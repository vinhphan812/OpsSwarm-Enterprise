"""G05 Live Commit Gate (#52): a valid guarded decision changes the Live Twin.

Runs the real API app with the in-process Live Twin:

1. The investigator and planner build candidate decisions from Live Twin reads.
2. The simulator scores every candidate on a clone of Live with the deterministic
   KPI evaluator (``services/simulation/kpi``); the best-scored candidate is chosen.
3. ``POST /simulations/{id}/approve`` runs the guard on fresh reads, issues a signed
   single-use authorization for exactly those actions, and the Executor commits them.
4. The Live Twin shows exactly the authorized transition, every touched SKU and the
   store version advance by one, ``GET /store`` (what the 3D Live view reads) shows
   it, the audit is written, and the Verifier re-reads Live and confirms the state.

Failure cases in the same run: approving the committed simulation again, and a
decision that does not fit the backroom, both leave Live unchanged.

The model is ``FakeLlmProvider`` with scripted tool calls and plan JSON; tools, the
simulator, KPI evaluator, guard, token, Executor and Verifier are production code.

Usage::

    python tests/e2e/gates/g05_live_commit_gate.py --out g05-evidence.json

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[3]
if __package__ in (None, ""):  # run as a script: make ``gates`` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _root in (_REPO / "services" / "simulation", _REPO / "services" / "forecasting"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from gates.common import (  # noqa: E402
    SKU,
    STORE,
    GateSimulations,
    approve,
    captured_logs,
    check,
    gate_app,
    git_sha,
    scripted_provider,
    simulation_for,
    store_registry,
)
from kpi.evaluator import ChangeFacings as KpiChangeFacings  # noqa: E402
from kpi.evaluator import MoveProduct as KpiMoveProduct  # noqa: E402
from kpi.evaluator import ReplenishShelf as KpiReplenishShelf  # noqa: E402
from kpi.evaluator import SimulationSnapshot, SlotState, evaluate_candidate  # noqa: E402
from retailtwin_api.agents.investigator.evidence import investigate  # noqa: E402
from retailtwin_api.agents.observer.consumer import InvestigationStart  # noqa: E402
from retailtwin_api.agents.planner.plans import plan  # noqa: E402
from retailtwin_api.agents.simulator import LiveView, SlotView, simulate  # noqa: E402
from retailtwin_api.agents.verifier import InMemoryVerificationAudit, VerificationStatus, verify  # noqa: E402
from retailtwin_api.contracts import ChangeFacings, Decision, ReplenishShelf  # noqa: E402
from retailtwin_api.decisions import InMemoryDecisionSource  # noqa: E402
from retailtwin_api.schemas import ProductInventory, StoreEvent  # noqa: E402

GATE = "G05"
ISSUE = 52
# Demand and price the simulator needs. The forecast port reports 18 units over 4 hours.
VELOCITY = "4.5"
PRICE = "2.5"


def _kpi_actions(actions: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
    converted: list[Any] = []
    for action in actions:
        kind = action["type"]
        if kind == "replenish_shelf":
            converted.append(KpiReplenishShelf(sku=action["sku"], quantity=action["quantity"]))
        elif kind == "change_facings":
            converted.append(KpiChangeFacings(sku=action["sku"], facings=action["facings"]))
        elif kind == "move_product":
            converted.append(KpiMoveProduct(sku=action["sku"], from_slot=action["from_slot"], to_slot=action["to_slot"]))
        else:
            raise ValueError(kind)
    return tuple(converted)


def _snapshot(snapshot: Mapping[str, Any]) -> SimulationSnapshot:
    return SimulationSnapshot(
        simulation_id=snapshot["simulation_id"],
        store_id=snapshot["store_id"],
        context_version=snapshot["context_version"],
        correlation_id=snapshot["correlation_id"],
        observed_at=datetime.fromisoformat(snapshot["observed_at"]),
        slots=tuple(
            SlotState(
                sku=slot["sku"],
                slot_id=slot["slot_id"],
                shelf_quantity=slot["shelf_quantity"],
                backroom_quantity=slot["backroom_quantity"],
                facings=slot["facings"],
                sales_velocity_units_per_hour=Decimal(slot["sales_velocity_units_per_hour"]),
                price=Decimal(slot["price"]),
            )
            for slot in snapshot["slots"]
        ),
    )


def kpi_evaluator(snapshot: Mapping[str, Any], candidate_id: str, actions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The simulator's deterministic scorer: services/simulation/kpi, no model."""
    return evaluate_candidate(_snapshot(snapshot), candidate_id, _kpi_actions(actions)).as_dict()


def _live_view(client: TestClient, correlation_id: str, observed_at: datetime) -> LiveView:
    store = client.get("/store").json()
    return LiveView(
        store_id=store["store_id"],
        context_version=store["context_version"],
        correlation_id=correlation_id,
        observed_at=observed_at,
        slots=tuple(
            SlotView(
                sku=item["sku"],
                slot_id=item["slot_id"],
                shelf_quantity=item["shelf_quantity"],
                backroom_quantity=item["backroom_quantity"],
                facings=item["facings"],
                sales_velocity_units_per_hour=VELOCITY,
                price=PRICE,
            )
            for item in store["products"]
        ),
    )


def _expected(before: dict[str, Any], decision: Decision) -> dict[str, Any]:
    after = dict(before)
    for action in decision.proposed_actions:
        if isinstance(action, ReplenishShelf):
            after["shelf_quantity"] += action.quantity
            after["backroom_quantity"] -= action.quantity
        elif isinstance(action, ChangeFacings):
            after["facings"] = action.facings
        else:
            after["slot_id"] = action.to_slot
    after["version"] = before["version"] + 1
    return after


def _run_id(given: str | None) -> str:
    return given or f"g05-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


def run_g05(run_id: str | None = None) -> dict[str, Any]:
    """Run the gate once and return its evidence. ``evidence["result"]`` is PASS or FAIL."""

    return _run(_run_id(run_id))


def _run(run_id: str) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    app = gate_app()
    simulations = GateSimulations()
    decisions = InMemoryDecisionSource()
    app.state.simulations = simulations
    app.state.decisions = decisions
    provider = scripted_provider(cycles=1)
    verification_audit = InMemoryVerificationAudit()
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {}

    with captured_logs() as logs, TestClient(app) as client:
        registry = store_registry(app.state.store, started.isoformat())
        event = StoreEvent(
            event_id=f"evt-{run_id}",
            correlation_id=run_id,
            event_type="sale.completed",
            store_id=STORE,
            sku=SKU,
            quantity=1,
            occurred_at=started,
            source="g05-gate",
        )
        start = InvestigationStart(investigation_id=f"inv-{event.event_id}", event=event)

        # 1-2. Candidates from Live reads, scored on a clone of Live.
        before = client.get(f"/inventory/{SKU}").json()
        store_before = client.get("/store").json()
        bundle = asyncio.run(investigate(start, provider=provider, registry=registry, collected_at=started))
        candidates = asyncio.run(
            plan(bundle, provider=provider, context_version=store_before["context_version"], context_timestamp=started)
        )
        simulated = simulate(candidates, _live_view(client, run_id, started), evaluate=kpi_evaluator)
        ranked = sorted(simulated.candidates, key=lambda item: item.kpi.kpi_score, reverse=True)
        chosen = ranked[0].decision
        steps["simulation"] = {
            "simulation_id": simulated.simulation_id,
            "context_version": simulated.context_version,
            "candidates": [
                {
                    "decision_id": item.decision.decision_id,
                    "kpi_score": item.kpi.kpi_score,
                    "formula_id": item.evaluation.get("formula_id"),
                    "actions": [action.model_dump() for action in item.decision.proposed_actions],
                }
                for item in ranked
            ],
            "chosen": chosen.decision_id,
        }
        check(
            checks,
            "candidate_was_simulated",
            chosen.simulation_id == simulated.simulation_id
            and chosen.expected_impact.kpi_score == ranked[0].kpi.kpi_score
            and all(item.evaluation.get("formula_id") == "simulation-kpi-v1" for item in ranked),
            f"{len(ranked)} candidates scored by simulation-kpi-v1; chose {chosen.decision_id} "
            f"(kpi_score={ranked[0].kpi.kpi_score}) on {simulated.simulation_id}",
        )
        check(
            checks,
            "simulation_left_live_unchanged",
            client.get(f"/inventory/{SKU}").json() == before,
            f"{SKU} still at version {before['version']} after scoring",
        )

        # 3. Approve through the route.
        simulation_id = simulated.simulation_id
        simulations.put(simulation_for(client, simulation_id, chosen, run_id))
        decisions.put(simulation_id, chosen)
        approved = approve(client, simulation_id, run_id)
        after = client.get(f"/inventory/{SKU}").json()
        store_after = client.get("/store").json()
        events = [e.model_dump(mode="json") for e in app.state.guard_audit.events(chosen.decision_id)]
        reviews = [r.model_dump(mode="json") for r in app.state.review_audit.get(simulation_id)]
        guard = approved.get("guard") or {}
        steps["commit"] = {
            "decision_id": chosen.decision_id,
            "simulation_id": simulation_id,
            "response": approved,
            "live_before": before,
            "live_after": after,
            "store_version_before": store_before["context_version"],
            "store_version_after": store_after["context_version"],
            "guard_audit": events,
            "review_audit": reviews,
        }
        check(
            checks,
            "guard_allowed_on_fresh_reads",
            approved.get("verdict") == "ALLOW"
            and guard.get("verdict") == "ALLOW"
            and all(item["passed"] for item in guard.get("policy_result", {}).get("checks", [])),
            "gates: " + ",".join(
                f"{item['gate']}={'pass' if item['passed'] else 'fail'}"
                for item in guard.get("policy_result", {}).get("checks", [])
            ),
        )
        check(
            checks,
            "authorization_redeemed_for_these_actions",
            [(e["stage"], e["verdict"]) for e in events] == [("authorize", "ALLOW"), ("commit", "ALLOW")]
            and approved.get("detail_code") == "COMMITTED"
            and events[0]["context_hash"] == guard.get("context_hash"),
            "guard audit: " + ",".join(f"{e['stage']}:{e['verdict']}" for e in events)
            + f"; the commit-stage recheck runs only after the Executor redeems a token bound to the "
            f"decision's ordered action hashes; context_hash={guard.get('context_hash', '')[:12]}…",
        )
        expected = _expected(before, chosen)
        check(
            checks,
            "live_twin_shows_exactly_the_authorized_transition",
            after == expected,
            f"expected {_delta(before, expected)}; observed {_delta(before, after)}",
        )
        check(
            checks,
            "live_version_incremented",
            after["version"] == before["version"] + 1
            and store_after["context_version"] != store_before["context_version"]
            and approved.get("live_context_version") == store_after["context_version"],
            f"{SKU} version {before['version']}->{after['version']}; store "
            f"{store_before['context_version']}->{store_after['context_version']}",
        )
        store_row = next(item for item in store_after["products"] if item["sku"] == SKU)
        check(
            checks,
            "live_view_source_reflects_the_commit",
            store_row == after,
            "GET /store (read by the 3D Live view) carries the committed row",
        )
        check(
            checks,
            "audit_written",
            len(reviews) == 1
            and (reviews[0]["verdict"], reviews[0]["reason_code"]) == ("ALLOW", "APPROVED")
            and all(e["correlation_id"] == run_id for e in events),
            f"review={[(r['verdict'], r['reason_code']) for r in reviews]}; guard events carry correlation_id={run_id}",
        )

        # 4. Verifier re-reads Live.
        # No post-action KPI observation exists yet, so none is passed. Recomputing the
        # simulator's score from its own inputs would not be an observation.
        report = verify(
            chosen,
            {SKU: ProductInventory.model_validate(before)},
            app.state.store,
            verification_audit,
            correlation_id=run_id,
        )
        steps["verification"] = report.model_dump(mode="json")
        state_verified = bool(report.checks) and all(item.reason_code == "VERIFIED" for item in report.checks)
        check(
            checks,
            "verifier_confirmed_the_live_state",
            state_verified and report.status is not VerificationStatus.REGRESSION,
            f"re-read {','.join(item.sku + '=' + item.reason_code for item in report.checks)}; "
            f"report status={report.status.value} reason={report.reason_code}",
        )
        steps["verification_note"] = (
            "State is verified by re-reading Live. The decision carries a simulated KPI and no observed "
            "post-action KPI exists yet, so the Verifier reports KPI_UNOBSERVED for the KPI half."
        )

        # Failure cases.
        settled = client.get(f"/inventory/{SKU}").json()
        again = approve(client, simulation_id, run_id)
        check(
            checks,
            "committed_simulation_cannot_commit_again",
            again.get("verdict") == "DENY" and client.get(f"/inventory/{SKU}").json() == settled,
            f"second approve: verdict={again.get('verdict')} reason={again.get('reason_code')}; Live unchanged",
        )
        infeasible_id = f"{simulation_id}-infeasible"
        too_big = chosen.model_copy(
            update={
                "decision_id": f"{chosen.decision_id}-infeasible",
                "simulation_id": infeasible_id,
                "proposed_actions": [ReplenishShelf(sku=SKU, quantity=settled["backroom_quantity"] + 1)],
                "evidence": [
                    chosen.evidence[0].model_copy(
                        update={
                            "entity_versions": {SKU: str(settled["version"])},
                            "collected_at": datetime.now(timezone.utc),
                            "freshness": datetime.now(timezone.utc),
                        }
                    )
                ],
                "context_timestamp": datetime.now(timezone.utc),
            }
        )
        simulations.put(simulation_for(client, infeasible_id, too_big, run_id))
        decisions.put(infeasible_id, too_big)
        refused = approve(client, infeasible_id, run_id)
        check(
            checks,
            "infeasible_decision_changes_nothing",
            refused.get("verdict") == "DENY"
            and refused.get("detail_code") == "INFEASIBLE_ACTION"
            and client.get(f"/inventory/{SKU}").json() == settled,
            f"replenish {settled['backroom_quantity'] + 1} with {settled['backroom_quantity']} in the backroom: "
            f"verdict={refused.get('verdict')} detail={refused.get('detail_code')}; Live unchanged",
        )
        steps["failure_cases"] = {"approve_again": again, "infeasible": refused}
        all_events = [e.model_dump(mode="json") for e in app.state.guard_audit.events()]
        check(
            checks,
            "correlation_preserved",
            all(e["correlation_id"] == run_id for e in all_events),
            f"{len(all_events)} guard audit events, all with correlation_id={run_id}",
        )
        steps["guard_audit_chain"] = [
            {k: e[k] for k in ("stage", "decision_id", "verdict", "reason_code", "failed_gate", "entity_versions", "at")}
            for e in all_events
        ]
        steps["verification_audit"] = [event.model_dump(mode="json") for event in verification_audit.events]

    passed = all(item["passed"] for item in checks)
    return {
        "gate": GATE,
        "issue": ISSUE,
        "run_id": run_id,
        "result": "PASS" if passed else "FAIL",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "runtime": {
            "app": "retailtwin_api.main.create_app",
            "live_twin_backend": "memory (seeded from data/schemas/store-state.example.json)",
            "provider": "FakeLlmProvider: scripted tool calls and plan JSON; tools execute against the Live Twin",
            "simulator": "agents.simulator.simulate + services/simulation/kpi (simulation-kpi-v1)",
            "provider_calls": provider.call_count,
        },
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> str:
    keys = ("slot_id", "facings", "shelf_quantity", "backroom_quantity", "version")
    return ", ".join(f"{k} {before[k]}->{after[k]}" for k in keys if before[k] != after[k]) or "no change"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the evidence JSON here")
    parser.add_argument("--run-id", help="run id; also the correlation id of every request")
    args = parser.parse_args(argv)
    evidence = run_g05(args.run_id)
    if args.out:
        args.out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"{GATE} run {evidence['run_id']}: {evidence['result']}")
    for item in evidence["checks"]:
        print(f"  [{'x' if item['passed'] else ' '}] {item['check']}: {item['detail']}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
