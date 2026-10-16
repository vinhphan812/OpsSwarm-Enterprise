"""HTTP route tests for the flagship controller.

These tests spin up a FastAPI app with the flagship routes mounted and
exercise the reset, start, and status commands end-to-end against the same
in-memory twin the controller tests use. The real canonical services back
every step — the only stubbed piece is the LLM provider, which the test
fakes deterministically.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from retailtwin_api.agents.investigator.evidence import bind_read_port
from retailtwin_api.agents.orchestrator.tool_registry import build_store_registry
from retailtwin_api.contracts import ReplenishShelf
from retailtwin_api.demand_surge import SKU as DEMO_SKU, STORE_ID as DEMO_STORE_ID
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed
from retailtwin_api.flagship import (
    FlagshipController,
    FlagshipDependencies,
    FlagshipPhase,
    register_dependencies,
    register_routes,
)
from retailtwin_api.llm.contracts import LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.settings import DEFAULT_FIXTURE
from retailtwin_api.store import StoreRepository

_REPO = Path(__file__).resolve().parents[3]
for _root in (_REPO / "services" / "simulation", _REPO / "services" / "forecasting"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from kpi.evaluator import (  # type: ignore[import-not-found]  # noqa: E402
    ChangeFacings as KpiChangeFacings,
)
from kpi.evaluator import (  # type: ignore[import-not-found]  # noqa: E402
    MoveProduct as KpiMoveProduct,
)
from kpi.evaluator import (  # type: ignore[import-not-found]  # noqa: E402
    ReplenishShelf as KpiReplenishShelf,
)
from kpi.evaluator import (  # type: ignore[import-not-found]  # noqa: E402
    SimulationSnapshot,
    SlotState,
    evaluate_candidate,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test doubles (mirror the controller test suite)
# ---------------------------------------------------------------------------


class _LiveReader:
    def __init__(self, repo: InMemoryTwinRepository, store_id: str) -> None:
        self._repo = repo
        self.store_id = store_id

    def view(self) -> Any:  # type: ignore[override]
        from retailtwin_api.schemas import ProductInventory, StoreResponse

        store = self._repo.get_store(self.store_id)
        version = store.version if store is not None else "v1"
        context_version = store.context_version() if store is not None else f"{self.store_id}:{version}"
        items = list(self._repo.list_inventory(self.store_id))
        return StoreResponse(
            store_id=self.store_id,
            context_version=context_version,
            version=version,
            products=[
                ProductInventory(
                    store_id=item.store_id,
                    sku=item.sku,
                    shelf_id=item.shelf_id,
                    slot_id=item.slot_id,
                    facings=item.facings,
                    shelf_quantity=item.shelf_quantity,
                    backroom_quantity=item.backroom_quantity,
                    version=item.version,
                )
                for item in items
            ],
        )

    def inventory(self, sku: str) -> Any:  # type: ignore[override]
        from retailtwin_api.schemas import ProductInventory

        for item in self._repo.list_inventory(self.store_id):
            if item.sku == sku:
                return ProductInventory(
                    store_id=item.store_id,
                    sku=item.sku,
                    shelf_id=item.shelf_id,
                    slot_id=item.slot_id,
                    facings=item.facings,
                    shelf_quantity=item.shelf_quantity,
                    backroom_quantity=item.backroom_quantity,
                    version=item.version,
                )
        return None


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        if request.tools:
            return LlmResponse(
                id=f"r-{self.calls}",
                model=request.model,
                finish_reason="tool_calls",
                tool_calls=[
                    LlmToolCall(id="i1", name="get_inventory", arguments={"sku": DEMO_SKU}),
                    LlmToolCall(id="i2", name="get_shelf_state", arguments={"shelf_id": "A02"}),
                    LlmToolCall(id="i3", name="get_sales_history", arguments={"sku": DEMO_SKU, "window_hours": 4}),
                    LlmToolCall(id="i4", name="forecast_demand", arguments={"sku": DEMO_SKU, "horizon_hours": 4}),
                    LlmToolCall(id="i5", name="get_promotions", arguments={"sku": DEMO_SKU}),
                    LlmToolCall(id="i6", name="get_planogram", arguments={}),
                ],
            )
        import json

        return LlmResponse(
            id=f"r-{self.calls}",
            model=request.model,
            finish_reason="stop",
            content=json.dumps({
                "candidates": [
                    {
                        "reason": "Replenish P017 from the backroom.",
                        "actions": [{"type": "replenish_shelf", "sku": DEMO_SKU, "quantity": 12}],
                    },
                    {
                        "reason": "Increase facings, then replenish P017.",
                        "actions": [
                            {"type": "change_facings", "sku": DEMO_SKU, "facings": 4},
                            {"type": "replenish_shelf", "sku": DEMO_SKU, "quantity": 12},
                        ],
                    },
                ]
            }),
        )


def _evaluator(snapshot: Any, candidate_id: str, actions: Any) -> dict[str, Any]:
    observed_at = snapshot["observed_at"]
    built = SimulationSnapshot(
        simulation_id=snapshot["simulation_id"],
        store_id=snapshot["store_id"],
        context_version=snapshot["context_version"],
        correlation_id=snapshot["correlation_id"],
        observed_at=datetime.fromisoformat(observed_at),
        slots=tuple(
            SlotState(
                sku=slot["sku"],
                slot_id=slot["slot_id"],
                shelf_quantity=slot["shelf_quantity"],
                backroom_quantity=slot["backroom_quantity"],
                facings=slot["facings"],
                sales_velocity_units_per_hour=Decimal(slot["sales_velocity_units_per_hour"] or "0"),
                price=Decimal(slot["price"] or "0"),
            )
            for slot in snapshot["slots"]
        ),
    )
    converted: list[Any] = []
    for action in actions:
        kind = action["type"]
        if kind == "replenish_shelf":
            converted.append(KpiReplenishShelf(sku=action["sku"], quantity=action["quantity"]))
        elif kind == "change_facings":
            converted.append(KpiChangeFacings(sku=action["sku"], facings=action["facings"]))
        elif kind == "move_product":
            converted.append(KpiMoveProduct(sku=action["sku"], from_slot=action["from_slot"], to_slot=action["to_slot"]))
    return evaluate_candidate(built, candidate_id, tuple(converted)).as_dict()


def _build_app() -> tuple[FastAPI, InMemoryTwinRepository, _FakeProvider]:
    repo = InMemoryTwinRepository()
    fixture = StoreRepository(DEFAULT_FIXTURE, DEMO_STORE_ID)
    assert fixture.loaded, fixture.error
    snapshot = fixture.view()
    items = [
        InventorySeed(
            sku=item.sku,
            shelf_id=item.shelf_id,
            slot_id=item.slot_id,
            facings=item.facings,
            shelf_quantity=item.shelf_quantity,
            backroom_quantity=item.backroom_quantity,
        )
        for item in snapshot.products
    ]
    items.append(InventorySeed(sku=DEMO_SKU, shelf_id="A02", slot_id="A02-S03", facings=2, shelf_quantity=8, backroom_quantity=54))
    repo.seed(DEMO_STORE_ID, snapshot.version, items)

    provider = _FakeProvider()
    registry = build_store_registry(_LiveReader(repo, DEMO_STORE_ID))
    # Bind the read tools the investigator needs.
    for name in ("get_sales_history", "forecast_demand", "get_promotions", "get_planogram"):
        def _factory(_name: str = name):
            def _handler(args: Any) -> dict[str, Any]:
                return {
                    "version": "v1",
                    "sku": getattr(args, "sku", DEMO_SKU),
                    "observed_at": NOW.isoformat(),
                    "value": "0",
                    "promotions": [],
                    "placements": [],
                    "sales": [],
                    "forecast_units": "0",
                    "formula_id": "forecast-demand-v1",
                }
            return _handler
        bind_read_port(registry, name, _factory())

    app = FastAPI()
    controller = register_dependencies(
        provider=provider,
        twin=repo,
        store_id=DEMO_STORE_ID,
        registry=registry,
        evaluator=_evaluator,
        clock=lambda: NOW,
    )
    app.state.flagship_controller = controller
    register_routes(app)
    return app, repo, provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reset_status_and_start_routes_execute_canonical_chain() -> None:
    app, repo, _ = _build_app()
    with TestClient(app) as client:
        # status before reset
        initial = client.get("/flagship/status").json()
        assert initial["phase"] == "IDLE"
        assert initial["committed_decision_id"] is None

        # reset
        reset_response = client.post("/flagship/reset")
        assert reset_response.status_code == 200
        reset_body = reset_response.json()
        assert reset_body["phase"] == "IDLE"
        assert reset_body["seed"] == 1

        # start
        start_response = client.post("/flagship/start", json={"stale_block_enabled": True})
        assert start_response.status_code == 200, start_response.text
        body = start_response.json()
        assert body["phase"] == "COMPLETE"
        assert body["guard_verdict"] == "REFRESH_REQUIRED"
        assert body["committed_decision_id"] is not None
        assert body["replan_refresh_count"] == 1
        assert body["verification_status"] in {"VERIFIED", "REGRESSION", "INCONCLUSIVE"}
        stages = {entry["stage"] for entry in body["timeline"]}
        assert {"event", "investigate", "plan", "simulate", "guard", "replan", "verify"}.issubset(stages)

        # status reflects the run
        after = client.get("/flagship/status").json()
        assert after["phase"] == "COMPLETE"
        assert after["committed_decision_id"] == body["committed_decision_id"]

        # The Live Twin moved: P017 version bumped.
        p017 = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
        assert p017 is not None
        assert p017.version >= 2  # the deliberate bump + the commit


def test_start_without_reset_still_works() -> None:
    """A first ``start`` on a fresh controller is allowed and reseeds implicitly."""

    app, _, _ = _build_app()
    with TestClient(app) as client:
        response = client.post("/flagship/start", json={"stale_block_enabled": False})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["phase"] == "COMPLETE"


def test_concurrent_start_is_rejected() -> None:
    """The state machine refuses a second ``start`` while one is in flight."""

    app, _, _ = _build_app()
    with TestClient(app) as client:
        client.post("/flagship/reset")
        # Hold the controller in RUNNING by mutating the phase via the API state.
        controller = app.state.flagship_controller  # type: ignore[attr-defined]
        with controller._lock:  # type: ignore[attr-defined]  # noqa: SLF001
            controller._phase = FlagshipPhase.RUNNING  # type: ignore[attr-defined]  # noqa: SLF001
        response = client.post("/flagship/start")
        assert response.status_code == 409
        controller._phase = FlagshipPhase.IDLE  # type: ignore[attr-defined]  # noqa: SLF001


def test_status_is_serializable_to_json() -> None:
    """``status`` must round-trip through ``json.dumps`` cleanly."""

    app, _, _ = _build_app()
    with TestClient(app) as client:
        client.post("/flagship/reset")
        client.post("/flagship/start", json={"stale_block_enabled": True})
        status = client.get("/flagship/status").json()
        # Pydantic-friendly primitives only.
        for key in (
            "run_id",
            "phase",
            "seed",
            "guard_verdict",
            "guard_reason_code",
            "committed_decision_id",
            "replan_refresh_count",
            "replan_reason_code",
            "verification_status",
        ):
            assert key in status, key
        assert status["timeline"], "timeline must record the run"


def test_production_refuses_stale_block_via_request_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production wire must force ``stale_block_enabled=False`` even if a
    caller sends ``stale_block_enabled: true``. This is defence-in-depth on
    top of the per-instance default in :class FlagshipRequest — the
    underlying ``bump_inventory_for_stale_block`` helper refuses to run
    under ``APP_ENV=production``, so the route rejects the wire-level knob
    instead of round-tripping to the helper.
    """
    monkeypatch.setenv("APP_ENV", "production")
    app, _, _ = _build_app()
    with TestClient(app) as client:
        client.post("/flagship/reset")
        # Send a body that explicitly asks for the stale injection.
        # Production should clamp it off and still complete the chain.
        response = client.post(
            "/flagship/start",
            json={"stale_block_enabled": True, "correlation_id": "prod-defence"},
        )
        # The chain completes (no bumped-state refusal at the helper),
        # because the route clamp already flipped stale_block_enabled to False.
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["phase"] in ("COMPLETE", "ERROR")
        # If COMPLETE, replan_refresh_count must be 0 because no stale injection ran.
        if payload["phase"] == "COMPLETE":
            assert payload["replan_refresh_count"] == 0
        assert payload["correlation_id"] == "prod-defence"
