"""Bounded automatic rollback policy after a verifier regression.

The Verifier (ADR 0017) confirms a committed decision by re-reading the Live
Twin. When the re-read disagrees with the transition the actions named, the
caller has three choices: replan (ADR 0018), pause for human review, or roll
back the changes that were just applied. Issue #55 owns the rollback path.

This module is the rollback policy. It is bounded by ``max_attempts`` to
prevent a recovery from triggering another regression. It is gated by a
feature flag (``RECOVERY_AUTO_ENABLED``, default ``False``) so the policy is
opt-in until G06 submission-gate evidence is on record. The activation rule is:

- ``VERIFIED`` → no automatic recovery, surface ``HUMAN_REVIEW_REQUIRED``.
- ``REGRESSION`` or ``INCONCLUSIVE`` → propose an inverse action only
  (``replenish_shelf`` → ``deplete_shelf``, ``change_facings`` → restore the
  baseline facings, ``move_product`` → reverse slot swap).
- A recovery proposal is not an execution. ``execute_recovery`` re-runs the
  Decision Context Guard on fresh reads, refuses on ``DENY`` /
  ``HUMAN_REVIEW`` / ``REFRESH_REQUIRED``, and applies the inverse through a
  recovery commit port that respects the Live Twin's optimistic concurrency.

The audit chain from the original execution and the recovery execution share
the original ``correlation_id``. The recovery events are written to a
``RecoveryAuditSink`` so the original ``retailtwin_api.audit.trail`` table
stays focused on the day-0 ``agent_actions`` lineage; the recovery trace can
be promoted to a separate table in a later change.

This module never writes the Live Twin directly. The injected
``RecoveryExecutor`` is the only path that mutates state, and it must apply
the inverse through the guarded Executor or an equivalent write port.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Protocol

from retailtwin_api.agents.verifier.verify import VerificationReport, VerificationStatus
from retailtwin_api.contracts import (
    ActionUnion,
    ChangeFacings,
    DCGVerdict,
    DCGVerdictResult,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding
from retailtwin_api.schemas import ProductInventory

log = logging.getLogger(__name__)

RECOVERY_AUTO_ENABLED_ENV = "RECOVERY_AUTO_ENABLED"
MAX_ATTEMPTS_ENV = "RETAILTWIN_RECOVERY_MAX_ATTEMPTS"

DEFAULT_MAX_ATTEMPTS = 1

RECOVERY_REASON_VERIFIED = "verified"
RECOVERY_REASON_LINKAGE_OK = "linkage_ok"
RECOVERY_REASON_NO_INVERSE = "no_inverse"
RECOVERY_REASON_LINKAGE_MISSING = "linkage_missing"
RECOVERY_REASON_BUDGET_EXHAUSTED = "budget_exhausted"
RECOVERY_REASON_FEATURE_DISABLED = "feature_disabled"
RECOVERY_REASON_STALE_RECOVERY = "stale_recovery"
RECOVERY_REASON_GUARD_REJECTED = "guard_rejected"
RECOVERY_REASON_CONSERVATION = "conservation_violation"
RECOVERY_REASON_EXECUTED = "executed"


class RecoveryOutcome(str, Enum):
    """How one recovery attempt ended.

    The proposal outcome is what the policy decided. The execution outcome is
    what the executor did with that proposal. They share the same enum so the
    caller sees a single terminal status per recovery.
    """

    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BLOCKED_NO_LINKAGE = "BLOCKED_NO_LINKAGE"
    BLOCKED_BUDGET_EXHAUSTED = "BLOCKED_BUDGET_EXHAUSTED"
    BLOCKED_CONSERVATION = "BLOCKED_CONSERVATION"


class RecoveryConservationError(Exception):
    """The inverse action would break inventory conservation on the Live Twin.

    The recovery commit port raises this when the inverse cannot be applied
    atomically: the shelf does not hold enough units to remove, or the
    backroom does not have enough free capacity to absorb the inverse. The
    higher-level recovery flow converts it into a ``BLOCKED_CONSERVATION``
    outcome with the same correlation id; the Live Twin is never partially
    written.
    """

    def __init__(
        self,
        *,
        sku: str,
        kind: str,
        reason: str,
        required: int,
        available: int,
    ) -> None:
        self.sku = sku
        self.kind = kind
        self.reason = reason
        self.required = required
        self.available = available
        super().__init__(
            f"recovery inverse refused: sku={sku!r} kind={kind!r} reason={reason!r} "
            f"required={required} available={available}"
        )


@dataclass(frozen=True)
class RecoveryPolicy:
    """Configuration for the automatic rollback policy.

    Attributes:
        max_attempts: Recovery budget per ``correlation_id``. The first
            inverse is attempt 0. A recovery that exceeds the bound is
            ``BLOCKED_BUDGET_EXHAUSTED``.
        inverse_only: When ``True``, only inverse actions are proposed. A
            policy that is allowed to invent new actions must change this
            flag and document the change in the ADR.
        linkage_required: When ``True``, the proposal is refused if the
            audit trail does not record an event for ``original_decision_id``
            under the same ``correlation_id``. Disabling linkage turns the
            recovery into a free-form planner, which is not what #55 wants.
    """

    max_attempts: int = 1
    inverse_only: bool = True
    linkage_required: bool = True


@dataclass(frozen=True)
class InverseAction:
    """The action to apply to undo a committed decision.

    The inverse of:
      - ``ReplenishShelf(sku, N)`` is ``deplete_shelf`` moving ``N`` units
        back from shelf to backroom.
      - ``ChangeFacings(sku, F)`` is ``change_facings`` restoring the
        baseline facing count carried in the recovery proposal.
      - ``MoveProduct(sku, A, B)`` is ``move_product`` with
        ``from_slot=B`` (current) and ``to_slot=A`` (original).

    The recovery commit port is responsible for applying the inverse
    semantics. The kind names align with the original ``ActionUnion`` names
    so a future port can wrap a regular action type with a direction flag.
    """

    kind: Literal["deplete_shelf", "change_facings", "move_product"]
    sku: str
    quantity: int | None = None
    facings: int | None = None
    from_slot: str | None = None
    to_slot: str | None = None


@dataclass(frozen=True)
class RecoveryProposal:
    """Suggested inverse of a verified-and-failed decision.

    The proposal is a typed message, not a side effect. ``execute_recovery``
    is the only function that may turn a ``PROPOSED`` proposal into a Live
    Twin change. ``outcome`` records what the policy decided; ``reason_code``
    carries the deterministic reason code that pairs with the outcome.
    """

    original_decision_id: str
    correlation_id: str
    store_id: str
    inverse_action: InverseAction
    required_versions: dict[str, int]
    freshness_at: datetime
    outcome: RecoveryOutcome
    reason_code: str
    attempt: int
    recovery_id: str = ""

    def __post_init__(self) -> None:
        if not self.recovery_id:
            object.__setattr__(
                self,
                "recovery_id",
                f"recovery:{self.original_decision_id}:r{self.attempt + 1}",
            )


@dataclass(frozen=True)
class RecoveryExecutionResult:
    """What ``execute_recovery`` did with one proposal.

    A non-``EXECUTED`` outcome carries ``executed_at=None`` and
    ``new_versions={}``. An ``EXECUTED`` outcome carries the post-write
    versions of the SKUs the inverse touched; callers can use those to chain
    a fresh read into a subsequent verification cycle.
    """

    proposal: RecoveryProposal
    outcome: RecoveryOutcome
    reason_code: str
    executed_at: datetime | None
    new_versions: dict[str, int]


@dataclass(frozen=True)
class RecoveryAuditEvent:
    """One stage of a recovery attempt, recorded with the original correlation id.

    The ``stage`` field is ``propose`` or ``execute``. Two proposals for the
    same decision appear as two events; the ``recovery_id`` ties them.
    """

    stage: str
    correlation_id: str
    original_decision_id: str
    recovery_id: str
    attempt: int
    outcome: RecoveryOutcome
    reason_code: str
    inverse_kind: str
    inverse_sku: str
    at: datetime


class RecoveryAuditSink(Protocol):
    """Where the recovery policy writes its trace. See ``InMemoryRecoveryAudit``."""

    def record(self, event: RecoveryAuditEvent) -> None: ...

    def events(
        self, original_decision_id: str | None = None
    ) -> list[RecoveryAuditEvent]: ...


class InMemoryRecoveryAudit:
    """Process-memory sink for recovery audit events."""

    def __init__(self) -> None:
        self._events: list[RecoveryAuditEvent] = []

    def record(self, event: RecoveryAuditEvent) -> None:
        self._events.append(event)

    def events(
        self, original_decision_id: str | None = None
    ) -> list[RecoveryAuditEvent]:
        """Return a copy of the recorded events, optionally filtered by decision id."""
        return [
            event
            for event in self._events
            if original_decision_id is None or event.original_decision_id == original_decision_id
        ]


class RecoveryConfigError(ValueError):
    """The recovery policy was given an invalid configuration."""


def recovery_auto_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Read ``RECOVERY_AUTO_ENABLED``. Default is False until G06 is on record."""
    env = os.environ if environ is None else environ
    raw = env.get(RECOVERY_AUTO_ENABLED_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def max_attempts_from_env(environ: Mapping[str, str] | None = None) -> int:
    """Read ``RETAILTWIN_RECOVERY_MAX_ATTEMPTS``. Default is 1."""
    env = os.environ if environ is None else environ
    raw = env.get(MAX_ATTEMPTS_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        raise RecoveryConfigError(f"{MAX_ATTEMPTS_ENV} must be a non-negative integer.") from None
    if value < 0:
        raise RecoveryConfigError(f"{MAX_ATTEMPTS_ENV} must be a non-negative integer.")
    return value


class AuthPipeline(Protocol):
    """Fresh-read + DCG validation for an inverse decision.

    Implementations must re-run the Decision Context Guard on a fresh Live
    Twin read (ADR 0014, ADR 0015). They must return ``(None, None)`` or
    any non-``ALLOW`` verdict to refuse the recovery without touching the
    Live Twin. The guard audit is recorded separately by the implementation.
    """

    def authorize(self, decision: Decision) -> tuple[DCGVerdictResult, CommitBinding | None]: ...


class RecoveryExecutor(Protocol):
    """Apply an inverse action to the Live Twin with the same guarantees as the guarded Executor.

    Implementations must refuse when the live version of any touched SKU has
    moved past ``required_versions``. They return the new versions after the
    write; an empty dict means no write happened.
    """

    def apply(
        self,
        inverse: InverseAction,
        *,
        required_versions: dict[str, int],
        correlation_id: str,
    ) -> dict[str, int]: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_inverse(
    action: ActionUnion, baseline: dict[str, ProductInventory]
) -> InverseAction | None:
    """Compute the inverse of one action against the pre-commit baseline."""
    if isinstance(action, ReplenishShelf):
        return InverseAction(kind="deplete_shelf", sku=action.sku, quantity=action.quantity)
    if isinstance(action, ChangeFacings):
        baseline_row = baseline.get(action.sku)
        if baseline_row is None:
            return None
        return InverseAction(kind="change_facings", sku=action.sku, facings=baseline_row.facings)
    if isinstance(action, MoveProduct):
        baseline_row = baseline.get(action.sku)
        if baseline_row is None:
            return None
        return InverseAction(
            kind="move_product",
            sku=action.sku,
            from_slot=action.to_slot,
            to_slot=baseline_row.slot_id,
        )
    return None


def _sentinel_inverse() -> InverseAction:
    """An empty inverse carried by non-``PROPOSED`` proposals so the field stays typed."""
    return InverseAction(kind="change_facings", sku="")


def _single_inverse(
    decision: Decision, baseline: dict[str, ProductInventory]
) -> InverseAction | None:
    """Recovery supports one SKU per decision; multi-SKU decisions stop for review."""
    skus = {action.sku for action in decision.proposed_actions}
    actions = list(decision.proposed_actions)
    if len(skus) != 1 or len(actions) != 1:
        return None
    return _build_inverse(actions[0], baseline)


def _correlation_id(
    decision: Decision, verification_report: VerificationReport
) -> str:
    if verification_report.correlation_id:
        return verification_report.correlation_id.strip()
    if decision.evidence:
        return decision.evidence[0].correlation_id.strip()
    return ""


def _store_id_from_decision(decision: Decision) -> str:
    """Return the single store id named by the original decision's evidence."""
    if not decision.evidence:
        return ""
    stores = {bundle.store_id.strip() for bundle in decision.evidence}
    stores.discard("")
    if len(stores) != 1:
        return ""
    return next(iter(stores))


def _has_linkage(
    decision_id: str,
    correlation_id: str,
    audit_trail: RecoveryAuditSink,
    decision: Decision,
) -> bool:
    """Decide whether the audit trail links the original decision to this recovery.

    The link is recorded when the original decision reached the
    ``EXECUTION`` stage. The simplest, deterministic check is: the audit
    trail must contain at least one event with the same ``correlation_id``
    and ``original_decision_id``, and the original decision must carry the
    same correlation id. ``executed_at`` is not required for the linkage to
    be valid: a refused decision still links to its recovery because the
    audit row exists.
    """
    if not correlation_id or not decision_id:
        return False
    if not decision.evidence:
        return False
    correlations = {bundle.correlation_id.strip() for bundle in decision.evidence}
    if correlation_id not in correlations:
        return False
    return any(
        event.original_decision_id == decision_id and event.correlation_id == correlation_id
        for event in audit_trail.events()
    )


def propose_recovery(
    decision: Decision,
    verification_report: VerificationReport,
    audit_trail: RecoveryAuditSink,
    *,
    baseline: dict[str, ProductInventory],
    current_versions: dict[str, int],
    policy: RecoveryPolicy = RecoveryPolicy(),
    attempt: int = 0,
    enabled: bool = False,
    now: datetime | None = None,
) -> RecoveryProposal:
    """Generate a recovery proposal for a decision whose verification was not VERIFIED.

    The function always returns a typed proposal. The ``outcome`` field tells
    the caller whether the proposal is ready for execution (``PROPOSED``) or
    why the policy refused to make one (``HUMAN_REVIEW_REQUIRED``,
    ``BLOCKED_NO_LINKAGE``, ``BLOCKED_BUDGET_EXHAUSTED``).

    Args:
        decision: The original ``Decision`` the Verifier just rejected.
        verification_report: The ``VerificationReport`` the Verifier returned.
        audit_trail: The sink that records the original execution. The
            proposal is refused when ``policy.linkage_required`` is ``True``
            and this sink has no event for ``decision.decision_id``.
        baseline: Pre-commit inventory rows the Verifier had. Used to compute
            the inverse ``ChangeFacings`` and ``MoveProduct`` actions.
        current_versions: Live Twin versions at proposal time. Required for
            No-Stale-Commit at execution time (ADR 0015).
        policy: The recovery policy to apply. Defaults to ``RecoveryPolicy()``.
        attempt: The recovery attempt counter, starting at ``0`` for the
            first inverse proposal.
        enabled: Whether the feature flag ``RECOVERY_AUTO_ENABLED`` is on.
            ``False`` means the policy proposes a proposal that records
            ``HUMAN_REVIEW_REQUIRED`` with ``feature_disabled``. The inverse
            is still computed so a human can inspect it.
        now: Optional clock override. The default is the wall clock at UTC.
    """
    timestamp = (now or _utcnow()).astimezone(timezone.utc)
    correlation_id = _correlation_id(decision, verification_report)
    store_id = _store_id_from_decision(decision)

    if verification_report.status is VerificationStatus.VERIFIED:
        proposal = RecoveryProposal(
            original_decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=store_id,
            inverse_action=_sentinel_inverse(),
            required_versions={},
            freshness_at=timestamp,
            outcome=RecoveryOutcome.HUMAN_REVIEW_REQUIRED,
            reason_code=RECOVERY_REASON_VERIFIED,
            attempt=attempt,
        )
        _record_propose(audit_trail, proposal)
        return proposal

    if not enabled:
        proposal = RecoveryProposal(
            original_decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=store_id,
            inverse_action=_sentinel_inverse(),
            required_versions={},
            freshness_at=timestamp,
            outcome=RecoveryOutcome.HUMAN_REVIEW_REQUIRED,
            reason_code=RECOVERY_REASON_FEATURE_DISABLED,
            attempt=attempt,
        )
        _record_propose(audit_trail, proposal)
        return proposal

    if attempt >= policy.max_attempts:
        proposal = RecoveryProposal(
            original_decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=store_id,
            inverse_action=_sentinel_inverse(),
            required_versions={},
            freshness_at=timestamp,
            outcome=RecoveryOutcome.BLOCKED_BUDGET_EXHAUSTED,
            reason_code=RECOVERY_REASON_BUDGET_EXHAUSTED,
            attempt=attempt,
        )
        _record_propose(audit_trail, proposal)
        return proposal

    if policy.linkage_required and not _has_linkage(
        decision.decision_id, correlation_id, audit_trail, decision
    ):
        proposal = RecoveryProposal(
            original_decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=store_id,
            inverse_action=_sentinel_inverse(),
            required_versions={},
            freshness_at=timestamp,
            outcome=RecoveryOutcome.BLOCKED_NO_LINKAGE,
            reason_code=RECOVERY_REASON_LINKAGE_MISSING,
            attempt=attempt,
        )
        _record_propose(audit_trail, proposal)
        return proposal

    inverse = _single_inverse(decision, baseline)
    if inverse is None:
        proposal = RecoveryProposal(
            original_decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=store_id,
            inverse_action=_sentinel_inverse(),
            required_versions={},
            freshness_at=timestamp,
            outcome=RecoveryOutcome.HUMAN_REVIEW_REQUIRED,
            reason_code=RECOVERY_REASON_NO_INVERSE,
            attempt=attempt,
        )
        _record_propose(audit_trail, proposal)
        return proposal

    proposal = RecoveryProposal(
        original_decision_id=decision.decision_id,
        correlation_id=correlation_id,
        store_id=store_id,
        inverse_action=inverse,
        required_versions=dict(current_versions),
        freshness_at=timestamp,
        outcome=RecoveryOutcome.PROPOSED,
        reason_code=RECOVERY_REASON_LINKAGE_OK,
        attempt=attempt,
    )
    _record_propose(audit_trail, proposal)
    log.info(
        "recovery proposed correlation_id=%s decision_id=%s recovery_id=%s kind=%s sku=%s",
        correlation_id,
        decision.decision_id,
        proposal.recovery_id,
        inverse.kind,
        inverse.sku,
    )
    return proposal


def execute_recovery(
    proposal: RecoveryProposal,
    *,
    auth_pipeline: AuthPipeline,
    executor: RecoveryExecutor,
    audit_trail: RecoveryAuditSink,
    now: datetime | None = None,
) -> RecoveryExecutionResult:
    """Execute a recovery proposal through the same DCG + freshness path.

    The execution:

    1. Re-validates the proposal outcome (``PROPOSED`` is the only one that
       proceeds past this point).
    2. Builds a synthetic ``Decision`` whose evidence mirrors the original
       and whose ``proposed_actions`` carry a forward-shaped inverse that
       the DCG can evaluate.
    3. Runs the ``AuthPipeline`` (No-Stale-Commit) on the synthetic decision.
       A non-``ALLOW`` verdict is returned as a blocked result.
    4. Compares the binding's ``entity_versions`` against the proposal's
       ``required_versions``. A mismatch is a stale recovery and is blocked.
    5. Calls ``RecoveryExecutor.apply`` with the inverse action, the binding
       versions, and the original ``correlation_id``.
    """
    timestamp = (now or _utcnow()).astimezone(timezone.utc)

    if proposal.outcome is not RecoveryOutcome.PROPOSED:
        result = RecoveryExecutionResult(
            proposal=proposal,
            outcome=proposal.outcome,
            reason_code=proposal.reason_code,
            executed_at=None,
            new_versions={},
        )
        _record_execute(audit_trail, proposal, result, timestamp)
        return result

    inverse_decision = _inverse_decision(proposal, timestamp)
    guard_result, binding = auth_pipeline.authorize(inverse_decision)
    if binding is None or guard_result.verdict is not DCGVerdict.ALLOW:
        result = RecoveryExecutionResult(
            proposal=proposal,
            outcome=RecoveryOutcome.BLOCKED_NO_LINKAGE,
            reason_code=guard_result.reason_code or RECOVERY_REASON_GUARD_REJECTED,
            executed_at=None,
            new_versions={},
        )
        _record_execute(audit_trail, proposal, result, timestamp)
        log.info(
            "recovery blocked correlation_id=%s decision_id=%s recovery_id=%s reason=%s",
            proposal.correlation_id,
            proposal.original_decision_id,
            proposal.recovery_id,
            result.reason_code,
        )
        return result

    if binding.entity_versions != proposal.required_versions:
        result = RecoveryExecutionResult(
            proposal=proposal,
            outcome=RecoveryOutcome.BLOCKED_NO_LINKAGE,
            reason_code=RECOVERY_REASON_STALE_RECOVERY,
            executed_at=None,
            new_versions={},
        )
        _record_execute(audit_trail, proposal, result, timestamp)
        log.info(
            "recovery blocked correlation_id=%s decision_id=%s recovery_id=%s reason=stale_recovery",
            proposal.correlation_id,
            proposal.original_decision_id,
            proposal.recovery_id,
        )
        return result

    try:
        new_versions = executor.apply(
            proposal.inverse_action,
            required_versions=dict(binding.entity_versions),
            correlation_id=proposal.correlation_id,
        )
    except RecoveryConservationError as conservation:
        result = RecoveryExecutionResult(
            proposal=proposal,
            outcome=RecoveryOutcome.BLOCKED_CONSERVATION,
            reason_code=RECOVERY_REASON_CONSERVATION,
            executed_at=None,
            new_versions={},
        )
        _record_execute(audit_trail, proposal, result, timestamp)
        log.info(
            "recovery blocked correlation_id=%s decision_id=%s recovery_id=%s reason=conservation sku=%s detail=%s",
            proposal.correlation_id,
            proposal.original_decision_id,
            proposal.recovery_id,
            conservation.sku,
            conservation.reason,
        )
        return result
    if not new_versions:
        # The executor refused to write (stale read, version conflict, or
        # write failure). Surface the recovery as a blocked, no-write outcome
        # so the audit trail and the caller never see a half-applied recovery.
        result = RecoveryExecutionResult(
            proposal=proposal,
            outcome=RecoveryOutcome.BLOCKED_NO_LINKAGE,
            reason_code=RECOVERY_REASON_STALE_RECOVERY,
            executed_at=None,
            new_versions={},
        )
        _record_execute(audit_trail, proposal, result, timestamp)
        log.info(
            "recovery blocked correlation_id=%s decision_id=%s recovery_id=%s reason=executor_no_write",
            proposal.correlation_id,
            proposal.original_decision_id,
            proposal.recovery_id,
        )
        return result
    result = RecoveryExecutionResult(
        proposal=proposal,
        outcome=RecoveryOutcome.EXECUTED,
        reason_code=RECOVERY_REASON_EXECUTED,
        executed_at=timestamp,
        new_versions=dict(new_versions),
    )
    _record_execute(audit_trail, proposal, result, timestamp)
    log.info(
        "recovery executed correlation_id=%s decision_id=%s recovery_id=%s skus=%s",
        proposal.correlation_id,
        proposal.original_decision_id,
        proposal.recovery_id,
        ",".join(sorted(new_versions)),
    )
    return result


def _record_propose(audit_trail: RecoveryAuditSink, proposal: RecoveryProposal) -> None:
    audit_trail.record(
        RecoveryAuditEvent(
            stage="propose",
            correlation_id=proposal.correlation_id,
            original_decision_id=proposal.original_decision_id,
            recovery_id=proposal.recovery_id,
            attempt=proposal.attempt,
            outcome=proposal.outcome,
            reason_code=proposal.reason_code,
            inverse_kind=proposal.inverse_action.kind,
            inverse_sku=proposal.inverse_action.sku,
            at=proposal.freshness_at,
        )
    )


def _record_execute(
    audit_trail: RecoveryAuditSink,
    proposal: RecoveryProposal,
    result: RecoveryExecutionResult,
    timestamp: datetime,
) -> None:
    audit_trail.record(
        RecoveryAuditEvent(
            stage="execute",
            correlation_id=proposal.correlation_id,
            original_decision_id=proposal.original_decision_id,
            recovery_id=proposal.recovery_id,
            attempt=proposal.attempt,
            outcome=result.outcome,
            reason_code=result.reason_code,
            inverse_kind=proposal.inverse_action.kind,
            inverse_sku=proposal.inverse_action.sku,
            at=timestamp,
        )
    )


def _inverse_decision(proposal: RecoveryProposal, timestamp: datetime) -> Decision:
    """Build a synthetic Decision that the DCG can authorize.

    The inverse ``ActionUnion`` is shaped so the existing DCG can evaluate
    the live state. For ``change_facings`` and ``move_product`` the inverse
    is a regular action that mirrors what the recovery will do. For
    ``deplete_shelf`` the inverse is reported to the DCG as a
    ``ReplenishShelf`` of the same magnitude, with the awareness that the
    recovery executor applies ``deplete_shelf`` semantics; the DCG is
    expected to allow it as long as the backroom has at least that many
    units, which is the conservative precondition for a recovery that
    will only reduce the shelf. The synthetic decision carries the
    original correlation id and the proposal's ``recovery_id``.
    """
    inverse = proposal.inverse_action
    forward = _to_forward_action(inverse)
    evidence = EvidenceBundle(
        bundle_id=f"{proposal.recovery_id}:evidence",
        provenance="recovery-policy",
        source="recovery",
        entity_versions={sku: str(version) for sku, version in proposal.required_versions.items()},
        collected_at=timestamp,
        freshness=timestamp,
        store_id=proposal.store_id,
        correlation_id=proposal.correlation_id,
        is_sufficient=True,
    )
    return Decision(
        decision_id=proposal.recovery_id,
        agent_id="recovery-policy",
        context_version=f"recovery:{proposal.correlation_id}",
        context_timestamp=timestamp,
        evidence=[evidence],
        proposed_actions=[forward],
        simulation_id=None,
        expected_impact=ExpectedImpact(kpi_score=-1.0, description="automatic recovery"),
    )


def _to_forward_action(inverse: InverseAction) -> ActionUnion:
    """Map an ``InverseAction`` to a regular ``ActionUnion`` for DCG evaluation."""
    if inverse.kind == "deplete_shelf":
        assert inverse.quantity is not None
        return ReplenishShelf(sku=inverse.sku, quantity=inverse.quantity)
    if inverse.kind == "change_facings":
        assert inverse.facings is not None
        return ChangeFacings(sku=inverse.sku, facings=inverse.facings)
    if inverse.kind == "move_product":
        assert inverse.from_slot is not None and inverse.to_slot is not None
        return MoveProduct(sku=inverse.sku, from_slot=inverse.from_slot, to_slot=inverse.to_slot)
    raise ValueError(f"Unknown inverse action kind: {inverse.kind!r}")