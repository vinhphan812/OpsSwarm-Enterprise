"""Demo Controller — deterministic flagship demo orchestration.

Provides a resettable DEMO SCENARIO MODE for Weekend Demand Surge.
Controls: random seed, event timing, initial state reset, deliberate stale-context mutation.
Demo scaffold: In-memory simulation only. No external providers, no Firestore, no production services.

This module lives under retailtwin_api.demo_runtime — demo-only, never imported
by production code outside this namespace.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

# --------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

from retailtwin_api.demo_runtime.agents.executor import ExecutorAgent
from retailtwin_api.demo_runtime.agents.verifier import VerifierAgent
from retailtwin_api.demo_runtime.guard.decision_context_guard import DCG, Decision
from retailtwin_api.demo_runtime.services.simulation import SimulationService
from retailtwin_api.demo_runtime.services.twin import TwinService

# --------------------------------------------------------------------------


class DemoPhase(str, Enum):
    """Current phase of the demo orchestration."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class TimelineEvent:
    """An event in the demo timeline."""
    event_id: str
    phase: str
    timestamp: str
    detail: str


@dataclass
class DemoStatus:
    """Response shape for /demo/status."""
    run_id: str
    phase: DemoPhase
    started_at: str | None
    completed_at: str | None
    context_version: str | None
    events_emitted: int
    decision_id: str | None
    dcg_verdict: str | None
    executor_committed: bool
    verifier_outcome: str | None
    timeline: list[TimelineEvent]
    error: str | None


# --------------------------------------------------------------------------
# Demo scenario definition
# --------------------------------------------------------------------------

DEFAULT_FIXTURES = [
    {"slot_id": "s01", "sku": "P001", "facings": 4, "shelf_quantity": 20, "backroom_quantity": 50},
    {"slot_id": "s02", "sku": "P002", "facings": 3, "shelf_quantity": 15, "backroom_quantity": 40},
    {"slot_id": "s03", "sku": "P003", "facings": 2, "shelf_quantity": 10, "backroom_quantity": 30},
    {"slot_id": "s04", "sku": "P017", "facings": 3, "shelf_quantity": 12, "backroom_quantity": 35},  # demand surge SKU
    {"slot_id": "s05", "sku": "P005", "facings": 5, "shelf_quantity": 25, "backroom_quantity": 60},
]


def make_surge_event(run_id: str, slot_id: str, sku: str) -> dict:
    """Create a demand-surge StoreEvent."""
    return {
        "event_id": f"evt-{run_id[:8]}-{uuid.uuid4().hex[:4]}",
        "correlation_id": f"run-{run_id[:8]}",
        "event_type": "sale.completed",
        "store_id": "store-001",
        "sku": sku,
        "quantity": 5,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "demo-surge",
    }


# --------------------------------------------------------------------------
# DemoOrchestrator — the stateful controller
# --------------------------------------------------------------------------

class DemoOrchestrator:
    """Stateful demo controller.

    Canonical flow:
    1. reset() — reset twin to fixtures
    2. start() — begin autonomous loop
    3. status() — read current state
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = DemoPhase.IDLE
        self._run_id: str | None = None
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._twin = None
        self._simulation = None
        self._dcg = None
        self._executor = None
        self._verifier = None
        self._timeline: list[TimelineEvent] = []
        self._decision_id: str | None = None
        self._dcg_verdict: str | None = None
        self._executor_committed = False
        self._verifier_outcome: str | None = None
        self._error: str | None = None
        self._fixtures = DEFAULT_FIXTURES

        # Bind services (injected via setup())
        self._twin_cls: type | None = None
        self._sim_cls: type | None = None
        self._dcg_cls: type | None = None
        self._exec_cls: type | None = None
        self._verif_cls: type | None = None

    def setup(
        self,
        twin_cls: type,
        sim_cls: type,
        dcg_cls: type,
        exec_cls: type,
        verif_cls: type,
        fixtures: list[dict] | None = None,
    ) -> None:
        """Inject service classes and fixtures. Called once at app startup."""
        self._twin_cls = twin_cls
        self._sim_cls = sim_cls
        self._dcg_cls = dcg_cls
        self._exec_cls = exec_cls
        self._verif_cls = verif_cls
        if fixtures is not None:
            self._fixtures = fixtures

    def reset(self, seed: int | None = None, stale_context_test: bool = False) -> dict:
        """Reset demo to initial state."""
        with self._lock:
            self._run_id = uuid.uuid4().hex[:12]
            self._phase = DemoPhase.IDLE
            self._started_at = None
            self._completed_at = None
            self._timeline = []
            self._decision_id = None
            self._dcg_verdict = None
            self._executor_committed = False
            self._verifier_outcome = None
            self._error = None

            # Initialize services
            assert self._twin_cls is not None, "setup() must be called before reset()"
            assert self._sim_cls is not None, "setup() must be called before reset()"
            assert self._dcg_cls is not None, "setup() must be called before reset()"
            assert self._exec_cls is not None, "setup() must be called before reset()"
            assert self._verif_cls is not None, "setup() must be called before reset()"
            twin = self._twin_cls("store-001")  # type: ignore[misc]
            twin.reset(self._fixtures)
            assert self._sim_cls is not None
            sim = self._sim_cls(twin)  # type: ignore[misc]
            assert self._dcg_cls is not None
            dcg = self._dcg_cls(twin)  # type: ignore[misc]
            assert self._exec_cls is not None
            exec_agent = self._exec_cls(twin)  # type: ignore[misc]
            assert self._verif_cls is not None
            verif = self._verif_cls(twin, sim)  # type: ignore[misc]

            self._twin = twin
            self._simulation = sim
            self._dcg = dcg
            self._executor = exec_agent
            self._verifier = verif

            self._timeline.append(
                TimelineEvent(
                    event_id=f"reset-{self._run_id}",
                    phase="reset",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    detail=f"Demo reset. Stale-context test: {stale_context_test}",
                )
            )

            return {
                "run_id": self._run_id,
                "phase": self._phase.value,
                "context_version": twin.get_context_version(),
                "slots_loaded": len(self._fixtures),
            }

    def start(self, stale_context_test: bool = False) -> dict:
        """Start the autonomous demo loop."""
        with self._lock:
            if self._phase not in (DemoPhase.IDLE, DemoPhase.COMPLETE):
                return {"error": f"Cannot start from phase {self._phase.value}"}

            self._phase = DemoPhase.RUNNING
            self._started_at = datetime.now(timezone.utc)
            self._executor_committed = False
            self._dcg_verdict = None
            self._decision_id = None
            self._verifier_outcome = None

        try:
            return self._run_loop(stale_context_test)
        except Exception as e:
            with self._lock:
                self._phase = DemoPhase.ERROR
                self._error = str(e)
                self._completed_at = datetime.now(timezone.utc)
            raise

    def _run_loop(self, stale_context_test: bool) -> dict:
        """Execute the autonomous demo loop (synchronous for MVP)."""
        assert self._twin is not None, "Call reset() first"
        assert self._simulation is not None
        assert self._dcg is not None
        assert self._executor is not None
        assert self._verifier is not None

        # Phase 1: Event — emit demand-surge event
        self._add_event("event", "Demand surge detected for P017")

        # Phase 2: Simulate — clone twin, apply candidate action
        sim_snap = self._simulation.clone()
        actions = [{"action_type": "facings", "slot_id": "s04", "facings": 5}]
        sim_results = self._simulation.apply(sim_snap, actions)
        before_kpi = self._simulation.evaluate(sim_snap)
        self._add_event(
            "simulate",
            f"Simulated facings change: {sim_results[0].after}",
        )

        # Phase 3: DCG — create decision
        decision_id = f"dec-{self._run_id}-{uuid.uuid4().hex[:4]}"
        from datetime import timedelta

        if stale_context_test:
            # Use old context version to simulate stale decision
            twin_state = self._twin.read()
            context_before = twin_state.context_version

            decision = Decision(
                decision_id=decision_id,
                context_version=context_before,  # stale version
                context_timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
                proposed_actions=actions,
            )
        else:
            twin_state = self._twin.read()
            decision = Decision(
                decision_id=decision_id,
                context_version=twin_state.context_version,
                context_timestamp=datetime.now(timezone.utc),
                proposed_actions=actions,
            )

        verdict = self._dcg.validate(decision)
        self._dcg_verdict = verdict.verdict.value
        self._decision_id = decision_id

        self._add_event(
            "dcg",
            f"DCG verdict: {verdict.verdict.value}. Errors: {verdict.errors}",
        )

        # Phase 4: Execute — if ALLOW, commit
        if verdict.verdict.value == "ALLOW":
            auth = self._dcg.authorize(decision)
            if auth:
                results = self._executor.execute(auth, self._dcg.validate_authorization)
                self._executor_committed = True
                self._add_event(
                    "execute",
                    f"Executor committed: {[r.success for r in results]}",
                )
            else:
                self._add_event("execute", "DCG authorized but executor rejected authorization")
        else:
            self._add_event(
                "execute",
                f"DCG blocked decision. Executor performed no mutation.",
            )

        # Phase 5: Verify
        after_snap = self._simulation.clone()
        after_kpi = self._simulation.evaluate(after_snap)
        expected_kpis = {
            "total_shelf": before_kpi.total_shelf_quantity,
            "total_facings": before_kpi.total_facings + 2,  # facings changed
        }
        verif_result = self._verifier.verify_decision(
            decision_id, expected_kpis, tolerance=0.15
        )
        self._verifier_outcome = verif_result.outcome.value

        self._add_event(
            "verify",
            f"Verifier: {verif_result.outcome.value}. KPIs: {verif_result.measured_kpis}",
        )

        with self._lock:
            self._phase = DemoPhase.COMPLETE
            self._completed_at = datetime.now(timezone.utc)

        return {
            "run_id": self._run_id,
            "phase": self._phase.value,
            "decision_id": decision_id,
            "dcg_verdict": self._dcg_verdict,
            "executor_committed": self._executor_committed,
            "verifier_outcome": self._verifier_outcome,
        }

    def status(self) -> DemoStatus:
        """Return current demo status."""
        with self._lock:
            return DemoStatus(
                run_id=self._run_id or "",
                phase=self._phase,
                started_at=self._started_at.isoformat() if self._started_at else None,
                completed_at=self._completed_at.isoformat() if self._completed_at else None,
                context_version=self._twin.get_context_version() if self._twin else None,
                events_emitted=len([e for e in self._timeline if e.phase == "event"]),
                decision_id=self._decision_id,
                dcg_verdict=self._dcg_verdict,
                executor_committed=self._executor_committed,
                verifier_outcome=self._verifier_outcome,
                timeline=list(self._timeline),
                error=self._error,
            )

    def timeline_events(self) -> list[TimelineEvent]:
        """Return timeline events."""
        with self._lock:
            return list(self._timeline)

    def _add_event(self, phase: str, detail: str) -> None:
        with self._lock:
            self._timeline.append(
                TimelineEvent(
                    event_id=f"evt-{uuid.uuid4().hex[:6]}",
                    phase=phase,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    detail=detail,
                )
            )


# --------------------------------------------------------------------------
# Global singleton
# --------------------------------------------------------------------------

_orchestrator: DemoOrchestrator | None = None
_orchestrator_lock = threading.Lock()


def get_orchestrator() -> DemoOrchestrator:
    global _orchestrator
    with _orchestrator_lock:
        if _orchestrator is None:
            _orchestrator = DemoOrchestrator()
        return _orchestrator


def setup_demo(app: FastAPI) -> None:
    """Wire demo services into the orchestrator. Call from main.py startup."""
    from retailtwin_api.demo_runtime.services.twin import TwinService
    from retailtwin_api.demo_runtime.services.simulation import SimulationService
    from retailtwin_api.demo_runtime.guard.decision_context_guard import DCG
    from retailtwin_api.demo_runtime.agents.executor import ExecutorAgent
    from retailtwin_api.demo_runtime.agents.verifier import VerifierAgent

    orch = get_orchestrator()
    orch.setup(
        twin_cls=TwinService,
        sim_cls=SimulationService,
        dcg_cls=DCG,
        exec_cls=ExecutorAgent,
        verif_cls=VerifierAgent,
    )
    app.state.demo_orchestrator = orch
