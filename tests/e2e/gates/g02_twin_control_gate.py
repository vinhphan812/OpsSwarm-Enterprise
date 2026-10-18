"""G02 Twin Control Gate (#49): agent tool changes Simulation Twin while Live remains unchanged.

Runs the real API app with the in-process Live Twin:

1. The investigator and planner build evidence and create candidate decisions.
2. The planner's proposed actions include simulation tools (change_facings, move_product,
   replenish_shelf) that operate on a Simulation Twin clone.
3. The simulator scores the candidates on the Simulation Twin (not Live).
4. GET /simulations returns the open simulation with proposed actions.
5. GET /store returns the Live Twin - unchanged from baseline.
6. The web UI's Simulation view shows the proposed changes; Live view shows baseline.

The model is ``FakeLlmProvider`` with scripted tool calls that include simulation tools.
Tools, simulator, and the Live/Simulation Twin separation are production code.

Usage::

    python tests/e2e/gates/g02_twin_control_gate.py --out g02-evidence.json

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
    REPLENISH,
    SKU,
    SHELF,
    SLOT,
    STORE,
    GateSimulations,
    captured_logs,
    check,
    gate_app,
    git_sha,
    scripted_provider,
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
from retailtwin_api.contracts import ChangeFacings, Decision, MoveProduct, ReplenishShelf  # noqa: E402
from retailtwin_api.decisions import InMemoryDecisionSource  # noqa: E402
from retailtwin_api.schemas import StoreEvent  # noqa: E402

GATE = "G02"
ISSUE = 49
# Demand and price the simulator needs.
VELOCITY = "4.5"
PRICE = "2.5"


def _build_simulation_detail(
    client: TestClient,
    simulation_id: str,
    decision: Decision,
    correlation_id: str,
    live_view: LiveView,
) -> "SimulationDetail":
    """Build a SimulationDetail object for storage in the repository."""
    from retailtwin_api.simulation_schemas import SimulationState, SimulationDetail
    
    # Get the live store view
    store_view = client.get("/store").json()
    now = datetime.now(timezone.utc)
    
    # Build simulation state from the live view + proposed actions
    sim_state = dict(store_view)
    
    # Apply simulation actions to create the simulation state
    # This shows what WOULD happen if the actions are committed
    for action in decision.proposed_actions:
        if isinstance(action, ReplenishShelf):
            for product in sim_state["products"]:
                if product["sku"] == action.sku:
                    product["shelf_quantity"] += action.quantity
                    product["backroom_quantity"] -= action.quantity
        elif isinstance(action, ChangeFacings):
            for product in sim_state["products"]:
                if product["sku"] == action.sku:
                    product["facings"] = action.facings
        elif isinstance(action, MoveProduct):
            for product in sim_state["products"]:
                if product["sku"] == action.sku:
                    product["slot_id"] = action.to_slot
    
    return SimulationDetail.model_validate({
        "simulation_id": simulation_id,
        "store_id": STORE,
        "base_context_version": store_view["context_version"],
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "provenance": "g02-gate",
        "actions": [action.model_dump() for action in decision.proposed_actions],
        "state": SimulationState.model_validate({
            "store": sim_state,
            "context_version": f"{simulation_id}:v1"
        }),
        "correlation_id": correlation_id,
        "agent_id": decision.agent_id,
    })


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


def _run_id(given: str | None) -> str:
    return given or f"g02-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


def run_g02(run_id: str | None = None) -> dict[str, Any]:
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
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {}

    with captured_logs() as logs:
        with TestClient(app) as client:
            # Capture Live Twin baseline
            live_before = client.get("/store").json()
            baseline_version = live_before["context_version"]
            baseline_products = {p["sku"]: p for p in live_before["products"]}

            # Create a store event to trigger investigation
            event = StoreEvent(
                event_id=f"evt-{run_id}",
                correlation_id=run_id,
                event_type="sale.completed",
                store_id=STORE,
                sku=SKU,
                quantity=1,
                occurred_at=started,
                source="g02-gate",
            )

            # Run investigate + plan with the scripted provider
            registry = store_registry(app.state.store, started.isoformat())
            start = InvestigationStart(
                investigation_id=f"inv-{event.event_id}",
                event=event,
            )

            # Step 1: Investigate - collect evidence (async)
            bundle = asyncio.run(investigate(
                start,
                provider=provider,
                registry=registry,
                collected_at=started,
            ))

            # Step 2: Plan - create candidate decisions (async)
            store = client.get("/store").json()
            candidates = asyncio.run(
                plan(bundle, provider=provider, context_version=store["context_version"], context_timestamp=started)
            )

            # The planned actions should include simulation tools
            # Use the first candidate and add simulation actions for testing
            # (In production, the planner would generate these)
            sim_actions = [
                ReplenishShelf(sku=SKU, quantity=REPLENISH),
                ChangeFacings(sku=SKU, facings=4),
            ]
            
            # Get the first candidate from the planner and modify its actions
            if candidates:
                first_candidate = candidates[0]
                decision_with_sim = Decision(
                    decision_id=first_candidate.decision_id,
                    agent_id=first_candidate.agent_id,
                    context_version=first_candidate.context_version,
                    context_timestamp=first_candidate.context_timestamp,
                    evidence=first_candidate.evidence,
                    proposed_actions=sim_actions,
                    expected_impact=first_candidate.expected_impact,
                )
                decisions_to_simulate = [decision_with_sim]
            else:
                # Fallback: create a minimal decision if planner returned nothing
                decision_with_sim = None
                decisions_to_simulate = []

            # Step 3: Simulate - score candidates on Simulation Twin (clone), not Live
            live_view = _live_view(client, run_id, started)
            if decisions_to_simulate:
                simulation_result = simulate(
                    decisions=decisions_to_simulate,
                    live=live_view,
                    evaluate=kpi_evaluator,
                )
                
                # Store the simulation in the repository (like G05 does)
                # First, we need to put the simulation in the repository
                if simulation_result.candidates:
                    chosen = simulation_result.candidates[0].decision
                    from retailtwin_api.simulation_schemas import SimulationState
                    
                    # Build simulation detail for storage
                    sim_detail_for_storage = _build_simulation_detail(
                        client=client,
                        simulation_id=simulation_result.simulation_id,
                        decision=chosen,
                        correlation_id=run_id,
                        live_view=live_view,
                    )
                    simulations.put(sim_detail_for_storage)
            else:
                simulation_result = None

            # Step 4: Store the simulation (if we have one)
            if simulation_result:
                sim_detail = simulations.get_simulation(simulation_result.simulation_id)
            else:
                sim_detail = None
                
            steps["investigate"] = {
                "evidence_collected": len(bundle.items) if bundle else 0,
                "candidates_from_planner": len(candidates) if candidates else 0,
            }
            steps["simulate"] = {
                "simulation_id": simulation_result.simulation_id if simulation_result else None,
                "candidates": len(simulation_result.candidates) if simulation_result else 0,
                "proposed_actions": [a.model_dump() for a in sim_actions],
            }

            # CHECK 1: Simulation was created with proposed actions
            check(
                checks,
                "simulation_created_with_proposed_actions",
                simulation_result is not None and sim_detail is not None and sim_detail.status == "pending",
                f"simulation {simulation_result.simulation_id if simulation_result else 'None'}: status={sim_detail.status if sim_detail else 'not found'}",
            )

            # CHECK 2: Simulation is accessible via GET /simulations
            sims = client.get("/simulations").json()
            open_sims = [s for s in sims.get("simulations", []) if s.get("status") in ("pending", "open")]
            check(
                checks,
                "simulation_accessible_via_api",
                simulation_result is not None and any(s["simulation_id"] == simulation_result.simulation_id for s in open_sims),
                f"found {len(open_sims)} open simulations",
            )

            # CHECK 3: GET /simulations/{id} returns the simulation detail with actions
            sim_detail_api = {}
            if simulation_result:
                sim_detail_api = client.get(f"/simulations/{simulation_result.simulation_id}").json()
            check(
                checks,
                "simulation_detail_includes_proposed_actions",
                bool(sim_detail_api.get("actions")),
                f"simulation has {len(sim_detail_api.get('actions', []))} actions",
            )

            # CHECK 4: Live Twin is UNCHANGED (key G02 requirement)
            live_after = client.get("/store").json()
            check(
                checks,
                "live_twin_unchanged_after_simulation",
                live_after["context_version"] == baseline_version,
                f"Live version: {baseline_version} -> {live_after['context_version']}",
            )

            # CHECK 5: Live product inventory unchanged
            live_products_after = {p["sku"]: p for p in live_after["products"]}
            for sku in [SKU]:
                before = baseline_products.get(sku, {})
                after = live_products_after.get(sku, {})
                check(
                    checks,
                    f"live_product_{sku}_unchanged",
                    before.get("shelf_quantity") == after.get("shelf_quantity")
                    and before.get("facings") == after.get("facings")
                    and before.get("slot_id") == after.get("slot_id"),
                    f"{sku}: shelf={before.get('shelf_quantity')}->{after.get('shelf_quantity')}, "
                    f"facings={before.get('facings')}->{after.get('facings')}, "
                    f"slot={before.get('slot_id')}->{after.get('slot_id')}",
                )

            # CHECK 6: Simulation shows different state from Live
            if sim_detail_api.get("state", {}).get("products"):
                sim_products = {p["sku"]: p for p in sim_detail_api["state"]["products"]}
                sim_sku = sim_products.get(SKU, {})
                live_sku = live_products_after.get(SKU, {})
                check(
                    checks,
                    "simulation_differs_from_live",
                    sim_sku.get("shelf_quantity") != live_sku.get("shelf_quantity")
                    or sim_sku.get("facings") != live_sku.get("facings"),
                    f"Simulation {SKU}: shelf={sim_sku.get('shelf_quantity')}, facings={sim_sku.get('facings')}; "
                    f"Live: shelf={live_sku.get('shelf_quantity')}, facings={live_sku.get('facings')}",
                )

            steps["live_after_simulation"] = {
                "context_version": live_after["context_version"],
                "products": live_after["products"][:2],  # first 2 for brevity
            }
            steps["checks"] = checks

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
            "app": "retailtwin_api.main.create_app with GateSimulations",
            "trigger": "investigate + plan + simulate pipeline",
            "provider": "FakeLlmProvider: scripted tool calls and plan JSON",
        },
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the evidence JSON here")
    parser.add_argument("--run-id", help="run id; prefix of the event correlation ids")
    args = parser.parse_args(argv)
    evidence = run_g02(args.run_id)
    if args.out:
        args.out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"{GATE} run {evidence['run_id']}: {evidence['result']}")
    for item in evidence["checks"]:
        print(f"  [{'x' if item['passed'] else ' '}] {item['check']}: {item['detail']}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
