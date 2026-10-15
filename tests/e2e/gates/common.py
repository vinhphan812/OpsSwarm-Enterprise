"""Shared pieces of the release-gate harnesses: the real app, a scripted model, the approve route."""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from retailtwin_api.agents.investigator.evidence import bind_read_port
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry, build_store_registry
from retailtwin_api.contracts import Decision
from retailtwin_api.llm.contracts import LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.simulation_repository import InMemorySimulationRepository
from retailtwin_api.simulation_schemas import SimulationDetail, SimulationState

STORE = "store-001"
SKU = "P001"
SHELF = "A01"
SLOT = "A01-S01"
REPLENISH = 12


class GateSimulations(InMemorySimulationRepository):
    """The review routes' simulation store, with a way to record new simulations."""

    def put(self, simulation: SimulationDetail) -> None:
        with self._lock:
            self._simulations[simulation.simulation_id] = simulation.model_copy(deep=True)


class GateLogs(logging.Handler):
    """Collect one structured record per API log line."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "simulation_id", "verdict", "reason_code", "detail_code", "live_context_version"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        self.records.append(entry)


@contextmanager
def captured_logs() -> Iterator[GateLogs]:
    logger = logging.getLogger("retailtwin_api")
    handler = GateLogs()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def tool_calls() -> list[LlmToolCall]:
    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": SKU}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": SHELF}),
        LlmToolCall(id="sales", name="get_sales_history", arguments={"sku": SKU, "window_hours": 4}),
        LlmToolCall(id="forecast", name="forecast_demand", arguments={"sku": SKU, "horizon_hours": 4}),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": SKU}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
    ]


def plan_json() -> str:
    return json.dumps(
        {
            "candidates": [
                {
                    "reason": f"Replenish {SKU} from the backroom.",
                    "actions": [{"type": "replenish_shelf", "sku": SKU, "quantity": REPLENISH}],
                },
                {
                    "reason": f"Increase facings, then replenish {SKU}.",
                    "actions": [
                        {"type": "change_facings", "sku": SKU, "facings": 4},
                        {"type": "replenish_shelf", "sku": SKU, "quantity": REPLENISH},
                    ],
                },
            ]
        }
    )


def scripted_provider(cycles: int) -> FakeLlmProvider:
    responses: list[FakeLlmProvider.Response] = []
    for _ in range(cycles):
        responses.append(FakeLlmProvider.Response(tool_calls=tool_calls(), finish_reason="tool_calls"))
        responses.append(FakeLlmProvider.Response(content=plan_json(), finish_reason="stop"))
    return FakeLlmProvider(responses=responses)


def store_registry(store: Any, observed_at: str) -> ToolRegistry:
    """Store reads come from the Live Twin. The other mandatory sources are versioned fixtures."""

    registry = build_store_registry(store)

    def sales(args: Any) -> dict[str, Any]:
        return {"version": "g04-sales-1", "sku": args.sku, "observed_at": observed_at, "sales": []}

    def forecast(args: Any) -> dict[str, Any]:
        return {
            "version": "forecast-demand-v1",
            "sku": args.sku,
            "forecast_units": "18",
            "formula_id": "forecast-demand-v1",
            "observed_at": observed_at,
        }

    def promotions(args: Any) -> dict[str, Any]:
        return {"version": "0", "sku": args.sku, "observed_at": observed_at, "promotions": []}

    def planogram(_args: Any) -> dict[str, Any]:
        return {
            "version": "1",
            "observed_at": observed_at,
            "placements": [{"sku": SKU, "shelf_id": SHELF, "slot_id": SLOT, "facings": 3}],
        }

    bind_read_port(registry, "get_sales_history", sales)
    bind_read_port(registry, "forecast_demand", forecast)
    bind_read_port(registry, "get_promotions", promotions)
    bind_read_port(registry, "get_planogram", planogram)
    return registry


def simulation_for(client: TestClient, simulation_id: str, decision: Decision, correlation_id: str) -> SimulationDetail:
    view = client.get("/store").json()
    now = datetime.now(timezone.utc)
    return SimulationDetail.model_validate(
        {
            "simulation_id": simulation_id,
            "store_id": STORE,
            "base_context_version": view["context_version"],
            "status": "evaluated",
            "created_at": now,
            "updated_at": now,
            "provenance": "g04-gate",
            "actions": [action.model_dump() for action in decision.proposed_actions],
            "state": SimulationState.model_validate(
                {"store": view, "context_version": f"{simulation_id}:v1"}
            ),
            "correlation_id": correlation_id,
            "agent_id": decision.agent_id,
        }
    )


def approve(client: TestClient, simulation_id: str, correlation_id: str) -> dict[str, Any]:
    response = client.post(
        f"/simulations/{simulation_id}/approve",
        json={
            "base_context_version": client.app.state.live_context_version,  # type: ignore[attr-defined]
            "proposal_context_version": f"{simulation_id}:v1",
        },
        headers={"X-Correlation-ID": correlation_id},
    )
    body: dict[str, Any] = {"http_status": response.status_code, **response.json()}
    return body


def git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=Path(__file__).parent
        ).stdout.strip()
    except Exception:
        return None


def check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def gate_app() -> Any:
    """The real API app with the in-process Live Twin seeded from the committed fixture."""
    settings = Settings(
        _env_file=None,
        app_env="e2e-smoke",
        store_id=STORE,
        store_fixture_path=DEFAULT_FIXTURE,
        live_twin_backend="memory",
    )
    return create_app(settings)
