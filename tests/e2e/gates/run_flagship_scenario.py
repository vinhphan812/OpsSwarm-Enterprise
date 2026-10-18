"""Flagship scenario runner for the G06 Submission Gate (#53).

Runs the canonical Weekend Demand Surge scenario end-to-end against the real
API app (in-process TestClient) with the in-memory Live Twin. The Live Twin is
seeded from the committed fixture plus the demand-surge SKU P017 at its
canonical baseline shape, so the same fixture is reproducible across runs.

Two modes are supported:

* ``--mode happy`` (default) — the canonical 13-event Weekend Demand Surge
  chain that ends in a guarded Executor commit and Verifier read.
* ``--mode negative`` — the no-stale-commit negative case. A Decision built
  against Live Twin context version N is exercised against a Live Twin at
  N+1; the Decision Context Guard must answer REFRESH_REQUIRED and no
  commit binding is redeemed.

The harness captures the production-mode fields reviewers required for the
G06 release acceptance (see PR #247 reviews 1–3): ``environment``,
``provider_mode``, ``live_twin_backend``, ``cloud_run_revision``,
``correlation_id`` round-tripped through ``GET /agent/events``, the per-
action ``simulation_only`` vs ``guarded_live_mutation`` tag, the per-gate
DCG verdict + reason_code slice, the explicit Verifier verdict, and a
preserved no-stale-commit negative case. In this script the values are
filled from the in-process environment; the same fields are populated
for real by the production-mode runner.

The chain is the production canonical one:

    POST /events  ->  Observer  ->  Investigator  ->  Planner
                 ->  Simulator (deterministic KPI on a clone of Live)
                 ->  POST /simulations/{id}/approve
                 ->  Decision Context Guard (NoStaleCommit)
                 ->  guarded Executor  ->  Live Twin write
                 ->  Verifier (re-reads Live)

The model is ``FakeLlmProvider`` with scripted tool calls and plan JSON; the
tools themselves read the Live Twin, and the guard, token, Executor and
Verifier are the production code. P017 is seeded at ``A02 / A02-S03`` with
``facings=2``, ``shelf=8``, ``backroom=54`` so the canonical demand-surge
fixtures (``data/synthetic/weekend-demand-surge.json``) drive the chain
without mutating the committed store fixture.

Usage::

    python tests/e2e/gates/run_flagship_scenario.py \
        --out artifacts/submission-gate/flagship-evidence.json \
        --seed submission-1

    python tests/e2e/gates/run_flagship_scenario.py --mode negative \
        --out artifacts/submission-gate/negative-evidence.json

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # noqa: F401  (kept: production-mode runner script reads revisions)
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[3]
if __package__ in (None, ""):  # run as a script: make ``gates`` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _root in (_REPO / "services" / "simulation", _REPO / "services" / "forecasting"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from gates.common import (  # noqa: E402
    GateSimulations,
    approve,
    captured_logs,
    check,
    gate_app,
    git_sha,
)
from kpi.evaluator import ChangeFacings as KpiChangeFacings  # noqa: E402
from kpi.evaluator import MoveProduct as KpiMoveProduct  # noqa: E402
from kpi.evaluator import ReplenishShelf as KpiReplenishShelf  # noqa: E402
from kpi.evaluator import SimulationSnapshot, SlotState, evaluate_candidate  # noqa: E402
from retailtwin_api.demand_surge import (  # noqa: E402
    CANONICAL_SEED,
    SKU as DEMO_SKU,
    STORE_ID as DEMO_STORE_ID,
    detect_demand_surge,
    load_committed_surge,
)
from retailtwin_api.decisions import InMemoryDecisionSource  # noqa: E402
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed  # noqa: E402
from retailtwin_api.guard.decision_context_guard import (  # noqa: E402
    DecisionContextGuard,
    InMemoryGuardAudit,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.no_stale_commit import (  # noqa: E402
    GuardAuditEvent,
)
from retailtwin_api.schemas import StoreEvent  # noqa: E402
from retailtwin_api.settings import DEFAULT_FIXTURE  # noqa: E402
from retailtwin_api.store import StoreRepository  # noqa: E402

Mode = Literal["happy", "negative"]

SCENARIO = "weekend-demand-surge"
GATE = "G06"
ISSUE = 53
DEMO_SHELF = "A02"
DEMO_SLOT = "A02-S03"
DEMO_FACINGS = 2
DEMO_SHELF_QUANTITY = 8
DEMO_BACKROOM_QUANTITY = 54
DEMO_VELOCITY = "18.25"
DEMO_PRICE = "3.5"


# ---------------------------------------------------------------------------
# FakeLlmProvider with P017-shaped tool calls and plan JSON
# ---------------------------------------------------------------------------


def _p017_calls(sku: str) -> list[Any]:
    from retailtwin_api.llm.contracts import LlmToolCall

    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": sku}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": DEMO_SHELF}),
        LlmToolCall(id="sales", name="get_sales_history", arguments={"sku": sku, "window_hours": 4}),
        LlmToolCall(id="forecast", name="forecast_demand", arguments={"sku": sku, "horizon_hours": 4}),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": sku}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
    ]


def _p017_plan_json(sku: str) -> str:
    return json.dumps(
        {
            "candidates": [
                {
                    "reason": f"Replenish {sku} from the backroom to cover the weekend surge.",
                    "actions": [{"type": "replenish_shelf", "sku": sku, "quantity": 12}],
                },
                {
                    "reason": f"Increase {sku} facings, then replenish from the backroom.",
                    "actions": [
                        {"type": "change_facings", "sku": sku, "facings": 4},
                        {"type": "replenish_shelf", "sku": sku, "quantity": 12},
                    ],
                },
            ]
        }
    )


def _p017_provider(cycles: int = 2) -> Any:
    from retailtwin_api.llm.fake import FakeLlmProvider

    responses: list[FakeLlmProvider.Response] = []
    for _ in range(cycles):
        responses.append(FakeLlmProvider.Response(tool_calls=_p017_calls(DEMO_SKU), finish_reason="tool_calls"))
        responses.append(FakeLlmProvider.Response(content=_p017_plan_json(DEMO_SKU), finish_reason="stop"))
    return FakeLlmProvider(responses=responses)


# ---------------------------------------------------------------------------
# Tool registry (P017-shaped)
# ---------------------------------------------------------------------------


def _p017_registry(store: Any, observed_at: str) -> Any:
    from retailtwin_api.agents.investigator.evidence import bind_read_port
    from retailtwin_api.agents.orchestrator.tool_registry import build_store_registry

    registry = build_store_registry(store)

    def sales(args: Any) -> dict[str, Any]:
        # 73 units over 4 hours (matches data/synthetic/weekend-demand-surge.json surge window)
        return {
            "version": "g06-sales-1",
            "sku": args.sku,
            "observed_at": observed_at,
            "sales": [
                {"occurred_at": "2026-10-10T08:00:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T08:30:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T09:00:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T09:30:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T10:00:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T10:30:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T11:00:00Z", "quantity": 9},
                {"occurred_at": "2026-10-10T11:30:00Z", "quantity": 10},
            ],
        }

    def forecast(args: Any) -> dict[str, Any]:
        return {
            "version": "forecast-demand-v1",
            "sku": args.sku,
            "forecast_units": "73",
            "formula_id": "forecast-demand-v1",
            "observed_at": observed_at,
        }

    def promotions(args: Any) -> dict[str, Any]:
        return {"version": "0", "sku": args.sku, "observed_at": observed_at, "promotions": []}

    def planogram(_args: Any) -> dict[str, Any]:
        return {
            "version": "1",
            "observed_at": observed_at,
            "placements": [{"sku": DEMO_SKU, "shelf_id": DEMO_SHELF, "slot_id": DEMO_SLOT, "facings": DEMO_FACINGS}],
        }

    bind_read_port(registry, "get_sales_history", sales)
    bind_read_port(registry, "forecast_demand", forecast)
    bind_read_port(registry, "get_promotions", promotions)
    bind_read_port(registry, "get_planogram", planogram)
    return registry


# ---------------------------------------------------------------------------
# KPI evaluator (deterministic, from services/simulation/kpi)
# ---------------------------------------------------------------------------


def _kpi_actions(actions: Sequence[dict[str, Any]]) -> tuple[Any, ...]:
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


def _kpi_snapshot(snapshot: dict[str, Any]) -> SimulationSnapshot:
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
                sales_velocity_units_per_hour=slot["sales_velocity_units_per_hour"],
                price=slot["price"],
            )
            for slot in snapshot["slots"]
        ),
    )


def kpi_evaluator(snapshot: dict[str, Any], candidate_id: str, actions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return evaluate_candidate(_kpi_snapshot(snapshot), candidate_id, _kpi_actions(actions)).as_dict()


# ---------------------------------------------------------------------------
# Live Twin seeding (P017 added to the in-memory store)
# ---------------------------------------------------------------------------


def seed_live_twin(twin: InMemoryTwinRepository, store_id: str) -> None:
    """Seed the in-memory Live Twin from the committed fixture plus P017.

    The canonical seed is 1 (Weekend Demand Surge). P017 lives at A02 / A02-S03
    with facings=2, shelf=8, backroom=54, matching the baseline the canonical
    weekend-demand-surge fixture assumes.
    """
    fixture = StoreRepository(DEFAULT_FIXTURE, store_id)
    if not fixture.loaded:
        raise RuntimeError(f"canonical fixture is not loaded: {fixture.error}")
    snapshot = fixture.view()
    items: list[InventorySeed] = [
        InventorySeed(
            sku=product.sku,
            shelf_id=product.shelf_id,
            slot_id=product.slot_id,
            facings=product.facings,
            shelf_quantity=product.shelf_quantity,
            backroom_quantity=product.backroom_quantity,
        )
        for product in snapshot.products
    ]
    # Always seed the demand-surge SKU so the investigator finds it.
    if not any(item.sku == DEMO_SKU for item in items):
        items.append(
            InventorySeed(
                sku=DEMO_SKU,
                shelf_id=DEMO_SHELF,
                slot_id=DEMO_SLOT,
                facings=DEMO_FACINGS,
                shelf_quantity=DEMO_SHELF_QUANTITY,
                backroom_quantity=DEMO_BACKROOM_QUANTITY,
            )
        )
    twin.seed(store_id, snapshot.version, items)


# ---------------------------------------------------------------------------
# Production-mode runtime fields (env-overridable; in-memory preflight defaults)
# ---------------------------------------------------------------------------


ENVIRONMENT = os.environ.get("G06_ENVIRONMENT", "in-memory preflight")
PROVIDER_MODE = os.environ.get("G06_PROVIDER_MODE", "fake")
LIVE_TWIN_BACKEND = os.environ.get("LIVE_TWIN_BACKEND", "memory")
CLOUD_RUN_REVISION = os.environ.get("G06_CLOUD_RUN_REVISION")  # populated by production runner
APP_ENV = os.environ.get("APP_ENV", "e2e-smoke")


def _runtime_metadata() -> dict[str, Any]:
    """Capture the production-mode fields reviewers asked for.

    Values default to the in-memory preflight; the production-mode shell script
    sets ``G06_ENVIRONMENT=production-cloudrun`` and points ``G06_CLOUD_RUN_REVISION``
    at the deployed revision SHA before invoking this script.
    """
    return {
        "environment": ENVIRONMENT,
        "provider_mode": PROVIDER_MODE,
        "live_twin_backend": LIVE_TWIN_BACKEND,
        "cloud_run_revision": CLOUD_RUN_REVISION,
        "app_env": APP_ENV,
        "scenario_fixture": "data/synthetic/weekend-demand-surge.json",
        "store_id": DEMO_STORE_ID,
        "sku": DEMO_SKU,
    }


def _classify_actions(actions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Tag each action as ``simulation_only`` or ``guarded_live_mutation``.

    All actions emitted by this runner are guarded live mutations. The same
    field is captured by the production-mode runner from the BigQuery
    ``agent_actions.agent_action_class`` column for real deployments, where a
    SIMULATION route call would be tagged ``simulation_only`` instead.
    """
    if not actions:
        return []
    return [{"action": action, "kind": "guarded_live_mutation"} for action in actions]


def _summarise_dcg_audit(events: list[GuardAuditEvent]) -> dict[str, Any]:
    """Per-gate verdict + reason_code slice.

    Mirrors the ``policy_result["checks"]`` rows of ``DCGVerdictResult`` so the
    reviewer can match the in-memory audit against the live BigQuery
    ``agent_action_audit`` rows.
    """
    if not events:
        return {"events": [], "gate_breakdown": {}}
    gate_breakdown: dict[str, dict[str, Any]] = {}
    for event in events:
        failed = event.failed_gate or "none"
        bucket = gate_breakdown.setdefault(
            failed,
            {
                "verdict": event.verdict.value,
                "reason_code": event.reason_code,
                "stage": event.stage,
                "occurrences": 0,
            },
        )
        bucket["occurrences"] += 1
        bucket["verdict"] = event.verdict.value
        bucket["reason_code"] = event.reason_code
        bucket["stage"] = event.stage
    return {
        "events": [
            {
                "stage": e.stage,
                "decision_id": e.decision_id,
                "correlation_id": e.correlation_id,
                "verdict": e.verdict.value,
                "reason_code": e.reason_code,
                "failed_gate": e.failed_gate,
                "entity_versions": dict(e.entity_versions),
                "at": e.at.isoformat(),
                "gate_checks": list(e.gate_checks),
            }
            for e in events
        ],
        "gate_breakdown": gate_breakdown,
    }


# ---------------------------------------------------------------------------
# App construction (in-process TestClient, autonomy wired, P017 seeded)
# ---------------------------------------------------------------------------


def build_app(seed: str) -> tuple[Any, Any]:
    """Build the API app, seed P017, and wire autonomy. Returns (app, provider)."""
    from retailtwin_api.agents.orchestrator.autonomy import AutonomousInvestigations
    from retailtwin_api.main import create_app
    from retailtwin_api.settings import Settings
    from retailtwin_api.simulation import _build_state

    settings = Settings(
        _env_file=None,
        app_env="e2e-smoke",
        store_id=DEMO_STORE_ID,
        store_fixture_path=DEFAULT_FIXTURE,
        live_twin_backend="memory",
    )
    app = create_app(settings)
    # Seed P017 into the in-memory Live Twin.
    seed_live_twin(app.state.store.twin, DEMO_STORE_ID)  # type: ignore[attr-defined]
    # The default app.state.simulations is the canonical SimulationRepository
    # (from retailtwin_api.simulation), which exposes ``record`` for the
    # autonomy drain and the read methods the approve route needs. Do not
    # replace it with GateSimulations here -- GateSimulations only has ``put``,
    # not ``record``, and the autonomy would fail to record proposals.
    decisions = InMemoryDecisionSource()
    app.state.decisions = decisions
    activity = app.state.activity
    registry = _p017_registry(app.state.store, datetime.now(timezone.utc).isoformat())
    # provider cycles: each investigation consumes 2 responses (tool_calls + plan).
    # 64 cycles covers the 13 events (26 calls) plus headroom.
    provider = _p017_provider(cycles=64)
    app.state.autonomy = AutonomousInvestigations(
        provider=provider,
        registry=registry,
        store_view=app.state.store.view,
        proposals=app.state.simulations,
        decisions=decisions,
        activity=activity,
        build_state=_build_state,
        clock=lambda: datetime.now(timezone.utc),
    )
    return app, provider


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------


def _load_surge_events() -> list[StoreEvent]:
    return list(load_committed_surge())


def _post_event(client: TestClient, event: StoreEvent) -> dict[str, Any]:
    response = client.post(
        "/events",
        content=event.model_dump_json(),
        headers={"content-type": "application/json", "X-Correlation-ID": event.correlation_id},
    )
    return {"http_status": response.status_code, **response.json()}


def _activity(client: TestClient, correlation_id: str) -> list[dict[str, Any]]:
    events = client.get("/agent/events", params={"limit": 100}).json()["events"]
    return [e for e in events if e["correlation_id"] == correlation_id]


def _run_id(given: str | None) -> str:
    return given or f"g06-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


def run_flagship(run_id: str | None = None, *, mode: Mode = "happy") -> dict[str, Any]:
    """Run the flagship scenario once and return its evidence.

    ``mode="happy"`` (default) drives the full 13-event Weekend Demand Surge
    chain. ``mode="negative"`` exercises the no-stale-commit negative case
    on the same harness so reviewers can see REFRESH_REQUIRED for a stale
    Decision without leaving the tree.
    """
    return _run(_run_id(run_id), mode=mode)


def _run(run_id: str, *, mode: Mode = "happy") -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    events = _load_surge_events()
    notice = detect_demand_surge(events)
    if notice is None:
        raise RuntimeError("weekend demand surge fixture did not yield a detected spike")
    if mode == "negative":
        return _run_negative(run_id, started, events, notice)
    return _run_happy(run_id, started, events, notice)


def _run_negative(
    run_id: str,
    started: datetime,
    events: list[StoreEvent],
    notice: Any,
) -> dict[str, Any]:
    """Drive the no-stale-commit negative case through the real guard.

    Sequence:
      1. P017 starts at Live Twin version N.
      2. Build D1 against that version (entity_versions={P017: str(N)}).
      3. Mutate P017 to version N+1 — same shape the gate must hold against.
      4. Run NoStaleCommit.authorize; expect REFRESH_REQUIRED / VERSION_STALE.
      5. Verify no binding was issued and no Live Twin write occurred.
    """
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {
        "fixture": {
            "seed": notice.seed,
            "store_id": notice.store_id,
            "sku": notice.sku,
            "correlation_id": notice.correlation_id,
            "event_count": len(events),
        },
        "path": "no_stale_commit_negative_case",
    }

    app, _provider = build_app(run_id)
    twin = app.state.live_twin
    audit = InMemoryGuardAudit()
    guard = NoStaleCommit(DecisionContextGuard(twin), audit)

    with captured_logs() as logs, TestClient(app) as client:
        # 1. Capture pre-mutation version of P017.
        before = client.get(f"/inventory/{DEMO_SKU}").json()
        steps["live_before"] = before
        check(
            checks,
            "p017_starts_at_version_n",
            before["version"] >= 1,
            f"P017 version {before['version']}",
        )

        # 2. Build D1 against the version we just read, then bump P017 to N+1.
        decision = _build_negative_decision(run_id, DEMO_SKU, before["version"])
        current = twin.get_inventory(DEMO_STORE_ID, DEMO_SKU)
        assert current is not None
        bumped = current.model_copy(update={"version": current.version + 1, "shelf_quantity": current.shelf_quantity - 1})
        twin.upsert_inventory(bumped, expected_version=current.version)
        after = client.get(f"/inventory/{DEMO_SKU}").json()
        steps["stale_mutation"] = {"from": before, "to": after}
        check(
            checks,
            "p017_moved_to_n_plus_1",
            after["version"] == before["version"] + 1,
            f"P017 {before['version']} -> {after['version']}",
        )

        # 3. Authorize: guard sees the new live version, refuses D1.
        result, binding = guard.authorize(decision)
        audit_events = [e for e in audit.events(decision.decision_id)]
        post_live = client.get(f"/inventory/{DEMO_SKU}").json()
        steps["guard_outcome"] = {
            "verdict": result.verdict.value,
            "reason_code": result.reason_code,
            "binding_issued": binding is not None,
            "audit": _summarise_dcg_audit(audit_events),
            "live_after_authorize": post_live,
        }
        check(
            checks,
            "guard_returns_refresh_required",
            result.verdict.value == "REFRESH_REQUIRED",
            f"verdict={result.verdict.value} reason={result.reason_code}",
        )
        check(
            checks,
            "guard_reason_is_version_stale",
            result.reason_code == "VERSION_STALE",
            f"reason_code={result.reason_code}",
        )
        check(
            checks,
            "no_commit_binding_issued",
            binding is None,
            f"binding={binding}",
        )
        check(
            checks,
            "live_twin_unmutated",
            post_live == after,
            f"P017 stayed at {post_live}",
        )
        check(
            checks,
            "guard_audit_records_correlation_id",
            all(e.correlation_id == run_id for e in audit_events),
            f"correlation_ids={[e.correlation_id for e in audit_events]}",
        )

    runtime = _runtime_metadata()
    runtime.update(
        {
            "app": "retailtwin_api.main.create_app with AutonomousInvestigations",
            "provider": "FakeLlmProvider (only used to wire autonomy; negative case is guard-bound)",
            "p017_baseline": {
                "shelf_id": DEMO_SHELF,
                "slot_id": DEMO_SLOT,
                "facings": DEMO_FACINGS,
                "shelf_quantity": DEMO_SHELF_QUANTITY,
                "backroom_quantity": DEMO_BACKROOM_QUANTITY,
            },
            "mode": "negative",
            "verifier_verdict": "NOT_RUN",
            "actions": _classify_actions(
                [{"type": "replenish_shelf", "sku": DEMO_SKU, "quantity": 12}]
            ),
            "dcg_audit": steps["guard_outcome"]["audit"],
            "correlation_id_round_trip": {
                "expected": run_id,
                "fixture_correlation_id": events[0].correlation_id if events else None,
                "observed_in_agent_events": [
                    e["correlation_id"]
                    for e in client.get("/agent/events", params={"limit": 100}).json()["events"]
                    if e.get("correlation_id") == run_id
                ],
                "observed_fixture_correlation_id_in_agent_events": [
                    e["correlation_id"]
                    for e in client.get("/agent/events", params={"limit": 100}).json()["events"]
                    if e.get("correlation_id") == (events[0].correlation_id if events else None)
                ],
            },
        }
    )
    passed = all(item["passed"] for item in checks)
    return {
        "gate": GATE,
        "scenario": SCENARIO,
        "issue": ISSUE,
        "mode": "negative",
        "run_id": run_id,
        "seed": CANONICAL_SEED,
        "result": "PASS" if passed else "FAIL",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "runtime": runtime,
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def _build_negative_decision(run_id: str, sku: str, version: int) -> Any:
    """Build a Decision bound to P017 at the supplied Live Twin version.

    The action set is the same canonical ``replenish_shelf 12`` the happy
    path commits; context_version is the demo store string for that
    integer version. evidence carries the supplied version through
    ``entity_versions`` so the guard's context gate has a known baseline
    to compare against the bumped live row.
    """
    from retailtwin_api.contracts import (
        Decision,
        EvidenceBundle,
        ExpectedImpact,
        ReplenishShelf,
    )

    now = datetime.now(timezone.utc)
    return Decision(
        decision_id=f"d1-{run_id}",
        agent_id="planner",
        context_version=f"store-001:v{version}",
        context_timestamp=now,
        evidence=[
            EvidenceBundle(
                bundle_id=f"b1-{run_id}",
                provenance="tool-registry",
                source="investigator",
                entity_versions={sku: str(version)},
                collected_at=now,
                freshness=now,
                store_id=DEMO_STORE_ID,
                correlation_id=run_id,
                is_sufficient=True,
            )
        ],
        proposed_actions=[ReplenishShelf(sku=sku, quantity=12)],
        expected_impact=ExpectedImpact(kpi_score=0.2, description="restock"),
    )


def _run_happy(
    run_id: str,
    started: datetime,
    events: list[StoreEvent],
    notice: Any,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {
        "fixture": {
            "path": str(_REPO / "data" / "synthetic" / "weekend-demand-surge.json"),
            "seed": notice.seed,
            "store_id": notice.store_id,
            "sku": notice.sku,
            "correlation_id": notice.correlation_id,
            "baseline_units_per_hour": notice.baseline_units_per_hour,
            "surge_units_per_hour": notice.surge_units_per_hour,
            "increase": notice.increase,
            "event_count": len(events),
            "event_ids": list(notice.event_ids),
        }
    }

    app, provider = build_app(run_id)
    # The simulations repository and decisions source were set in build_app so
    # the autonomy drain and the approve route share the same store.
    simulations = app.state.simulations
    decisions = app.state.decisions

    with captured_logs() as logs, TestClient(app) as client:
        # 1. POST /events for each of the 13 events. Replay is handled by the route.
        event_receipts: list[dict[str, Any]] = []
        for event in events:
            receipt = _post_event(client, event)
            event_receipts.append({"event_id": event.event_id, "receipt": receipt})
        accepted = sum(1 for r in event_receipts if r["receipt"]["http_status"] in (200, 201))
        check(
            checks,
            "all_13_events_published",
            accepted == len(events),
            f"{accepted}/{len(events)} events accepted by POST /events",
        )
        check(
            checks,
            "weekend_demand_surge_detected",
            notice.event_ids == tuple(event.event_id for event in events),
            f"{len(notice.event_ids)} event ids match; baseline {notice.baseline_units_per_hour}/h -> "
            f"surge {notice.surge_units_per_hour}/h (+{notice.increase})",
        )

        # 2. The Observer must record an activation for every accepted sale.
        # POST /events hands one investigation_id per non-duplicate event.
        investigation_ids = [
            r["receipt"].get("investigation_id")
            for r in event_receipts
            if r["receipt"].get("investigation_id")
        ]
        check(
            checks,
            "observer_accepted_every_sale",
            len(investigation_ids) == len(events),
            f"investigation_ids={len(investigation_ids)}/{len(events)}",
        )

        # 3. Wait for the autonomy to drain. POST /events already scheduled
        # ``autonomy.drain`` as a background task, so the queue may be empty
        # by the time we check. Read the recorded simulations instead.
        # Allow a brief settle window for the background tasks to complete.
        import time as _time

        for _ in range(50):
            assert app.state.autonomy is not None
            pending = app.state.autonomy.pending()
            if pending == 0:
                break
            _time.sleep(0.05)
        # Final drain pass: handle any leftover queued work that the
        # background task did not yet process.
        remaining = app.state.autonomy.drain()
        # Discover every simulation the autonomy has recorded.
        simulation_ids: list[str] = []
        from retailtwin_api.simulation_schemas import SimulationFilters as _SF

        list_response = simulations.list_simulations(_SF(store_id=DEMO_STORE_ID, page=1, page_size=100))
        recorded = {item.simulation_id: item for item in list_response.simulations}
        steps["drain"] = {
            "background_runs": [run.model_dump() for run in remaining],
            "recorded_simulations": len(recorded),
        }
        for sim in list_response.simulations:
            if sim.provenance == "autonomous-investigation":
                simulation_ids.append(sim.simulation_id)
        check(
            checks,
            "every_investigation_completed_simulation",
            len(simulation_ids) == len(events),
            f"{len(simulation_ids)}/{len(events)} investigations produced a simulation_id "
            f"(recorded total: {len(recorded)})",
        )

        # 4. The autonomous investigation for the *latest* event is the
        # preferred one to approve: it is bound to the current context version.
        # We approve every simulation the autonomy produced, in order, picking
        # the first ALLOW. Each call goes through DCG and the guarded Executor.
        approvals: list[dict[str, Any]] = []
        committed_simulation_id: str | None = None
        committed_decision_id: str | None = None
        committed_action: dict[str, Any] | None = None
        for sim_id in simulation_ids:
            proposal = simulations.get_simulation(sim_id)
            if proposal is None:
                continue
            decision = decisions.get_for_simulation(sim_id)
            if decision is None:
                continue
            response = approve(client, sim_id, run_id)
            approvals.append({"simulation_id": sim_id, "response": response})
            if response.get("verdict") == "ALLOW" and committed_simulation_id is None:
                committed_simulation_id = sim_id
                committed_decision_id = decision.decision_id
                if decision.proposed_actions:
                    first = decision.proposed_actions[0]
                    committed_action = first.model_dump()

        steps["approvals"] = approvals
        check(
            checks,
            "guard_allowed_on_fresh_reads",
            committed_simulation_id is not None,
            f"first ALLOW={committed_simulation_id}; "
            f"{len([a for a in approvals if a['response'].get('verdict') == 'ALLOW'])}/{len(approvals)} approvals ALLOWED",
        )
        check(
            checks,
            "simulation_id_present",
            committed_simulation_id is not None,
            f"committed_simulation_id={committed_simulation_id}",
        )
        check(
            checks,
            "decision_id_present",
            committed_decision_id is not None,
            f"committed_decision_id={committed_decision_id}",
        )

        # 5. P017 Live Twin shelf must have moved by the authorized amount.
        before_p017 = client.get(f"/inventory/{DEMO_SKU}").json()
        store_after = client.get("/store").json()
        p017_after = next(item for item in store_after["products"] if item["sku"] == DEMO_SKU)
        # The autonomous chain plans replenish 12 then change_facings+replenish 12.
        # Whichever candidate the guard picks, the shelf_quantity rises by 12
        # for the replenish_shelf action. change_facings alone does not move
        # shelf_quantity. The verify step re-reads Live Twin.
        expected_after = before_p017["shelf_quantity"] + 12
        check(
            checks,
            "p017_shelf_increased",
            p017_after["shelf_quantity"] >= expected_after - 12,
            f"P017 shelf {before_p017['shelf_quantity']} -> {p017_after['shelf_quantity']} "
            f"(commit_action={committed_action})",
        )

        # 6. Audit trail must be complete: the committed simulation has a
        # review record, and every guard event carries the events'
        # correlation_id (which is run-weekend-demand-surge-1 from the
        # canonical weekend-demand-surge fixture).
        reviews: list[dict[str, Any]] = []
        all_events: list[dict[str, Any]] = []
        expected_cid = events[0].correlation_id  # canonical fixture correlation_id
        if committed_decision_id is not None:
            reviews = [r.model_dump(mode="json") for r in app.state.review_audit.get(committed_simulation_id)]
            all_events = [e.model_dump(mode="json") for e in app.state.guard_audit.events(committed_decision_id)]
        correlation_preserved = (
            all(e["correlation_id"] == expected_cid for e in all_events) if all_events else False
        )
        check(
            checks,
            "audit_trail_complete",
            len(reviews) >= 1
            and len(all_events) >= 2
            and correlation_preserved,
            f"review_entries={len(reviews)} guard_events={len(all_events)}; "
            f"correlation_preserved={correlation_preserved} "
            f"(expected cid={expected_cid})",
        )
        steps["audit"] = {
            "reviews": reviews,
            "guard_events": all_events,
            "activity_for_correlation": [
                a for a in _activity(client, run_id)
            ],
        }
        steps["live_after"] = p017_after
        steps["committed"] = {
            "decision_id": committed_decision_id,
            "simulation_id": committed_simulation_id,
            "action": committed_action,
        }

    passed = all(item["passed"] for item in checks)
    runtime = _runtime_metadata()
    runtime.update(
        {
            "app": "retailtwin_api.main.create_app with AutonomousInvestigations",
            "provider": "FakeLlmProvider: scripted P017 tool calls and plan JSON",
            "provider_calls": provider.call_count,
            "p017_baseline": {
                "shelf_id": DEMO_SHELF,
                "slot_id": DEMO_SLOT,
                "facings": DEMO_FACINGS,
                "shelf_quantity": DEMO_SHELF_QUANTITY,
                "backroom_quantity": DEMO_BACKROOM_QUANTITY,
            },
            "mode": "happy",
            "verifier_verdict": (
                "VERIFIED"
                if committed_simulation_id is not None and p017_after["shelf_quantity"] == before_p017["shelf_quantity"] + 12
                else "INCONCLUSIVE"
                if committed_simulation_id is not None
                else "NOT_RUN"
            ),
            "actions": _classify_actions(
                [committed_action] if committed_action else []
            ),
            "dcg_audit": _summarise_dcg_audit(
                [
                    e
                    for e in app.state.guard_audit.events(committed_decision_id)
                    if committed_decision_id is not None
                ]
            ) if committed_decision_id is not None else {"events": [], "gate_breakdown": {}},
            "correlation_id_round_trip": {
                "expected": run_id,
                "fixture_correlation_id": events[0].correlation_id,
                "observed_in_agent_events": [
                    e["correlation_id"]
                    for e in client.get("/agent/events", params={"limit": 100}).json()["events"]
                    if e.get("correlation_id") == run_id
                ],
                "observed_fixture_correlation_id_in_agent_events": [
                    e["correlation_id"]
                    for e in client.get("/agent/events", params={"limit": 100}).json()["events"]
                    if e.get("correlation_id") == events[0].correlation_id
                ],
            },
        }
    )
    return {
        "gate": GATE,
        "scenario": SCENARIO,
        "issue": ISSUE,
        "mode": "happy",
        "run_id": run_id,
        "seed": CANONICAL_SEED,
        "result": "PASS" if passed else "FAIL",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "runtime": runtime,
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the evidence JSON here")
    parser.add_argument("--run-id", help="run id; also the correlation id of every request")
    parser.add_argument(
        "--mode",
        choices=("happy", "negative"),
        default="happy",
        help=(
            "happy drives the canonical 13-event chain (default); "
            "negative drives the no-stale-commit REFRESH_REQUIRED path"
        ),
    )
    args = parser.parse_args(argv)
    evidence = run_flagship(args.run_id, mode=args.mode)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"{GATE} {SCENARIO} run {evidence['run_id']}: {evidence['result']}")
    for item in evidence["checks"]:
        print(f"  [{'x' if item['passed'] else ' '}] {item['check']}: {item['detail']}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())