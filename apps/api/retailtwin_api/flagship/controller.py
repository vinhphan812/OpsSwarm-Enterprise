"""Flagship Controller implementation.

A single-shot, stateful controller that drives the autonomous chain on the
canonical services. The controller is wired at app startup with a provider, a
Live Twin boundary, a deterministic KPI evaluator, and a tool registry
backed by the same Live Twin. The ``start`` call publishes the canonical
``sale.completed`` event, runs investigator + planner + simulator, deliberately
bumps the Live Twin to provoke a stale ``REFRESH_REQUIRED`` from the guard, and
then runs the canonical ``replan`` loop. The committed decision is verified
post-hoc on the same Live Twin.

The state machine is intentionally narrow:

    IDLE  → reset()        → IDLE          (deterministic reset)
    IDLE  → start()        → RUNNING → COMPLETE | ERROR
    ANY   → status()       → returns the current snapshot

The controller does not retry, does not paginate, and does not keep
multi-run history. A second ``start`` requires a fresh ``reset``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from retailtwin_api.agents.executor.executor import GuardedExecutor
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.replan import (
    CommitPort,
    ContextVersionSource,
    ReplanResult,
    ReplanStatus,
    SimulationPort,
    replan,
)
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry
from retailtwin_api.agents.simulator.branch import (
    CandidateEvaluator,
    LiveView,
    SlotView,
    simulate,
)
from retailtwin_api.agents.verifier.verify import (
    InMemoryVerificationAudit,
    InventoryReader,
    VerificationReport,
    VerificationStatus,
    verify,
)
from retailtwin_api.contracts import Decision, ReplenishShelf
from retailtwin_api.demand_surge import (
    CANONICAL_SEED,
    SKU as DEMO_SKU,
    STORE_ID as DEMO_STORE_ID,
    reset_weekend_demand_surge,
)
from retailtwin_api.firestore_twin import (
    InventoryDocument,
    LiveTwinRepository,
)
from retailtwin_api.flagship._stale_bump import bump_inventory_for_stale_block
from retailtwin_api.guard.decision_context_guard import (
    InMemoryGuardAudit,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.authorization import (
    CommitAuthorizer,
    InMemoryAuthorizationLedger,
)
from retailtwin_api.guard.decision_context_guard.guard import DecisionContextGuard
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding
from retailtwin_api.schemas import ProductInventory, StoreEvent, StoreResponse

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase / result / status dataclasses
# ---------------------------------------------------------------------------


class FlagshipPhase(str, Enum):
    """Lifecycle of one flagship run."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class FlagshipStateError(RuntimeError):
    """The controller was asked to start without a reset or while running."""


@dataclass
class FlagshipRunResult:
    """Terminal outcome of a single ``start`` call."""

    run_id: str
    phase: FlagshipPhase
    correlation_id: str
    seed: int
    context_version_before: str
    context_version_after: str
    guard_verdict: str
    guard_reason_code: str
    committed_decision_id: str | None
    replan_refresh_count: int
    replan_reason_code: str
    verification_status: str | None
    verification_reason_code: str | None
    timeline: list[dict[str, str]]
    error: str | None = None
    replay_token: str = ""


@dataclass
class FlagshipStatus:
    """Result of the ``status`` call. Safe to serialize as JSON."""

    run_id: str
    phase: FlagshipPhase
    seed: int
    started_at: str | None
    completed_at: str | None
    correlation_id: str | None
    context_version: str | None
    guard_verdict: str | None
    guard_reason_code: str | None
    committed_decision_id: str | None
    replan_refresh_count: int
    replan_reason_code: str | None
    verification_status: str | None
    verification_reason_code: str | None
    timeline: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    last_result: FlagshipRunResult | None = None


# ---------------------------------------------------------------------------
# Wire contracts
# ---------------------------------------------------------------------------


class LlmPort(Protocol):
    """Provider-neutral LLM contract — same shape as ``LlmProvider``."""

    async def complete(self, request: Any) -> Any: ...


class StoreReads(Protocol):
    """The Live Twin read surface used by the tool registry and verifier."""

    store_id: str

    def view(self) -> StoreResponse: ...

    def inventory(self, sku: str) -> ProductInventory | None: ...


class FlagshipRequest(BaseModel):
    """Body for POST /flagship/start — knobs that keep the run reproducible."""

    model_config = ConfigDict(extra="forbid")

    seed: int = Field(default=CANONICAL_SEED, ge=1, le=1)
    # Stale-block injection is a demo/test affordance: production refuses
    # the underlying bump helper (``flagship/_stale_bump.py`` raises on
    # ``APP_ENV=production``), so the default must keep production on a
    # real-event path. Non-production envs (test/dev/staging/e2e-smoke)
    # opt into the stale → replan → commit path by default; production
    # opts out. Evaluated per-instance so tests can override ``APP_ENV``
    # per request via ``monkeypatch.setenv``.
    stale_block_enabled: bool = Field(
        default_factory=lambda: os.environ.get("APP_ENV") != "production",
    )
    max_refreshes: int = Field(default=1, ge=0, le=3)
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_inventory(reader: StoreReads, sku: str) -> ProductInventory:
    item = reader.inventory(sku)
    if item is None:
        raise KeyError(f"SKU {sku!r} is not in store {reader.store_id!r}.")
    return item


def _build_live_view(
    reader: StoreReads,
    *,
    correlation_id: str,
) -> LiveView:
    """Translate a ``StoreResponse`` into a ``LiveView`` for the simulator."""

    snapshot = reader.view()
    slots: list[SlotView] = []
    for product in snapshot.products:
        slots.append(
            SlotView(
                sku=product.sku,
                slot_id=product.slot_id,
                shelf_quantity=product.shelf_quantity,
                backroom_quantity=product.backroom_quantity,
                facings=product.facings,
                sales_velocity_units_per_hour="0",
                price="0",
            )
        )
    return LiveView(
        store_id=snapshot.store_id,
        context_version=snapshot.context_version,
        correlation_id=correlation_id,
        observed_at=_now(),
        slots=tuple(slots),
    )


class _LiveContextSource(ContextVersionSource):
    """Reads the current context version from a Live Twin adapter."""

    def __init__(self, reader: StoreReads) -> None:
        self._reader = reader

    def context_version(self, store_id: str) -> str:
        return self._reader.view().context_version


class _CommitSpy(CommitPort):
    """The commit port the ``replan`` loop writes to.

    ``commit`` reissues a signed authorization for the binding the replan
    loop already produced, then delegates to the canonical
    :class:`GuardedExecutor` so the Live Twin write goes through the
    production ``commit_inventory`` boundary (ADR 0016). The spy records
    committed decisions and before/after inventory snapshots for the
    verification step.
    """

    def __init__(
        self,
        twin: LiveTwinRepository,
        store_id: str,
        audit: InMemoryVerificationAudit,
        gate: NoStaleCommit,
        clock: Callable[[], datetime],
    ) -> None:
        self._twin = twin
        self._store_id = store_id
        self._audit = audit
        self._gate = gate
        self._clock = clock
        self._lock = threading.Lock()
        self.committed: list[Decision] = []
        self.bindings: list[CommitBinding] = []
        self.before_by_sku: dict[str, ProductInventory] = {}
        self.after_by_sku: dict[str, ProductInventory] = {}
        # Per-spy in-process signing key — tokens never leave the process.
        # The decision→token→executor chain mirrors production
        # ``CommitService.approve`` so the canonical guard + authorizer +
        # executor flow runs end-to-end. All three components share the
        # caller's clock so token issue/expiry and the guard's freshness
        # window stay aligned (otherwise the executor sees TOKEN_EXPIRED on
        # redemption in tests where both clocks lock to one moment).
        self._authorizer = CommitAuthorizer(
            signing_key=secrets.token_hex(32).encode("utf-8"),
            ledger=InMemoryAuthorizationLedger(),
            clock=clock,
        )
        self._executor = GuardedExecutor(
            twin,
            self._authorizer,
            gate,
            clock=clock,
        )

    def snapshot_before(self, skus: Sequence[str], reader: StoreReads) -> None:
        with self._lock:
            for sku in skus:
                item = _read_inventory(reader, sku)
                self.before_by_sku[sku] = item

    def commit(self, decision: Decision, binding: CommitBinding) -> None:
        # The replan loop already authorized and rechecked the binding; the
        # spy reissues a signed authorization and routes through the guarded
        # executor so the Live Twin write goes through the canonical
        # ``commit_inventory`` boundary.
        if not self.before_by_sku:
            self.snapshot_before([DEMO_SKU], _ReaderAdapter(self._twin, self._store_id))
        token = self._authorizer.issue(decision, binding)
        outcome = self._executor.commit(decision, token)
        if not outcome.committed:
            # The executor refuses with a reason code copied from the guard;
            # surface it as a state error so the surrounding controller code
            # sees the failure the same way it would for a production path.
            raise FlagshipStateError(
                f"guarded executor refused decision_id={decision.decision_id} "
                f"reason={outcome.reason_code}"
            )
        with self._lock:
            self.committed.append(decision)
            self.bindings.append(binding)
            for action in decision.proposed_actions:
                if not isinstance(action, ReplenishShelf):
                    continue
                after = self._twin.get_inventory(self._store_id, action.sku)
                if after is not None:
                    self.after_by_sku[action.sku] = _ReaderAdapter._to_product(after)

    @property
    def decisions(self) -> list[Decision]:
        with self._lock:
            return list(self.committed)


class _ReaderAdapter(StoreReads):
    """Bridge a ``LiveTwinRepository`` to the ``StoreReads`` protocol."""

    def __init__(self, twin: LiveTwinRepository, store_id: str) -> None:
        self._twin = twin
        self.store_id = store_id
        self._lock = threading.Lock()

    def view(self) -> StoreResponse:
        with self._lock:
            store = self._twin.get_store(self.store_id)
            version = store.version if store is not None else "v1"
            context_version = store.context_version() if store is not None else f"{self.store_id}:{version}"
            items = list(self._twin.list_inventory(self.store_id))
            products = [self._to_product(item) for item in items]
            return StoreResponse(
                store_id=self.store_id,
                context_version=context_version,
                version=version,
                products=products,
            )

    def inventory(self, sku: str) -> ProductInventory | None:
        with self._lock:
            doc = self._twin.get_inventory(self.store_id, sku)
            if doc is None:
                return None
            return self._to_product(doc)

    @staticmethod
    def _to_product(doc: InventoryDocument) -> ProductInventory:
        return ProductInventory(
            store_id=doc.store_id,
            sku=doc.sku,
            shelf_id=doc.shelf_id,
            slot_id=doc.slot_id,
            facings=doc.facings,
            shelf_quantity=doc.shelf_quantity,
            backroom_quantity=doc.backroom_quantity,
            version=doc.version,
        )


class _StubInventoryReader(InventoryReader):
    """Inventory reader backed by the Live Twin — used by the verifier."""

    def __init__(self, twin: LiveTwinRepository, store_id: str) -> None:
        self._twin = twin
        self._store_id = store_id

    def inventory(self, sku: str) -> ProductInventory | None:
        doc = self._twin.get_inventory(self._store_id, sku)
        if doc is None:
            return None
        return ProductInventory(
            store_id=doc.store_id,
            sku=doc.sku,
            shelf_id=doc.shelf_id,
            slot_id=doc.slot_id,
            facings=doc.facings,
            shelf_quantity=doc.shelf_quantity,
            backroom_quantity=doc.backroom_quantity,
            version=doc.version,
        )


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


@dataclass
class FlagshipDependencies:
    """External wiring injected at app startup. None of the fields are optional."""

    provider: LlmPort
    twin: LiveTwinRepository
    store_id: str
    registry: ToolRegistry
    evaluator: CandidateEvaluator
    clock: Callable[[], datetime] = _now


class FlagshipController:
    """Deterministic flagship demo controller.

    The controller holds the wire dependencies and the run-state lock. Every
    public method is thread-safe; ``start`` is the only async method because
    the canonical chain is awaited end-to-end.
    """

    def __init__(self, deps: FlagshipDependencies | None = None) -> None:
        self._deps = deps
        self._lock = threading.RLock()
        self._phase: FlagshipPhase = FlagshipPhase.IDLE
        self._run_id: str | None = None
        self._correlation_id: str | None = None
        self._seed: int = CANONICAL_SEED
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._timeline: list[dict[str, str]] = []
        self._last_result: FlagshipRunResult | None = None
        self._error: str | None = None
        self._reset_count = 0

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def configure(self, deps: FlagshipDependencies) -> None:
        """Attach the wire dependencies. Called once at app startup."""
        with self._lock:
            self._deps = deps

    @property
    def is_configured(self) -> bool:
        return self._deps is not None

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def reset(self, *, seed: int = CANONICAL_SEED) -> dict[str, Any]:
        """Reset the controller state and clear the Live Twin to canonical seed.

        The Live Twin is reseeded via the canonical ``LiveTwinRepository.seed``
        boundary, so a Firestore-backed run and an in-memory test run exercise
        the same path.
        """
        if seed != CANONICAL_SEED:
            raise ValueError("Flagship controller accepts only the canonical seed (1).")
        with self._lock:
            self._require_deps()
            self._reset_count += 1
            self._phase = FlagshipPhase.IDLE
            self._run_id = None
            self._correlation_id = None
            self._seed = seed
            self._started_at = None
            self._completed_at = None
            self._timeline = []
            self._last_result = None
            self._error = None
            self._reseed_twin(seed)
        self._add_event("reset", f"controller reset to seed {seed}")
        return {
            "run_id": self._run_id or "",
            "phase": self._phase.value,
            "seed": self._seed,
            "context_version": self._deps_view().context_version,
        }

    def status(self) -> FlagshipStatus:
        with self._lock:
            return FlagshipStatus(
                run_id=self._run_id or "",
                phase=self._phase,
                seed=self._seed,
                started_at=self._started_at.isoformat() if self._started_at else None,
                completed_at=self._completed_at.isoformat() if self._completed_at else None,
                correlation_id=self._correlation_id,
                context_version=self._safe_context_version(),
                guard_verdict=self._last_result.guard_verdict if self._last_result else None,
                guard_reason_code=self._last_result.guard_reason_code if self._last_result else None,
                committed_decision_id=(
                    self._last_result.committed_decision_id if self._last_result else None
                ),
                replan_refresh_count=self._last_result.replan_refresh_count if self._last_result else 0,
                replan_reason_code=self._last_result.replan_reason_code if self._last_result else None,
                verification_status=self._last_result.verification_status if self._last_result else None,
                verification_reason_code=(
                    self._last_result.verification_reason_code if self._last_result else None
                ),
                timeline=list(self._timeline),
                error=self._error,
                last_result=self._last_result,
            )

    async def start(self, request: FlagshipRequest | None = None) -> FlagshipRunResult:
        """Run the autonomous chain end-to-end. Returns the terminal result.

        This is the **demo /flagship/start** entry point: it rebuilds the
        canonical weekend-demand-surge ``sale.completed`` event from the
        demand-surge seed and drives the chain against it. Production
        autonomous events must use :meth:`start_for_event` instead — this
        path reseeds the Live Twin via :meth:`reset` and is not safe for
        real production traffic.
        """
        body = request or FlagshipRequest()
        with self._lock:
            self._require_deps()
            if self._phase not in (FlagshipPhase.IDLE, FlagshipPhase.COMPLETE, FlagshipPhase.ERROR):
                raise FlagshipStateError(
                    f"Cannot start from phase {self._phase.value}. Call reset() first."
                )
            self._run_id = uuid.uuid4().hex[:12]
            self._correlation_id = body.correlation_id or f"run-weekend-demand-surge-{self._seed}"
            self._seed = body.seed
            self._started_at = _now()
            self._completed_at = None
            self._timeline = []
            self._error = None
            self._phase = FlagshipPhase.RUNNING
            self._add_event("start", f"flagship start run_id={self._run_id} seed={self._seed}")

        # 1) EVENT — rebuild the canonical sale event from the demand-surge seed.
        events = reset_weekend_demand_surge(self._seed)
        trigger = events[-1]
        # Replace the correlation id so investigators/planner see a single lineage.
        trigger_event = trigger.model_copy(
            update={"correlation_id": self._correlation_id}
        )
        self._add_event(
            "event",
            f"sale.completed sku={DEMO_SKU} correlation_id={self._correlation_id}",
        )
        start = InvestigationStart(
            investigation_id=f"inv-{self._run_id}",
            event=trigger_event,
        )

        try:
            result = await self._drive_chain(start, body)
        except Exception as exc:  # noqa: BLE001 — surface anything
            log.exception("flagship run failed run_id=%s", self._run_id)
            with self._lock:
                self._phase = FlagshipPhase.ERROR
                self._completed_at = _now()
                self._error = f"{type(exc).__name__}: {exc}"
                self._add_event("error", self._error)
            raise

        with self._lock:
            self._phase = FlagshipPhase.COMPLETE if result.phase is FlagshipPhase.COMPLETE else FlagshipPhase.ERROR
            self._completed_at = _now()
            self._last_result = result
        return result

    async def start_for_event(
        self,
        event: StoreEvent,
        correlation_id: str | None = None,
    ) -> FlagshipRunResult:
        """Drive the autonomous chain against a real incoming event.

        Production autonomous events (ADR 0023) enter through this method.
        Differences from :meth:`start`:

        * **No Live reset.** The Live Twin stays in whatever state the
          store currently holds — a real sale must investigate the *current*
          store, not a freshly seeded demo baseline.
        * **No stale-block injection.** ``stale_block_enabled`` is forced
          to ``False`` regardless of ``APP_ENV``; real events never need a
          deterministic ``REFRESH_REQUIRED`` race. The injection is a demo
          artefact.
        * The full event content (``event_id``, ``sku``, ``quantity``,
          ``occurred_at``, ``store_id``, ``correlation_id``) is preserved
          end-to-end and propagated to the investigator/planner/replan
          chain.

        The event is still subject to the canonical guard and replan loop;
        only the deterministic-reset and stale-injection knobs are turned
        off. Live Twin writes still go through the guarded Executor
        (ADR 0016).
        """
        if not self.is_configured:
            raise FlagshipStateError(
                "Flagship controller is not configured. Call register_dependencies() first."
            )
        # Pin the autonomous event path to the canonical seed (ADR 0023)
        # and force ``stale_block_enabled=False`` so a real Pub/Sub message
        # never triggers a deterministic ``REFRESH_REQUIRED`` injection.
        body = FlagshipRequest(
            stale_block_enabled=False,
            correlation_id=correlation_id or event.correlation_id,
        )
        with self._lock:
            self._require_deps()
            if self._phase not in (FlagshipPhase.IDLE, FlagshipPhase.COMPLETE, FlagshipPhase.ERROR):
                raise FlagshipStateError(
                    f"Cannot start_for_event from phase {self._phase.value}."
                )
            self._run_id = uuid.uuid4().hex[:12]
            self._correlation_id = body.correlation_id or f"event-{event.event_id}"
            self._seed = body.seed
            self._started_at = _now()
            self._completed_at = None
            self._timeline = []
            self._error = None
            self._phase = FlagshipPhase.RUNNING
            self._add_event(
                "start",
                f"flagship start_for_event event_id={event.event_id} sku={event.sku} store_id={event.store_id}",
            )
            self._add_event(
                "event",
                f"sale.completed sku={event.sku} correlation_id={self._correlation_id}",
            )

        start = InvestigationStart(
            investigation_id=f"inv-{event.event_id}",
            event=event,
        )

        try:
            result = await self._drive_chain(start, body)
        except Exception as exc:  # noqa: BLE001 — surface anything
            log.exception(
                "flagship start_for_event failed event_id=%s run_id=%s",
                event.event_id,
                self._run_id,
            )
            with self._lock:
                self._phase = FlagshipPhase.ERROR
                self._completed_at = _now()
                self._error = f"{type(exc).__name__}: {exc}"
                self._add_event("error", self._error)
            raise

        with self._lock:
            self._phase = FlagshipPhase.COMPLETE if result.phase is FlagshipPhase.COMPLETE else FlagshipPhase.ERROR
            self._completed_at = _now()
            self._last_result = result
        return result

    # ------------------------------------------------------------------
    # Internal flow
    # ------------------------------------------------------------------

    async def _drive_chain(
        self,
        start: InvestigationStart,
        body: FlagshipRequest,
    ) -> FlagshipRunResult:
        """Drive the canonical chain. Failures surface as a result with phase=ERROR.

        Shared by :meth:`start` (demo /flagship/start path, which builds the
        canonical seed event) and :meth:`start_for_event` (autonomous event
        path, which uses the real incoming ``StoreEvent``). Steps 2-7 below
        are identical for both entry points; only the event source differs.
        """
        assert self._deps is not None
        deps = self._deps
        run_id = self._run_id or uuid.uuid4().hex[:12]
        correlation_id = self._correlation_id or f"run-weekend-demand-surge-{self._seed}"
        store_id = deps.store_id

        # 2) INVESTIGATE — provider calls the read tools, no Live writes.
        try:
            from retailtwin_api.agents.investigator.evidence import investigate
            bundle = await investigate(
                start,
                provider=deps.provider,  # type: ignore[arg-type]
                registry=deps.registry,
                collected_at=deps.clock(),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(run_id, correlation_id, "investigate", f"investigator failed: {exc}")
        self._add_event("investigate", f"evidence bundle_id={bundle.bundle_id} sufficient={bundle.is_sufficient}")

        # 3) PLAN — read-only candidate decisions, no scoring yet.
        try:
            from retailtwin_api.agents.planner.plans import plan
            decisions = await plan(
                bundle,
                provider=deps.provider,  # type: ignore[arg-type]
                context_version=self._deps_view().context_version,
                context_timestamp=deps.clock(),
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(run_id, correlation_id, "plan", f"planner failed: {exc}")
        if not decisions:
            return self._fail(run_id, correlation_id, "plan", "planner returned no decisions")
        first_decision = decisions[0]
        self._add_event(
            "plan",
            f"first decision_id={first_decision.decision_id} actions={[a.__class__.__name__ + ':' + a.model_dump_json() for a in first_decision.proposed_actions]}",
        )

        # 4) SIMULATE — score every decision on a clone of the live snapshot.
        live_before = _build_live_view(self._reader_adapter(store_id), correlation_id=correlation_id)
        try:
            simulation = simulate(decisions, live_before, evaluate=deps.evaluator)
        except Exception as exc:  # noqa: BLE001
            return self._fail(run_id, correlation_id, "simulate", f"simulator failed: {exc}")
        scored = list(simulation.candidates)
        self._add_event(
            "simulate",
            f"scored {len(scored)} candidates simulation_id={simulation.simulation_id} top_score={scored[0].kpi.kpi_score if scored else 'n/a'}",
        )

        # 5) GUARD — optionally bump Live to provoke a REFRESH_REQUIRED
        # stale block. The canonical race the issue is asking us to detect
        # comes from the Live Twin moving between ``plan`` and the guard's
        # ``authorize`` call. The bump is the only thing the controller
        # controls for reproducibility. The helper refuses to run when
        # ``APP_ENV`` is ``production`` (ADR 0016 — only the guarded Executor
        # writes the Live Twin in production), so we surface that as a
        # fail-safely error result instead of letting it crash the demo.
        # Autonomous-event callers pass ``stale_block_enabled=False``
        # (ADR 0023), so a real Pub/Sub message never hits this branch.
        bumped = False
        if body.stale_block_enabled and scored:
            try:
                bumped = self._bump_inventory(store_id, DEMO_SKU)
            except RuntimeError as exc:
                return self._fail(
                    run_id,
                    correlation_id,
                    "guard",
                    f"stale-block injection refused: {exc}",
                )

        reader = self._reader_adapter(store_id)
        audit = InMemoryGuardAudit()
        guard = NoStaleCommit(
            DecisionContextGuard(deps.twin, clock=deps.clock),
            audit,
            clock=deps.clock,
        )
        live_view_after_bump = _build_live_view(reader, correlation_id=correlation_id)
        first_verdict, first_binding = guard.authorize(first_decision)
        self._add_event(
            "guard",
            f"verdict={first_verdict.verdict.value} reason={first_verdict.reason_code} context={live_view_after_bump.context_version}",
        )

        if body.stale_block_enabled:
            # The bumped decision must be refused. Anything else means the
            # canonical stale-block test could not run.
            if first_binding is not None or first_verdict.verdict.value != "REFRESH_REQUIRED":
                return self._fail(
                    run_id,
                    correlation_id,
                    "guard",
                    (
                        "expected REFRESH_REQUIRED on the stale decision but the guard returned "
                        f"{first_verdict.verdict.value} reason={first_verdict.reason_code}"
                    ),
                )
            if not bumped:
                return self._fail(
                    run_id, correlation_id, "guard",
                    "Live Twin did not move; stale block test cannot run.",
                )

        committed_decision: Decision
        replan_refresh_count = 0
        replan_reason_code = "ALLOWED"
        if first_verdict.verdict.value == "ALLOW" and first_binding is not None:
            # Direct ALLOW: no replan needed. Commit the first decision
            # ourselves through the same guarded boundary the replan loop uses.
            self._add_event("replan", "status=SKIPPED reason=direct_allow refreshes=0")
            commit_spy = _CommitSpy(
                deps.twin,
                store_id,
                InMemoryVerificationAudit(),
                guard,
                deps.clock,
            )
            commit_spy.snapshot_before([DEMO_SKU], reader)
            commit_spy.commit(first_decision, first_binding)
            committed_decision = first_decision
        else:
            # 6) REPLAN — refresh, plan, simulate, guard again, commit.
            if bumped:
                # Reflect the bump in the view used by the replan loop so the
                # context source returns v<N+1> not v<N>.
                reader = self._reader_adapter(store_id)
            audit_replan = InMemoryGuardAudit()
            replan_guard = NoStaleCommit(
                DecisionContextGuard(deps.twin, clock=deps.clock),
                audit_replan,
                clock=deps.clock,
            )
            contexts = _LiveContextSource(reader)
            commit_spy = _CommitSpy(
                deps.twin,
                store_id,
                InMemoryVerificationAudit(),
                replan_guard,
                deps.clock,
            )
            commit_spy.snapshot_before([DEMO_SKU], reader)
            simulation_port: SimulationPort | None = self._simulation_port(correlation_id, reader)

            try:
                replan_result: ReplanResult = await replan(
                    first_decision,
                    start,
                    authorizer=replan_guard,
                    provider=deps.provider,  # type: ignore[arg-type]
                    registry=deps.registry,
                    commit=commit_spy,
                    contexts=contexts,
                    simulate=simulation_port,
                    max_refreshes=body.max_refreshes,
                    clock=deps.clock,
                )
            except Exception as exc:  # noqa: BLE001
                return self._fail(run_id, correlation_id, "replan", f"replan raised: {exc}")
            self._add_event(
                "replan",
                f"status={replan_result.status.value} reason={replan_result.reason_code} refreshes={replan_result.refresh_count}",
            )
            if replan_result.status is not ReplanStatus.COMMITTED:
                return self._fail(
                    run_id,
                    correlation_id,
                    "replan",
                    f"replan did not commit: {replan_result.status.value} reason={replan_result.reason_code}",
                )
            if not commit_spy.decisions:
                return self._fail(
                    run_id, correlation_id, "replan",
                    "replan reported committed but commit spy saw no decision",
                )
            committed_decision = commit_spy.decisions[-1]
            replan_refresh_count = replan_result.refresh_count
            replan_reason_code = replan_result.reason_code

        # 7) VERIFY — re-read Live inventory and compare against the pre-commit baseline.
        verify_audit = InMemoryVerificationAudit()
        verify_reader = _StubInventoryReader(deps.twin, store_id)
        try:
            verification: VerificationReport = verify(
                committed_decision,
                dict(commit_spy.before_by_sku),
                verify_reader,
                verify_audit,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(run_id, correlation_id, "verify", f"verifier raised: {exc}")
        self._add_event(
            "verify",
            f"status={verification.status.value} reason={verification.reason_code}",
        )

        after_view = _build_live_view(self._reader_adapter(store_id), correlation_id=correlation_id)
        return FlagshipRunResult(
            run_id=run_id,
            phase=FlagshipPhase.COMPLETE,
            correlation_id=correlation_id,
            seed=self._seed,
            context_version_before=live_before.context_version,
            context_version_after=after_view.context_version,
            guard_verdict=first_verdict.verdict.value,
            guard_reason_code=first_verdict.reason_code,
            committed_decision_id=committed_decision.decision_id,
            replan_refresh_count=replan_refresh_count,
            replan_reason_code=replan_reason_code,
            verification_status=verification.status.value,
            verification_reason_code=verification.reason_code,
            timeline=list(self._timeline),
            replay_token=json.dumps(
                {
                    "seed": self._seed,
                    "correlation_id": correlation_id,
                    "guard_verdict": first_verdict.verdict.value,
                    "guard_reason_code": first_verdict.reason_code,
                },
                sort_keys=True,
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_deps(self) -> None:
        if self._deps is None:
            raise FlagshipStateError(
                "Flagship controller is not configured. Call register_dependencies() first."
            )

    def _deps_view(self) -> StoreResponse:
        assert self._deps is not None
        return self._reader_adapter(self._deps.store_id).view()

    def _safe_context_version(self) -> str | None:
        if not self.is_configured:
            return None
        try:
            return self._deps_view().context_version
        except Exception:  # noqa: BLE001
            return None

    def _reader_adapter(self, store_id: str) -> StoreReads:
        assert self._deps is not None
        return _ReaderAdapter(self._deps.twin, store_id)

    def _dual_twin_reader(self, store_id: str) -> Any:
        """Unused — kept for backwards-compatible test stubs."""
        return None

    def _reseed_twin(self, seed: int) -> None:
        """Re-seed the Live Twin via the canonical ``seed`` boundary.

        ``reset_weekend_demand_surge`` rebuilds the canonical series for seed
        1; we always include the demand-surge SKU P017 so the store has the
        same baseline shape at the start of every run, regardless of which
        fixture the application happens to ship.
        """
        assert self._deps is not None
        from retailtwin_api.firestore_twin import InventorySeed
        from retailtwin_api.settings import DEFAULT_FIXTURE
        from retailtwin_api.store import StoreRepository

        fixture = StoreRepository(DEFAULT_FIXTURE, self._deps.store_id)
        if not fixture.loaded:
            raise FlagshipStateError(
                f"canonical fixture is not loaded: {fixture.error}"
            )
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
                    shelf_id="A02",
                    slot_id="A02-S03",
                    facings=2,
                    shelf_quantity=8,
                    backroom_quantity=54,
                )
            )
        self._deps.twin.seed(self._deps.store_id, snapshot.version, items)
        # Touch the demand-surge series so the seed parameter is observable in
        # structured logs and the controller will refuse non-canonical seeds.
        _ = reset_weekend_demand_surge(seed)

    def _bump_inventory(self, store_id: str, sku: str) -> bool:
        """Mutate the Live Twin so the next authorize call returns REFRESH_REQUIRED.

        The actual ``commit_inventory`` write is performed by the
        test-only helper :func:`retailtwin_api.flagship._stale_bump.bump_inventory_for_stale_block`,
        which refuses to run when ``APP_ENV`` is ``production`` (ADR 0016
        — only the guarded Executor writes the Live Twin in production).
        This module never calls the Live Twin mutation API directly.

        Returns True when the Live Twin was successfully bumped; False if no
        bump could be applied (e.g. no live document, the optimistic lock
        conflicted, or APP_ENV is ``production`` and the helper raised).
        """
        assert self._deps is not None
        return bump_inventory_for_stale_block(self._deps.twin, store_id, sku)

    def _simulation_port(self, correlation_id: str, reader: StoreReads) -> SimulationPort:
        """The replan loop's simulation port — reuses the canonical simulator."""

        outer = self

        class _Port(SimulationPort):
            def score(self, decisions: Sequence[Decision]) -> list[Decision]:
                live = _build_live_view(reader, correlation_id=correlation_id)
                scored = simulate(decisions, live, evaluate=outer._deps.evaluator)  # type: ignore[union-attr]
                return [candidate.decision for candidate in scored.candidates]

        return _Port()

    def _fail(
        self,
        run_id: str,
        correlation_id: str,
        stage: str,
        message: str,
    ) -> FlagshipRunResult:
        self._add_event(stage, message)
        log.warning("flagship stage=%s message=%s run_id=%s", stage, message, run_id)
        return FlagshipRunResult(
            run_id=run_id,
            phase=FlagshipPhase.ERROR,
            correlation_id=correlation_id,
            seed=self._seed,
            context_version_before="",
            context_version_after=self._safe_context_version() or "",
            guard_verdict="",
            guard_reason_code="",
            committed_decision_id=None,
            replan_refresh_count=0,
            replan_reason_code=message,
            verification_status=None,
            verification_reason_code=None,
            timeline=list(self._timeline),
            error=message,
        )

    def _add_event(self, stage: str, detail: str) -> None:
        with self._lock:
            self._timeline.append({
                "stage": stage,
                "detail": detail,
                "at": _now().isoformat(),
            })


# ---------------------------------------------------------------------------
# Process-wide singleton + app wiring
# ---------------------------------------------------------------------------


_controller: FlagshipController | None = None
_controller_lock = threading.Lock()


def get_controller() -> FlagshipController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = FlagshipController()
        return _controller


def register_dependencies(
    *,
    provider: LlmPort,
    twin: LiveTwinRepository,
    store_id: str,
    registry: ToolRegistry,
    evaluator: CandidateEvaluator,
    clock: Callable[[], datetime] = _now,
) -> FlagshipController:
    """Wire the controller to the canonical services. Called once at startup."""
    deps = FlagshipDependencies(
        provider=provider,
        twin=twin,
        store_id=store_id,
        registry=registry,
        evaluator=evaluator,
        clock=clock,
    )
    controller = get_controller()
    controller.configure(deps)
    return controller


# Re-export for tests that want to build the live view manually.
__all__ = [
    "FlagshipController",
    "FlagshipPhase",
    "FlagshipRequest",
    "FlagshipRunResult",
    "FlagshipStatus",
    "LlmPort",
    "StoreReads",
    "_build_live_view",
    "get_controller",
    "register_dependencies",
]
