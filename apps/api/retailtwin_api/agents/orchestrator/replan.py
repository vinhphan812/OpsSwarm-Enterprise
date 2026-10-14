"""Refresh evidence and authorize a new decision after a stale rejection.

``REFRESH_REQUIRED`` discards the binding from the rejected decision. The same
injected provider then runs the investigator and the planner. The new
``Decision`` carries the context version read from an injected source after
that refresh, not the version on the rejected decision. The commit port is
called only after ``ALLOW`` survives ``recheck``. This module does not write
the Live Twin and does not branch on which vendor the provider calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from retailtwin_api.agents.investigator.evidence import InvestigatorError, investigate
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry
from retailtwin_api.agents.planner.plans import UNSCORED_IMPACT, PlannerError, plan
from retailtwin_api.contracts import DCGVerdict, Decision
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding, NoStaleCommit
from retailtwin_api.llm.contracts import LlmProvider

log = logging.getLogger(__name__)

MAX_REFRESHES_ENV = "RETAILTWIN_REPLAN_MAX_REFRESHES"
DEFAULT_MAX_REFRESHES = 1

LINEAGE_MISMATCH = "lineage_mismatch"
PROVIDER_FAILED = "provider_failed"
SIMULATION_FAILED = "simulation_failed"
EMPTY_PLAN = "empty_plan"
COMMIT_FAILED = "commit_failed"
MISSING_BINDING = "missing_binding"
CONTEXT_UNAVAILABLE = "context_unavailable"
CONTEXT_MISMATCH = "context_mismatch"


class ReplanConfigError(ValueError):
    """The refresh bound is set but is not a non-negative integer."""


class ReplanStatus(str, Enum):
    """How one recovery attempt ended. A commit exists only for ``COMMITTED``."""

    COMMITTED = "COMMITTED"
    DENIED = "DENIED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    RETRY_LIMIT = "RETRY_LIMIT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ReplanResult:
    """The terminal outcome. ``decision_id`` is the decision the loop stopped on."""

    status: ReplanStatus
    correlation_id: str
    decision_id: str | None
    committed_decision_id: str | None
    verdict: DCGVerdict | None
    reason_code: str
    refresh_count: int
    context_version: str | None


class CommitPort(Protocol):
    """Hands an allowed decision to the guarded commit path.

    Called only with a binding that ``authorize`` just issued and ``recheck``
    still allows. Implementations must not accept a binding from an earlier
    ``REFRESH_REQUIRED``.
    """

    def commit(self, decision: Decision, binding: CommitBinding) -> None: ...


class SimulationPort(Protocol):
    """Scores refreshed decisions. The orchestrator does not compute a KPI."""

    def score(self, decisions: Sequence[Decision]) -> Sequence[Decision]: ...


class ContextVersionSource(Protocol):
    """The store's current canonical context version.

    Read after each evidence refresh, for that investigation's store. The
    rejected decision is not a source for this value. A later refresh reads
    it again.
    """

    def context_version(self, store_id: str) -> str: ...


def max_refreshes_from_env(environ: Mapping[str, str] | None = None) -> int:
    """Read ``RETAILTWIN_REPLAN_MAX_REFRESHES``. Unset or blank stays at 1."""

    env = os.environ if environ is None else environ
    raw = env.get(MAX_REFRESHES_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_REFRESHES
    try:
        value = int(raw)
    except ValueError:
        raise ReplanConfigError(f"{MAX_REFRESHES_ENV} must be a non-negative integer.") from None
    if value < 0:
        raise ReplanConfigError(f"{MAX_REFRESHES_ENV} must be a non-negative integer.")
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _limit(max_refreshes: int | None) -> int:
    if max_refreshes is None:
        return max_refreshes_from_env()
    if max_refreshes < 0:
        raise ReplanConfigError("max_refreshes must be a non-negative integer.")
    return max_refreshes


def _same_lineage(decision: Decision, start: InvestigationStart) -> bool:
    event = start.event
    if not decision.evidence:
        return False
    return all(
        bundle.store_id == event.store_id and bundle.correlation_id == event.correlation_id
        for bundle in decision.evidence
    )


def _prefer(decisions: Sequence[Decision]) -> list[Decision]:
    """Authorize a scored candidate before an unscored one. ``-1.0`` is not a score."""

    indexed = list(enumerate(decisions))
    scored = [item for item in indexed if item[1].expected_impact.kpi_score != UNSCORED_IMPACT]
    unscored = [item[1] for item in indexed if item[1].expected_impact.kpi_score == UNSCORED_IMPACT]
    scored.sort(key=lambda item: (-item[1].expected_impact.kpi_score, item[0]))
    return [item[1] for item in scored] + unscored


def _finish(
    status: ReplanStatus,
    correlation_id: str,
    decision_id: str | None,
    committed_decision_id: str | None,
    verdict: DCGVerdict | None,
    reason_code: str,
    refresh_count: int,
    context_version: str | None,
) -> ReplanResult:
    log.info(
        "replan finished correlation_id=%s status=%s reason=%s refreshes=%s decision_id=%s",
        correlation_id,
        status.value,
        reason_code,
        refresh_count,
        decision_id or "",
    )
    return ReplanResult(
        status=status,
        correlation_id=correlation_id,
        decision_id=decision_id,
        committed_decision_id=committed_decision_id,
        verdict=verdict,
        reason_code=reason_code,
        refresh_count=refresh_count,
        context_version=context_version,
    )


def _from_guard(
    status: ReplanStatus,
    verdict_name: DCGVerdict,
    reason_code: str,
    correlation_id: str,
    decision_id: str,
    refresh_count: int,
    context_version: str,
) -> ReplanResult:
    return _finish(
        status,
        correlation_id,
        decision_id,
        None,
        verdict_name,
        reason_code,
        refresh_count,
        context_version,
    )


def _distinct(decisions: Sequence[Decision], seen: set[str], refresh: int) -> list[Decision]:
    """New immutable decisions: an id already used in this run gets an ``-r{refresh}`` suffix."""

    distinct: list[Decision] = []
    for item in decisions:
        decision_id = item.decision_id
        while decision_id in seen:
            decision_id = f"{decision_id}-r{refresh}"
        seen.add(decision_id)
        distinct.append(item if decision_id == item.decision_id else item.model_copy(update={"decision_id": decision_id}))
    return distinct


def _carry_context(decisions: Sequence[Decision], version: str) -> bool:
    return all(item.context_version == version for item in decisions)


async def _refresh(
    start: InvestigationStart,
    *,
    provider: LlmProvider,
    registry: ToolRegistry,
    contexts: ContextVersionSource,
    stopped_context_version: str,
    simulate: SimulationPort | None,
    clock: Callable[[], datetime],
    previous_decision_id: str,
    refreshes: int,
    limit: int,
    reason_code: str,
) -> list[Decision] | ReplanResult:
    correlation_id = start.event.correlation_id
    if refreshes >= limit:
        # The bound is already spent. Report the rejected decision's version
        # and do not read a new one or pass the old one to the planner.
        return _finish(
            ReplanStatus.RETRY_LIMIT,
            correlation_id,
            previous_decision_id,
            None,
            DCGVerdict.REFRESH_REQUIRED,
            reason_code,
            refreshes,
            stopped_context_version,
        )
    attempt = refreshes + 1

    def failed(reason: str, context_version: str | None) -> ReplanResult:
        return _finish(
            ReplanStatus.FAILED,
            correlation_id,
            previous_decision_id,
            None,
            DCGVerdict.REFRESH_REQUIRED,
            reason,
            attempt,
            context_version,
        )

    now = clock()
    log.info(
        "replan refresh correlation_id=%s previous_decision_id=%s refresh=%s",
        correlation_id,
        previous_decision_id,
        attempt,
    )
    try:
        bundle = await investigate(start, provider=provider, registry=registry, collected_at=now)
    except InvestigatorError:
        log.info(
            "replan provider failed correlation_id=%s error_type=InvestigatorError",
            correlation_id,
        )
        return failed(PROVIDER_FAILED, stopped_context_version)
    if bundle.correlation_id != correlation_id or bundle.store_id != start.event.store_id:
        return failed(LINEAGE_MISMATCH, stopped_context_version)
    try:
        raw_context = contexts.context_version(start.event.store_id)
    except Exception as exc:
        log.info(
            "replan context unavailable correlation_id=%s error_type=%s",
            correlation_id,
            type(exc).__name__,
        )
        return failed(CONTEXT_UNAVAILABLE, None)
    if not isinstance(raw_context, str) or not raw_context.strip():
        log.info(
            "replan context unavailable correlation_id=%s error_type=blank",
            correlation_id,
        )
        return failed(CONTEXT_UNAVAILABLE, None)
    refreshed = raw_context.strip()
    try:
        decisions = await plan(
            bundle,
            provider=provider,
            context_version=refreshed,
            context_timestamp=now,
        )
    except PlannerError as exc:
        log.info(
            "replan planning failed correlation_id=%s reason=%s error_type=PlannerError",
            correlation_id,
            exc.reason,
        )
        return failed(exc.reason, stopped_context_version)
    if not _carry_context(decisions, refreshed):
        return failed(CONTEXT_MISMATCH, refreshed)
    if simulate is not None:
        try:
            produced = list(simulate.score(decisions))
        except Exception as exc:
            log.info(
                "replan simulation failed correlation_id=%s error_type=%s",
                correlation_id,
                type(exc).__name__,
            )
            return failed(SIMULATION_FAILED, stopped_context_version)
        if not produced or not all(_same_lineage(item, start) for item in produced):
            reason = EMPTY_PLAN if not produced else LINEAGE_MISMATCH
            return failed(reason, stopped_context_version)
        if not _carry_context(produced, refreshed):
            return failed(CONTEXT_MISMATCH, refreshed)
        decisions = produced
    return _prefer(decisions)


async def replan(
    decision: Decision,
    start: InvestigationStart,
    *,
    authorizer: NoStaleCommit,
    provider: LlmProvider,
    registry: ToolRegistry,
    commit: CommitPort,
    contexts: ContextVersionSource,
    simulate: SimulationPort | None = None,
    max_refreshes: int | None = None,
    clock: Callable[[], datetime] = _utcnow,
) -> ReplanResult:
    """Recover one run after a stale decision, or stop on a terminal verdict.

    ``max_refreshes`` counts ``REFRESH_REQUIRED`` cycles. Each cycle reads
    ``contexts`` after the evidence refresh and passes that version to
    ``plan``. The rejected decision's context version is not reused. A
    provider failure does not start another cycle and does not call ``commit``.
    """

    limit = _limit(max_refreshes)
    correlation_id = start.event.correlation_id
    if not _same_lineage(decision, start):
        return _finish(
            ReplanStatus.FAILED,
            correlation_id,
            decision.decision_id,
            None,
            None,
            LINEAGE_MISMATCH,
            0,
            decision.context_version,
        )
    pending: list[Decision] = [decision]
    # Every decision this loop has seen. A refreshed plan reuses the planner's
    # ``plan-{correlation}-{sku}-{n}`` ids, so it is renamed until it is distinct.
    seen_ids: set[str] = {decision.decision_id}
    refreshes = 0
    stopped_context = decision.context_version
    while pending:
        current = pending.pop(0)
        stopped_context = current.context_version
        verdict, binding = authorizer.authorize(current)
        if verdict.verdict is DCGVerdict.ALLOW:
            if binding is None:
                return _finish(
                    ReplanStatus.FAILED,
                    correlation_id,
                    current.decision_id,
                    None,
                    verdict.verdict,
                    MISSING_BINDING,
                    refreshes,
                    verdict.context_version,
                )
            checked = authorizer.recheck(current, binding)
            if checked.verdict is DCGVerdict.REFRESH_REQUIRED:
                # The binding and the rejected context version are not reused.
                outcome = await _refresh(
                    start,
                    provider=provider,
                    registry=registry,
                    contexts=contexts,
                    stopped_context_version=current.context_version,
                    simulate=simulate,
                    clock=clock,
                    previous_decision_id=current.decision_id,
                    refreshes=refreshes,
                    limit=limit,
                    reason_code=checked.reason_code,
                )
                if isinstance(outcome, ReplanResult):
                    return outcome
                refreshes += 1
                pending = _distinct(outcome, seen_ids, refreshes)
                continue
            if checked.verdict is not DCGVerdict.ALLOW:
                status = (
                    ReplanStatus.HUMAN_REVIEW
                    if checked.verdict is DCGVerdict.HUMAN_REVIEW
                    else ReplanStatus.DENIED
                )
                return _from_guard(
                    status,
                    checked.verdict,
                    checked.reason_code,
                    correlation_id,
                    current.decision_id,
                    refreshes,
                    checked.context_version,
                )
            try:
                commit.commit(current, binding)
            except Exception as exc:
                log.info(
                    "replan commit failed correlation_id=%s decision_id=%s error_type=%s",
                    correlation_id,
                    current.decision_id,
                    type(exc).__name__,
                )
                return _finish(
                    ReplanStatus.FAILED,
                    correlation_id,
                    current.decision_id,
                    None,
                    DCGVerdict.ALLOW,
                    COMMIT_FAILED,
                    refreshes,
                    checked.context_version,
                )
            return _finish(
                ReplanStatus.COMMITTED,
                correlation_id,
                current.decision_id,
                current.decision_id,
                DCGVerdict.ALLOW,
                checked.reason_code,
                refreshes,
                checked.context_version,
            )
        if verdict.verdict is DCGVerdict.REFRESH_REQUIRED:
            outcome = await _refresh(
                start,
                provider=provider,
                registry=registry,
                contexts=contexts,
                stopped_context_version=current.context_version,
                simulate=simulate,
                clock=clock,
                previous_decision_id=current.decision_id,
                refreshes=refreshes,
                limit=limit,
                reason_code=verdict.reason_code,
            )
            if isinstance(outcome, ReplanResult):
                return outcome
            refreshes += 1
            pending = _distinct(outcome, seen_ids, refreshes)
            continue
        if verdict.verdict is DCGVerdict.HUMAN_REVIEW:
            return _from_guard(
                ReplanStatus.HUMAN_REVIEW,
                verdict.verdict,
                verdict.reason_code,
                correlation_id,
                current.decision_id,
                refreshes,
                verdict.context_version,
            )
        if pending:
            continue
        return _from_guard(
            ReplanStatus.DENIED,
            verdict.verdict,
            verdict.reason_code,
            correlation_id,
            current.decision_id,
            refreshes,
            verdict.context_version,
        )
    return _finish(
        ReplanStatus.FAILED,
        correlation_id,
        decision.decision_id,
        None,
        None,
        EMPTY_PLAN,
        refreshes,
        stopped_context,
    )
