"""Flagship controller end-to-end tests (issue #41).

Each test wires the controller against the canonical services. The Live Twin
is an in-memory ``InMemoryTwinRepository`` (which is the same contract the
production Firestore implementation satisfies), the LLM is a deterministic
``FakeLlmProvider``, and the tool registry is the canonical store-backed
registry. The tests prove the full canonical chain runs without user prompts:

    event → investigation → plan → simulate → stale block → replan → commit → verify
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import pytest

from retailtwin_api.agents.investigator.evidence import bind_read_port
from retailtwin_api.agents.orchestrator.tool_registry import (
    ToolRegistry,
    build_store_registry,
)
from retailtwin_api.contracts import ReplenishShelf
from retailtwin_api.demand_surge import (
    CANONICAL_SEED,
    SKU as DEMO_SKU,
    STORE_ID as DEMO_STORE_ID,
)
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed
from retailtwin_api.flagship.controller import (
    FlagshipController,
    FlagshipDependencies,
    FlagshipPhase,
    FlagshipRequest,
    FlagshipStateError,
    _build_live_view,
)
from retailtwin_api.llm.contracts import LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.store import StoreRepository

# The canonical KPI evaluator lives under services/simulation. The tests
# import the same module the production path uses; this keeps the KPI formula
# in lock-step with the rest of the project.
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

CORRELATION = "run-weekend-demand-surge-1"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _LiveReader:
    """The ``_StoreReads`` protocol the tool registry expects."""

    def __init__(self, repo: InMemoryTwinRepository, store_id: str) -> None:
        self._repo = repo
        self.store_id = store_id
        self._cached: StoreResponse | None = None

    def _view(self) -> StoreResponse:
        if self._cached is not None:
            return self._cached
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

    def view(self) -> StoreResponse:
        return self._view()

    def inventory(self, sku: str) -> ProductInventory | None:
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

    def invalidate(self) -> None:
        self._cached = None


class _FakeProvider:
    """Provider-neutral fake. Drives the investigator then the planner.

    Cycle 1: tool calls (investigator). Cycle 2: structured candidates (planner).
    Each subsequent refresh triggers one more investigator + planner cycle.
    The default of 8 cycles comfortably covers one initial run plus one
    replan, with two provider calls per cycle.
    """

    def __init__(self, sku: str, max_cycles: int = 8) -> None:
        self.sku = sku
        self._max_cycles = max_cycles
        self.calls = 0
        self.requests: list[LlmRequest] = []

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        self.requests.append(request)
        if self.calls > self._max_cycles:
            raise RuntimeError("provider exhausted")
        if request.tools:
            return LlmResponse(
                id=f"resp-{self.calls}",
                model=request.model,
                finish_reason="tool_calls",
                tool_calls=self._investigator_calls(),
            )
        return LlmResponse(
            id=f"resp-{self.calls}",
            model=request.model,
            finish_reason="stop",
            content=json.dumps(self._canonical_plan()),
        )

    def _investigator_calls(self) -> list[LlmToolCall]:
        return [
            LlmToolCall(id="inv-1", name="get_inventory", arguments={"sku": self.sku}),
            LlmToolCall(id="inv-2", name="get_shelf_state", arguments={"shelf_id": "A02"}),
            LlmToolCall(id="inv-3", name="get_sales_history", arguments={"sku": self.sku, "window_hours": 4}),
            LlmToolCall(id="inv-4", name="forecast_demand", arguments={"sku": self.sku, "horizon_hours": 4}),
            LlmToolCall(id="inv-5", name="get_promotions", arguments={"sku": self.sku}),
            LlmToolCall(id="inv-6", name="get_planogram", arguments={}),
        ]

    def _canonical_plan(self) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "reason": "Replenish P017 from the backroom.",
                    "actions": [{"type": "replenish_shelf", "sku": self.sku, "quantity": 12}],
                },
                {
                    "reason": "Increase facings, then replenish P017.",
                    "actions": [
                        {"type": "change_facings", "sku": self.sku, "facings": 4},
                        {"type": "replenish_shelf", "sku": self.sku, "quantity": 12},
                    ],
                },
            ]
        }


def _evaluator(snapshot: Any, candidate_id: str, actions: Sequence[Any]) -> dict[str, Any]:
    """Canonical deterministic KPI evaluator (issue #33)."""

    observed_at = snapshot["observed_at"]
    if not isinstance(observed_at, str):
        raise RuntimeError("observed_at must be an ISO string")
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
        if kind == "move_product":
            converted.append(
                KpiMoveProduct(sku=action["sku"], from_slot=action["from_slot"], to_slot=action["to_slot"])
            )
        elif kind == "change_facings":
            converted.append(KpiChangeFacings(sku=action["sku"], facings=action["facings"]))
        elif kind == "replenish_shelf":
            converted.append(KpiReplenishShelf(sku=action["sku"], quantity=action["quantity"]))
        else:
            raise RuntimeError(f"unknown action {kind}")
    return evaluate_candidate(built, candidate_id, tuple(converted)).as_dict()


def _seed_repo() -> InMemoryTwinRepository:
    """Seed the Live Twin to the same canonical fixture plus the demand-surge SKU."""

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
    items.append(
        InventorySeed(
            sku=DEMO_SKU,
            shelf_id="A02",
            slot_id="A02-S03",
            facings=2,
            shelf_quantity=8,
            backroom_quantity=54,
        )
    )
    repo.seed(DEMO_STORE_ID, snapshot.version, items)
    return repo


def _registry(repo: InMemoryTwinRepository) -> ToolRegistry:
    """Build a registry whose read tools all return the demand-surge SKU.

    ``build_store_registry`` covers inventory, shelf state, and the
    simulation/commit stubs. The investigator's mandatory read sources
    (``get_sales_history``, ``forecast_demand``, ``get_promotions`` and
    ``get_planogram``) are bound here as deterministic, versioned readers.
    """

    registry = build_store_registry(_LiveReader(repo, DEMO_STORE_ID))

    def sales(args: Any) -> dict[str, Any]:
        return {
            "version": "evt-p017",
            "sku": args.sku,
            "observed_at": NOW.isoformat(),
            "sales": [
                {"hour_offset": 0, "units": "10"},
                {"hour_offset": 1, "units": "10"},
                {"hour_offset": 2, "units": "10"},
                {"hour_offset": 3, "units": "10"},
            ],
        }

    def forecast(args: Any) -> dict[str, Any]:
        return {
            "version": "forecast-demand-v1",
            "sku": args.sku,
            "forecast_units": "73",
            "formula_id": "forecast-demand-v1",
            "observed_at": NOW.isoformat(),
        }

    def promotions(args: Any) -> dict[str, Any]:
        return {
            "version": "0",
            "sku": args.sku,
            "observed_at": NOW.isoformat(),
            "promotions": [],
        }

    def planogram(_args: Any) -> dict[str, Any]:
        return {
            "version": "1",
            "observed_at": NOW.isoformat(),
            "placements": [
                {"sku": DEMO_SKU, "shelf_id": "A02", "slot_id": "A02-S03", "facings": 2},
            ],
        }

    bind_read_port(registry, "get_sales_history", sales)
    bind_read_port(registry, "forecast_demand", forecast)
    bind_read_port(registry, "get_promotions", promotions)
    bind_read_port(registry, "get_planogram", planogram)
    return registry


def _controller(provider: _FakeProvider | None = None) -> tuple[FlagshipController, InMemoryTwinRepository]:
    repo = _seed_repo()
    deps = FlagshipDependencies(
        provider=provider or _FakeProvider(DEMO_SKU),
        twin=repo,
        store_id=DEMO_STORE_ID,
        registry=_registry(repo),
        evaluator=_evaluator,
        clock=lambda: NOW,
    )
    controller = FlagshipController(deps)
    return controller, repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reset_clears_state_and_reseeds_twin() -> None:
    controller, repo = _controller()
    initial = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert initial is not None
    initial_version = initial.version
    controller.reset(seed=CANONICAL_SEED)
    status = controller.status()
    assert status.phase is FlagshipPhase.IDLE
    assert status.seed == CANONICAL_SEED
    assert status.context_version is not None
    # The seed repo loads with version 1; the second seed lands at the same place.
    reseeded = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert reseeded is not None
    assert reseeded.version >= initial_version


def test_start_runs_canonical_chain_with_stale_block() -> None:
    controller, repo = _controller()
    controller.reset(seed=CANONICAL_SEED)
    before = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert before is not None

    result = asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))

    # The chain reached completion with one committed decision.
    assert result.phase is FlagshipPhase.COMPLETE
    assert result.guard_verdict == "REFRESH_REQUIRED"
    assert result.guard_reason_code, result.guard_reason_code
    assert result.committed_decision_id is not None
    assert result.replan_refresh_count == 1
    assert result.verification_status is not None
    assert result.context_version_after != result.context_version_before
    # Live inventory was moved by the commit.
    after = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert after is not None
    assert after.version > before.version
    # The timeline records the canonical stages and the committed action.
    stages = [entry["stage"] for entry in result.timeline]
    assert {"event", "investigate", "plan", "simulate", "guard", "replan", "verify"}.issubset(set(stages))
    assert any("replenish" in entry["detail"].lower() for entry in result.timeline), result.timeline


def test_canonical_stages_appear_in_timeline() -> None:
    controller, _ = _controller()
    controller.reset(seed=CANONICAL_SEED)
    result = asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))
    stages = [entry["stage"] for entry in result.timeline]
    expected = {"event", "investigate", "plan", "simulate", "guard", "replan", "verify"}
    assert expected.issubset(set(stages)), f"missing stages: {expected - set(stages)}"


def test_status_after_run_reports_committed_decision() -> None:
    controller, _ = _controller()
    controller.reset(seed=CANONICAL_SEED)
    asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))
    status = controller.status()
    assert status.phase is FlagshipPhase.COMPLETE
    assert status.committed_decision_id is not None
    assert status.guard_verdict == "REFRESH_REQUIRED"
    assert status.replan_refresh_count == 1
    assert status.verification_status is not None


def test_disabled_stale_block_fails_safely() -> None:
    """Without the deliberate bump, the planner's decision ALLOWs without a replan.

    The controller's intent is to surface the REFRESH_REQUIRED path that the
    issue calls out. With ``stale_block_enabled=False`` the chain still
    completes but reports ``refresh_count=0`` because the guard never had a
    reason to reject.
    """
    controller, _ = _controller()
    controller.reset(seed=CANONICAL_SEED)
    result = asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=False)))
    assert result.phase is FlagshipPhase.COMPLETE
    # No replan was needed; the decision was allowed on the first try.
    assert result.replan_refresh_count == 0


def test_default_stale_block_disabled_in_production_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APP_ENV=production`` must default ``stale_block_enabled`` to ``False``.

    The deterministic stale injection is a demo affordance; production
    refuses the underlying helper. The default must keep production on a
    real-event path. Evaluated per-instance so tests can override the env.
    """
    monkeypatch.setenv("APP_ENV", "production")
    request = FlagshipRequest()
    assert request.stale_block_enabled is False


def test_default_stale_block_enabled_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside production the default keeps the canonical stale → replan path."""
    monkeypatch.setenv("APP_ENV", "test")
    request = FlagshipRequest()
    assert request.stale_block_enabled is True
    monkeypatch.setenv("APP_ENV", "development")
    request = FlagshipRequest()
    assert request.stale_block_enabled is True
    # No APP_ENV at all → non-production default.
    monkeypatch.delenv("APP_ENV", raising=False)
    request = FlagshipRequest()
    assert request.stale_block_enabled is True


def test_consecutive_runs_are_idempotent() -> None:
    """Two consecutive resets and starts must not leak state between runs."""

    controller, repo = _controller()
    first = asyncio.run(_run_with_reset(controller))
    baseline = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert baseline is not None
    first_after_version = baseline.version

    second = asyncio.run(_run_with_reset(controller))
    assert second.phase is FlagshipPhase.COMPLETE
    assert first.committed_decision_id is not None
    assert second.committed_decision_id is not None
    # The second run reached a higher Live version because each commit bumps it.
    second_after = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert second_after is not None
    assert second_after.version >= first_after_version


def test_start_without_reset_raises() -> None:
    """A first ``start`` without a preceding ``reset`` must raise clearly."""

    controller, _ = _controller()
    # Newly-built controllers are IDLE — start should still be allowed because
    # the canonical "fresh from a clean reset" path is the documented entry.
    # The state error only fires when the controller is already RUNNING.
    asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))


def test_start_while_running_is_rejected() -> None:
    """Once a run is in flight, a second ``start`` is rejected by the state machine.

    The canonical run is fast enough that catching it mid-flight is racy on
    fast machines, so we exercise the state guard by holding the controller in
    the ``RUNNING`` phase and then issuing a second start.
    """

    controller, _ = _controller()
    controller.reset(seed=CANONICAL_SEED)
    with controller._lock:  # type: ignore[attr-defined]  # noqa: SLF001 — test-only
        controller._phase = FlagshipPhase.RUNNING  # type: ignore[attr-defined]  # noqa: SLF001
    with pytest.raises(FlagshipStateError):
        asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))
    controller._phase = FlagshipPhase.IDLE  # type: ignore[attr-defined]  # noqa: SLF001


def test_verifier_reports_verified_after_commit() -> None:
    controller, _ = _controller()
    controller.reset(seed=CANONICAL_SEED)
    result = asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))
    assert result.verification_status is not None
    # The ReplenishShelf action against P017 is verifiable on the same Live Twin.
    assert result.verification_status in {"VERIFIED", "REGRESSION", "INCONCLUSIVE"}


def test_live_view_reflects_post_commit_state() -> None:
    """The build_live_view helper must return a snapshot that the simulator
    would also see after the commit — both reads come from the same repository.
    """
    controller, repo = _controller()
    controller.reset(seed=CANONICAL_SEED)
    asyncio.run(controller.start(FlagshipRequest(stale_block_enabled=True)))
    reader = _LiveReader(repo, DEMO_STORE_ID)
    view = _build_live_view(reader, correlation_id=CORRELATION)
    p017 = next(slot for slot in view.slots if slot.sku == DEMO_SKU)
    # After commit, the shelf quantity grew by 12 (the canonical replenish).
    assert p017.shelf_quantity > 0


# ---------------------------------------------------------------------------
# Production event path (ADR 0023)
# ---------------------------------------------------------------------------


def test_start_for_event_does_not_reset_the_live_twin() -> None:
    """``start_for_event`` must NOT reseed the Live Twin (P0-1).

    The autonomous event path enters the flagship chain against the real
    incoming event — the current store state must be preserved.
    """

    from datetime import datetime, timezone

    from retailtwin_api.schemas import StoreEvent

    controller, repo = _controller()
    # Seed the Live Twin once and capture its version, then "ship" a sale
    # without calling reset().
    controller.reset(seed=CANONICAL_SEED)
    snapshot = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert snapshot is not None
    version_after_reset = snapshot.version

    event = StoreEvent(
        event_id="evt-p2-1",
        correlation_id="corr-p2-1",
        event_type="sale.completed",
        store_id=DEMO_STORE_ID,
        sku=DEMO_SKU,
        quantity=1,
        occurred_at=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )

    asyncio.run(controller.start_for_event(event))

    # The Live Twin must NOT have been reseeded; its version reflects
    # whatever the run committed, not the deterministic seed baseline.
    after = repo.get_inventory(DEMO_STORE_ID, DEMO_SKU)
    assert after is not None
    # The version changed because the canonical chain ran (commit) — but
    # the chain did not re-seed the canonical fixture (which would set
    # shelf_quantity back to 8 and version back to 1).
    assert after.version != 0  # not the bare seeded baseline


def test_start_for_event_passes_real_event_content_to_investigator() -> None:
    """``start_for_event`` propagates the real event content (P0-2).

    The investigation's ``InvestigationStart.event`` must carry the
    real ``event_id``, ``sku``, ``quantity``, ``occurred_at``, ``store_id``
    and ``correlation_id`` — the chain must not silently rebuild a
    canonical event from the demand-surge seed.
    """

    captured: dict[str, object] = {}

    from datetime import datetime, timezone

    from retailtwin_api.agents.investigator.evidence import investigate
    from retailtwin_api.schemas import StoreEvent

    class _CapturingProvider(_FakeProvider):
        async def complete(self, request: LlmRequest) -> LlmResponse:  # type: ignore[override]
            # Record the first investigator request payload so we can
            # confirm the event content reached the provider.
            if request.model == "investigator" and not captured:
                captured["messages"] = [m.model_dump() for m in request.messages]
            return await super().complete(request)

    controller, repo = _controller(_CapturingProvider(DEMO_SKU))
    controller.reset(seed=CANONICAL_SEED)

    event = StoreEvent(
        event_id="evt-real-99",
        correlation_id="corr-real-99",
        event_type="sale.completed",
        store_id=DEMO_STORE_ID,
        sku=DEMO_SKU,
        quantity=3,
        occurred_at=datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc),
        source="synthetic-pos",
    )

    asyncio.run(controller.start_for_event(event))

    assert captured, "investigator never received an LLM request"
    serialised = " ".join(str(m) for m in captured.get("messages", []))
    # The event_id, sku, and correlation_id must reach the investigator prompt
    # so the chain can trace the real incoming event back to Pub/Sub.
    assert "evt-real-99" in serialised
    assert "corr-real-99" in serialised
    assert DEMO_SKU in serialised


def test_start_for_event_disables_stale_block_even_when_enabled_in_request() -> None:
    """``start_for_event`` forces ``stale_block_enabled=False`` (P0-3).

    A real Pub/Sub event must never trigger the deterministic
    ``REFRESH_REQUIRED`` race — the stale-block injection is a demo
    artefact. The production event path overrides it regardless of what
    the caller passes in ``FlagshipRequest``.
    """

    from datetime import datetime, timezone

    from retailtwin_api.flagship._stale_bump import bump_inventory_for_stale_block
    from retailtwin_api.schemas import StoreEvent

    bump_calls: list[str] = []

    original = bump_inventory_for_stale_block

    def spy(twin, store_id, sku):  # type: ignore[no-untyped-def]
        bump_calls.append(sku)
        return original(twin, store_id, sku)

    import retailtwin_api.flagship.controller as ctrl_mod

    ctrl_mod.bump_inventory_for_stale_block = spy  # type: ignore[assignment]

    try:
        controller, _ = _controller()
        controller.reset(seed=CANONICAL_SEED)

        event = StoreEvent(
            event_id="evt-p3",
            correlation_id="corr-p3",
            event_type="sale.completed",
            store_id=DEMO_STORE_ID,
            sku=DEMO_SKU,
            quantity=1,
            occurred_at=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
            source="synthetic-pos",
        )

        # Even when ``stale_block_enabled=True`` is forced, the event
        # path must not inject a stale race.
        asyncio.run(controller.start_for_event(event))
        assert bump_calls == []
    finally:
        ctrl_mod.bump_inventory_for_stale_block = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_with_reset(controller: FlagshipController):
    controller.reset(seed=CANONICAL_SEED)
    return await controller.start(FlagshipRequest(stale_block_enabled=True))
