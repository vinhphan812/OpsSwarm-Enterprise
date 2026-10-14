"""G04 Guard Gate (#51): a stale decision is blocked, then a refreshed decision proceeds.

Runs the real API app with the in-process Live Twin and drives every live
action through ``POST /simulations/{id}/approve``:

1. The investigator and planner build D1 from Live Twin reads at version N.
2. A concurrent write moves the relevant SKU to N+1 (the controlled stale mutation).
3. D1 is submitted: the guard must answer REFRESH_REQUIRED or DENY, no commit
   authorization is redeemed, and the Executor writes nothing.
4. ``replan`` refreshes evidence and plans D2, which is approved through the same
   route and changes the Live Twin.

The model is ``FakeLlmProvider`` with scripted tool calls and plan JSON; the tools
themselves execute against the Live Twin, and the guard, token and Executor are the
production code. DEMO_AND_ACCEPTANCE.md §3 allows the seed and the stale mutation to
be controlled. Run with a real provider for the model-driven proof.

Usage::

    python tests/e2e/gates/g04_guard_gate.py --out g04-evidence.json

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from retailtwin_api.agents.investigator.evidence import bind_read_port, investigate
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.replan import ReplanStatus, replan
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry, build_store_registry
from retailtwin_api.agents.planner.plans import plan
from retailtwin_api.contracts import Decision
from retailtwin_api.decisions import InMemoryDecisionSource
from retailtwin_api.guard.decision_context_guard import (
    DecisionContextGuard,
    GuardPolicy,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding
from retailtwin_api.llm.contracts import LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.main import create_app
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.simulation_repository import InMemorySimulationRepository
from retailtwin_api.simulation_schemas import SimulationDetail, SimulationState

GATE = "G04"
ISSUE = 51
STORE = "store-001"
SKU = "P001"
SHELF = "A01"
SLOT = "A01-S01"
REPLENISH = 12


class _GateSimulations(InMemorySimulationRepository):
    """The review routes' simulation store, with a way to record new simulations."""

    def put(self, simulation: SimulationDetail) -> None:
        with self._lock:
            self._simulations[simulation.simulation_id] = simulation.model_copy(deep=True)


class _Logs(logging.Handler):
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
def _captured_logs() -> Iterator[_Logs]:
    logger = logging.getLogger("retailtwin_api")
    handler = _Logs()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _tool_calls() -> list[LlmToolCall]:
    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": SKU}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": SHELF}),
        LlmToolCall(id="sales", name="get_sales_history", arguments={"sku": SKU, "window_hours": 4}),
        LlmToolCall(id="forecast", name="forecast_demand", arguments={"sku": SKU, "horizon_hours": 4}),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": SKU}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
    ]


def _plan_json() -> str:
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


def _provider(cycles: int) -> FakeLlmProvider:
    responses: list[FakeLlmProvider.Response] = []
    for _ in range(cycles):
        responses.append(FakeLlmProvider.Response(tool_calls=_tool_calls(), finish_reason="tool_calls"))
        responses.append(FakeLlmProvider.Response(content=_plan_json(), finish_reason="stop"))
    return FakeLlmProvider(responses=responses)


def _registry(store: Any, observed_at: str) -> ToolRegistry:
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


def _simulation(client: TestClient, simulation_id: str, decision: Decision, correlation_id: str) -> SimulationDetail:
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


def _approve(client: TestClient, simulation_id: str, correlation_id: str) -> dict[str, Any]:
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


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=Path(__file__).parent
        ).stdout.strip()
    except Exception:
        return None


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def _run_id(given: str | None) -> str:
    return given or f"g04-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


def run_g04(run_id: str | None = None) -> dict[str, Any]:
    """Run the gate once and return its evidence. ``evidence["result"]`` is PASS or FAIL."""

    return _run(_run_id(run_id))


def _run(run_id: str) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    settings = Settings(
        _env_file=None,
        app_env="e2e-smoke",
        store_id=STORE,
        store_fixture_path=DEFAULT_FIXTURE,
        live_twin_backend="memory",
    )
    app = create_app(settings)
    simulations = _GateSimulations()
    decisions = InMemoryDecisionSource()
    app.state.simulations = simulations
    app.state.decisions = decisions
    provider = _provider(cycles=2)
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {}

    with _captured_logs() as logs, TestClient(app) as client:
        twin = app.state.live_twin
        registry = _registry(app.state.store, started.isoformat())
        event = StoreEvent(
            event_id=f"evt-{run_id}",
            correlation_id=run_id,
            event_type="sale.completed",
            store_id=STORE,
            sku=SKU,
            quantity=1,
            occurred_at=started,
            source="g04-gate",
        )
        start = InvestigationStart(investigation_id=f"inv-{event.event_id}", event=event)

        # 1. D1 from Live Twin reads at version N.
        at_n = client.get(f"/inventory/{SKU}").json()
        bundle = asyncio.run(investigate(start, provider=provider, registry=registry, collected_at=started))
        candidates = asyncio.run(
            plan(
                bundle,
                provider=provider,
                context_version=client.get("/store").json()["context_version"],
                context_timestamp=started,
            )
        )
        s1 = f"sim-{run_id}-d1"
        d1 = candidates[0].model_copy(update={"simulation_id": s1})
        simulations.put(_simulation(client, s1, d1, run_id))
        decisions.put(s1, d1)
        steps["d1"] = {
            "decision_id": d1.decision_id,
            "simulation_id": s1,
            "context_version": d1.context_version,
            "entity_versions": dict(d1.evidence[0].entity_versions),
            "is_sufficient": d1.evidence[0].is_sufficient,
            "actions": [action.model_dump() for action in d1.proposed_actions],
        }
        _check(
            checks,
            "d1_built_at_version_n",
            d1.evidence[0].entity_versions.get(SKU) == str(at_n["version"]) and d1.evidence[0].is_sufficient,
            f"D1 read {SKU} at version {d1.evidence[0].entity_versions.get(SKU)}; live was {at_n['version']}",
        )

        # 2. Controlled stale mutation: a concurrent sale moves the SKU to N+1.
        current = twin.get_inventory(STORE, SKU)
        twin.upsert_inventory(
            current.model_copy(update={"shelf_quantity": current.shelf_quantity - 1, "version": current.version + 1}),
            expected_version=current.version,
        )
        at_n1 = client.get(f"/inventory/{SKU}").json()
        store_before = client.get("/store").json()
        steps["stale_mutation"] = {"before": at_n, "after": at_n1}
        _check(
            checks,
            "relevant_entity_moved_to_n_plus_1",
            at_n1["version"] == at_n["version"] + 1,
            f"{SKU} version {at_n['version']} -> {at_n1['version']}",
        )

        # 3. Submit D1 through the approve route.
        refused = _approve(client, s1, run_id)
        after_stale = client.get(f"/inventory/{SKU}").json()
        store_after_stale = client.get("/store").json()
        d1_events = [e.model_dump(mode="json") for e in app.state.guard_audit.events(d1.decision_id)]
        s1_reviews = [r.model_dump(mode="json") for r in app.state.review_audit.get(s1)]
        steps["stale_submit"] = {
            "response": refused,
            "live_after": after_stale,
            "store_version_before": store_before["context_version"],
            "store_version_after": store_after_stale["context_version"],
            "guard_audit": d1_events,
            "review_audit": s1_reviews,
        }
        _check(
            checks,
            "stale_decision_refused",
            refused["verdict"] in ("REFRESH_REQUIRED", "DENY") and refused["status"] != "committed",
            f"verdict={refused['verdict']} reason={refused['reason_code']} detail={refused.get('detail_code')}",
        )
        failed_gate = (refused.get("guard") or {}).get("policy_result", {}).get("failed_gate")
        _check(
            checks,
            "guard_named_the_stale_entity",
            refused.get("detail_code") == "VERSION_STALE" and failed_gate == "context",
            f"failed_gate={failed_gate} live_versions={(refused.get('guard') or {}).get('policy_result', {}).get('entity_versions')}",
        )
        _check(
            checks,
            "no_usable_authorization",
            [e["stage"] for e in d1_events] == ["authorize"] and d1_events[0]["verdict"] != "ALLOW",
            "guard audit stages for D1: " + ",".join(f"{e['stage']}:{e['verdict']}" for e in d1_events)
            + " (a token is issued only from the binding of an ALLOW authorize; the commit stage is the"
            " recheck that follows one)",
        )
        _check(
            checks,
            "executor_wrote_nothing",
            after_stale == at_n1 and store_after_stale["context_version"] == store_before["context_version"],
            f"{SKU} stayed at version {after_stale['version']}; store stayed at {store_after_stale['context_version']}",
        )
        _check(
            checks,
            "audit_shows_the_rejection",
            len(s1_reviews) == 1
            and s1_reviews[0]["reason_code"] in ("VERSION_STALE", "DCG_DENY")
            and all(e["correlation_id"] == run_id for e in d1_events),
            f"review={[(r['verdict'], r['reason_code']) for r in s1_reviews]} correlation={[e['correlation_id'] for e in d1_events]}",
        )

        # 4. Refresh and re-plan; the new decision goes through the same approve route.
        approvals: list[dict[str, Any]] = []

        class _ApproveThroughRoute:
            def commit(self, decision: Decision, binding: CommitBinding) -> None:
                simulation_id = f"sim-{run_id}-r{len(approvals) + 1}"
                linked = decision.model_copy(update={"simulation_id": simulation_id})
                simulations.put(_simulation(client, simulation_id, linked, run_id))
                decisions.put(simulation_id, linked)
                answer = _approve(client, simulation_id, run_id)
                approvals.append({"decision_id": decision.decision_id, "simulation_id": simulation_id, "response": answer})
                if answer["verdict"] != "ALLOW":
                    raise RuntimeError(f"approve refused: {answer['reason_code']}")

        class _LiveContext:
            def context_version(self, store_id: str) -> str:
                return str(client.get("/store").json()["context_version"])

        gate = NoStaleCommit(DecisionContextGuard(twin, GuardPolicy.from_env()), app.state.guard_audit)
        result = asyncio.run(
            replan(
                d1,
                start,
                authorizer=gate,
                provider=provider,
                registry=registry,
                commit=_ApproveThroughRoute(),
                contexts=_LiveContext(),
                max_refreshes=1,
            )
        )
        final = client.get(f"/inventory/{SKU}").json()
        store_final = client.get("/store").json()
        committed_id = result.committed_decision_id
        d2_events = [e.model_dump(mode="json") for e in app.state.guard_audit.events(committed_id)] if committed_id else []
        steps["replan"] = {
            "result": {
                "status": result.status.value,
                "verdict": result.verdict.value if result.verdict else None,
                "reason_code": result.reason_code,
                "refresh_count": result.refresh_count,
                "decision_id": result.decision_id,
                "committed_decision_id": committed_id,
                "context_version": result.context_version,
            },
            "approvals": approvals,
            "guard_audit": d2_events,
            "live_after": final,
            "store_version_after": store_final["context_version"],
        }
        _check(
            checks,
            "replan_committed_a_new_decision",
            result.status is ReplanStatus.COMMITTED
            and result.refresh_count == 1
            and committed_id is not None
            and committed_id != d1.decision_id,
            f"status={result.status.value} refreshes={result.refresh_count} D1={d1.decision_id} D2={committed_id}",
        )
        approved = approvals[-1]["response"] if approvals else {}
        _check(
            checks,
            "new_decision_approved_through_the_route",
            approved.get("verdict") == "ALLOW" and approved.get("status") == "committed",
            f"verdict={approved.get('verdict')} status={approved.get('status')} detail={approved.get('detail_code')}",
        )
        _check(
            checks,
            "live_twin_changed_only_by_the_new_decision",
            final["shelf_quantity"] == at_n1["shelf_quantity"] + REPLENISH
            and final["backroom_quantity"] == at_n1["backroom_quantity"] - REPLENISH
            and final["version"] == at_n1["version"] + 1
            and store_final["context_version"] != store_before["context_version"],
            f"{SKU} shelf {at_n1['shelf_quantity']}->{final['shelf_quantity']}, backroom "
            f"{at_n1['backroom_quantity']}->{final['backroom_quantity']}, version {at_n1['version']}->{final['version']}, "
            f"store {store_before['context_version']}->{store_final['context_version']}",
        )
        d1_final = [(e.stage, e.verdict.value) for e in app.state.guard_audit.events(d1.decision_id)]
        _check(
            checks,
            "stale_decision_never_committed",
            all(stage != "commit" for stage, _ in d1_final),
            f"D1 guard events after the run: {d1_final}",
        )
        all_events = [e.model_dump(mode="json") for e in app.state.guard_audit.events()]
        _check(
            checks,
            "correlation_preserved",
            all(e["correlation_id"] == run_id for e in all_events),
            f"{len(all_events)} guard audit events, all with correlation_id={run_id}",
        )
        steps["guard_audit_chain"] = [
            {k: e[k] for k in ("stage", "decision_id", "verdict", "reason_code", "failed_gate", "entity_versions", "at")}
            for e in all_events
        ]

    passed = all(item["passed"] for item in checks)
    return {
        "gate": GATE,
        "issue": ISSUE,
        "run_id": run_id,
        "result": "PASS" if passed else "FAIL",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "runtime": {
            "app": "retailtwin_api.main.create_app",
            "live_twin_backend": "memory (seeded from data/schemas/store-state.example.json)",
            "provider": "FakeLlmProvider: scripted tool calls and plan JSON; tools execute against the Live Twin",
            "provider_calls": provider.call_count,
        },
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the evidence JSON here")
    parser.add_argument("--run-id", help="run id; also the correlation id of every request")
    args = parser.parse_args(argv)
    evidence = run_g04(args.run_id)
    if args.out:
        args.out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"{GATE} run {evidence['run_id']}: {evidence['result']}")
    for item in evidence["checks"]:
        print(f"  [{'x' if item['passed'] else ' '}] {item['check']}: {item['detail']}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
