"""Autonomous investigations: a new sale starts the agent without a prompt (G03).

``AutonomousInvestigations`` is the Observer's ``InvestigationStarter``. The
handoff only queues the investigation, so the Observer can commit its
activation and acknowledge the message. ``drain`` then runs each queued
investigation:

1. OBSERVE      the activation is recorded;
2. INVESTIGATE  versioned evidence from the tool registry;
3. PLAN         candidate decisions bound to the current context version;
4. SIMULATE     the preferred candidate becomes an open proposal, and its
                Decision is stored for ``POST /simulations/{id}/approve``.

Every step writes one Agent Activity entry with the event's correlation id.
Nothing here writes the Live Twin: a proposal reaches Live only through the
approve route, the Decision Context Guard and the guarded Executor.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from retailtwin_api.agent_activity import AgentActivityLog
from retailtwin_api.agents.investigator.evidence import InvestigatorError, investigate
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry
from retailtwin_api.agents.planner.plans import PlannerError, plan
from retailtwin_api.contracts import ControlStage, Decision
from retailtwin_api.llm.contracts import LlmProvider
from retailtwin_api.schemas import StoreResponse
from retailtwin_api.simulation_schemas import SimulationDetail

log = logging.getLogger(__name__)

STARTED = "started"
COMPLETED = "completed"
FAILED = "failed"
INSUFFICIENT = "insufficient_evidence"


class ProposalStore(Protocol):
    def record(self, run: SimulationDetail) -> None: ...


class DecisionStore(Protocol):
    def put(self, simulation_id: str, decision: Decision) -> None: ...


@dataclass(frozen=True)
class InvestigationRun:
    """How one autonomous investigation ended."""

    investigation_id: str
    correlation_id: str
    status: str
    reason: str | None = None
    simulation_id: str | None = None
    decision_id: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutonomousInvestigations:
    def __init__(
        self,
        *,
        provider: LlmProvider,
        registry: ToolRegistry,
        store_view: Callable[[], StoreResponse],
        proposals: ProposalStore,
        decisions: DecisionStore,
        activity: AgentActivityLog,
        build_state: Callable[[StoreResponse, list[Any]], Any],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._store_view = store_view
        self._proposals = proposals
        self._decisions = decisions
        self._activity = activity
        self._build_state = build_state
        self._clock = clock
        self._lock = threading.Lock()
        self._queue: list[InvestigationStart] = []

    # InvestigationStarter -------------------------------------------------

    def start_investigation(self, start: InvestigationStart) -> None:
        """Record the OBSERVE stage and queue the investigation for ``drain``.

        Historical / G03 entry point. The production autonomous event path
        (ADR 0023) now drives investigations through
        :class:`FlagshipInvestigationStarter`, which preserves the full
        event content without resetting the Live Twin. This method is
        kept for backwards compatibility with the original ``/events``
        handler and unit tests that exercise the legacy queue + drain
        chain.
        """
        event = start.event
        self._activity.record(
            ControlStage.OBSERVE,
            STARTED,
            event.correlation_id,
            run_id=start.investigation_id,
            sku=event.sku,
            summary=f"{event.event_type} {event.event_id} started an investigation without a prompt.",
            at=self._clock(),
        )
        with self._lock:
            self._queue.append(start)

    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        """Production autonomous-event entry point (ADR 0023).

        The :class:`ObserverConsumer` protocol uses this method when
        handing a real incoming event to its investigation starter. For
        :class:`AutonomousInvestigations` (the legacy G03 chain) it is a
        thin alias over :meth:`start_investigation` — the OBSERVE record
        and queue append are identical. Production Pub/Sub events route
        through :class:`FlagshipInvestigationStarter.start_investigation_for_event`
        instead, which drives :class:`FlagshipController.start_for_event`
        and preserves the full event payload without resetting the Live
        Twin.
        """
        self.start_investigation(start)

    # Runner ---------------------------------------------------------------

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def drain(self) -> list[InvestigationRun]:
        """Run every queued investigation. Failures are recorded, never raised."""
        runs: list[InvestigationRun] = []
        while True:
            with self._lock:
                if not self._queue:
                    return runs
                start = self._queue.pop(0)
            runs.append(asyncio.run(self.run(start)))

    async def run(self, start: InvestigationStart) -> InvestigationRun:
        event = start.event
        cid = event.correlation_id
        run_id = start.investigation_id

        def finish(status: str, stage: ControlStage, reason: str | None, **ids: str | None) -> InvestigationRun:
            log.info(
                "autonomy finished correlation_id=%s investigation_id=%s status=%s reason=%s",
                cid,
                run_id,
                status,
                reason or "",
            )
            if status == FAILED:
                self._activity.record(
                    stage, FAILED, cid, run_id=run_id, sku=event.sku, summary=reason, at=self._clock()
                )
            return InvestigationRun(run_id, cid, status, reason, ids.get("simulation_id"), ids.get("decision_id"))

        try:
            bundle = await investigate(start, provider=self._provider, registry=self._registry, collected_at=self._clock())
        except InvestigatorError:
            return finish(FAILED, ControlStage.INVESTIGATE, "provider_failed")
        self._activity.record(
            ControlStage.INVESTIGATE,
            COMPLETED if bundle.is_sufficient else INSUFFICIENT,
            cid,
            run_id=run_id,
            sku=event.sku,
            summary=f"{len(bundle.items)} evidence items; versions {dict(bundle.entity_versions)}",
            at=self._clock(),
        )

        try:
            base = self._store_view()
            candidates = await plan(
                bundle, provider=self._provider, context_version=base.context_version, context_timestamp=self._clock()
            )
        except PlannerError as exc:
            return finish(FAILED, ControlStage.PLAN, exc.reason)
        except Exception as exc:
            return finish(FAILED, ControlStage.PLAN, type(exc).__name__)
        chosen = candidates[0]
        self._activity.record(
            ControlStage.PLAN,
            COMPLETED,
            cid,
            run_id=run_id,
            decision=chosen.decision_id,
            sku=event.sku,
            summary=f"{len(candidates)} candidate plans at {base.context_version}",
            at=self._clock(),
        )

        simulation_id = f"sim-{run_id}"
        decision = chosen.model_copy(update={"simulation_id": simulation_id})
        try:
            now = self._clock()
            self._proposals.record(
                SimulationDetail(
                    simulation_id=simulation_id,
                    store_id=event.store_id,
                    base_context_version=base.context_version,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                    provenance="autonomous-investigation",
                    actions=list(decision.proposed_actions),
                    state=self._build_state(base, list(decision.proposed_actions)),
                    correlation_id=cid,
                    agent_id=decision.agent_id,
                )
            )
            self._decisions.put(simulation_id, decision)
        except Exception as exc:
            return finish(FAILED, ControlStage.SIMULATE, type(exc).__name__)
        self._activity.record(
            ControlStage.SIMULATE,
            COMPLETED,
            cid,
            run_id=run_id,
            decision=decision.decision_id,
            simulation_id=simulation_id,
            sku=event.sku,
            summary="Proposal open for review; Live changes only through the guarded approve route.",
            at=self._clock(),
        )
        return finish(COMPLETED, ControlStage.SIMULATE, None, simulation_id=simulation_id, decision_id=decision.decision_id)
