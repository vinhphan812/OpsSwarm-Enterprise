"""Bounded automatic rollback after a verifier regression (issue #55, ADR 0039)."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from retailtwin_api.agents.executor.executor import InverseExecutor, _apply_inverse
from retailtwin_api.agents.executor.recovery import (
    AuthPipeline,
    InMemoryRecoveryAudit,
    InverseAction,
    RecoveryAuditEvent,
    RecoveryAuditSink,
    RecoveryConservationError,
    RecoveryExecutionResult,
    RecoveryExecutor,
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryProposal,
    RECOVERY_REASON_CONSERVATION,
    execute_recovery,
    propose_recovery,
    recovery_auto_enabled,
)
from retailtwin_api.agents.verifier.verify import (
    InMemoryVerificationAudit,
    VerificationReport,
    VerificationStatus,
)
from retailtwin_api.contracts import (
    ChangeFacings,
    DCGVerdict,
    DCGVerdictResult,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed
from retailtwin_api.guard.decision_context_guard import (
    DecisionContextGuard,
    InMemoryGuardAudit,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding
from retailtwin_api.schemas import ProductInventory

STORE = "store-001"
CORRELATION = "run-rollback-1"
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def twin() -> InMemoryTwinRepository:
    repo = InMemoryTwinRepository()
    repo.seed(
        STORE,
        "v3",
        [
            InventorySeed(
                sku="P001",
                shelf_id="SH1",
                slot_id="S1",
                facings=2,
                shelf_quantity=10,
                backroom_quantity=30,
            ),
            InventorySeed(
                sku="P002",
                shelf_id="SH1",
                slot_id="S2",
                facings=3,
                shelf_quantity=4,
                backroom_quantity=9,
            ),
        ],
    )
    return repo


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def guard_audit() -> InMemoryGuardAudit:
    return InMemoryGuardAudit()


@pytest.fixture
def gate(
    twin: InMemoryTwinRepository, guard_audit: InMemoryGuardAudit, clock: Clock
) -> NoStaleCommit:
    return NoStaleCommit(DecisionContextGuard(twin, clock=clock), guard_audit, clock=clock)


@pytest.fixture
def auth_pipeline(gate: NoStaleCommit) -> AuthPipeline:
    return gate


@pytest.fixture
def inverse_executor(twin: InMemoryTwinRepository, clock: Clock) -> InverseExecutor:
    return InverseExecutor(twin, STORE, clock=clock)


@pytest.fixture
def recovery_audit() -> InMemoryRecoveryAudit:
    return InMemoryRecoveryAudit()


def _decision(
    sku: str = "P001",
    actions: list | None = None,
    *,
    versions: dict[str, int] | None = None,
    correlation_id: str = CORRELATION,
    sufficient: bool = True,
) -> Decision:
    if actions is None:
        actions = [ReplenishShelf(sku=sku, quantity=6)]
    if versions is None:
        versions = {sku: 1}
    return Decision(
        decision_id="dec-1",
        agent_id="planner",
        context_version=f"{STORE}:v3",
        context_timestamp=T0,
        evidence=[
            EvidenceBundle(
                bundle_id="b1",
                provenance="tool-registry",
                source="investigator",
                entity_versions={sku: str(version) for sku, version in versions.items()},
                collected_at=T0,
                freshness=T0,
                store_id=STORE,
                correlation_id=correlation_id,
                is_sufficient=sufficient,
            )
        ],
        proposed_actions=list(actions),
        expected_impact=ExpectedImpact(kpi_score=-1.0, description="commit-only baseline"),
    )


def _baseline(sku: str = "P001", **overrides: int) -> dict[str, ProductInventory]:
    fields: dict[str, Any] = {
        "store_id": STORE,
        "sku": sku,
        "shelf_id": "SH1",
        "slot_id": "S1",
        "facings": 2,
        "shelf_quantity": 10,
        "backroom_quantity": 30,
        "version": 1,
    }
    fields.update(overrides)
    return {sku: ProductInventory.model_validate(fields)}


def _bump(twin: InMemoryTwinRepository, sku: str, **changes: Any) -> None:
    """Move ``sku`` to its next version with optional field overrides."""
    doc = twin.get_inventory(STORE, sku)
    assert doc is not None
    twin.upsert_inventory(
        doc.model_copy(update={"version": doc.version + 1, **changes}),
        expected_version=doc.version,
    )


def _report(
    decision: Decision,
    *,
    status: VerificationStatus,
    reason: str = "REGRESSION",
) -> VerificationReport:
    return VerificationReport(
        decision_id=decision.decision_id,
        correlation_id=decision.evidence[0].correlation_id,
        store_id=STORE,
        status=status,
        reason_code=reason,
        outcomes=[],
        checks=[],
    )


def _seed_linkage(
    audit: RecoveryAuditSink, decision: Decision, *, outcome: RecoveryOutcome = RecoveryOutcome.PROPOSED
) -> None:
    """Record the original execution on the recovery audit sink.

    The recovery policy uses the sink to prove the original decision reached
    execution; tests can shortcut this by recording a ``propose`` event
    against the decision id.
    """
    audit.record(
        RecoveryAuditEvent(
            stage="propose",
            correlation_id=decision.evidence[0].correlation_id,
            original_decision_id=decision.decision_id,
            recovery_id=f"recovery:{decision.decision_id}:r0",
            attempt=0,
            outcome=outcome,
            reason_code="seeded",
            inverse_kind="change_facings",
            inverse_sku="P001",
            at=T0,
        )
    )


# ─── Proposal rules ──────────────────────────────────────────────────────────


def test_recovery_proposes_inverse_on_regression(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """A regression on ``replenish_shelf`` proposes a ``deplete_shelf`` inverse."""
    decision = _decision(actions=[ReplenishShelf(sku="P001", quantity=6)])
    report = _report(decision, status=VerificationStatus.REGRESSION, reason="STATE_MISMATCH")
    _seed_linkage(recovery_audit, decision)

    # Simulate the original commit: P001 advanced to version 2.
    _bump(inverse_executor._twin, "P001")  # type: ignore[attr-defined]

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        policy=RecoveryPolicy(),
        enabled=True,
    )

    assert proposal.outcome is RecoveryOutcome.PROPOSED
    assert proposal.correlation_id == CORRELATION
    assert proposal.original_decision_id == "dec-1"
    assert proposal.inverse_action.kind == "deplete_shelf"
    assert proposal.inverse_action.sku == "P001"
    assert proposal.inverse_action.quantity == 6
    assert proposal.required_versions == {"P001": 2}

    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )
    assert result.outcome is RecoveryOutcome.EXECUTED
    assert result.new_versions == {"P001": 3}


def test_recovery_skips_on_verified(recovery_audit: InMemoryRecoveryAudit) -> None:
    """``VERIFIED`` reports do not trigger an automatic recovery."""
    decision = _decision()
    report = _report(decision, status=VerificationStatus.VERIFIED, reason="VERIFIED")

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 1},
        enabled=True,
    )

    assert proposal.outcome is RecoveryOutcome.HUMAN_REVIEW_REQUIRED
    assert proposal.reason_code == "verified"


def test_recovery_disabled_when_feature_flag_off(recovery_audit: InMemoryRecoveryAudit) -> None:
    """The ``RECOVERY_AUTO_ENABLED`` flag gates the policy at False until G06."""
    decision = _decision()
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=False,
    )

    assert proposal.outcome is RecoveryOutcome.HUMAN_REVIEW_REQUIRED
    assert proposal.reason_code == "feature_disabled"
    assert recovery_auto_enabled(environ={}) is False
    assert recovery_auto_enabled(environ={"RECOVERY_AUTO_ENABLED": "true"}) is True


def test_recovery_caps_max_attempts(recovery_audit: InMemoryRecoveryAudit) -> None:
    """A second attempt is refused when ``max_attempts`` is 1."""
    decision = _decision()
    report = _report(decision, status=VerificationStatus.REGRESSION)
    _seed_linkage(recovery_audit, decision)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        policy=RecoveryPolicy(max_attempts=1),
        attempt=1,
        enabled=True,
    )

    assert proposal.outcome is RecoveryOutcome.BLOCKED_BUDGET_EXHAUSTED
    assert proposal.reason_code == "budget_exhausted"


def test_recovery_blocks_when_linkage_missing(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """A proposal whose decision is not in the trail is blocked at propose time."""
    decision = _decision()
    report = _report(decision, status=VerificationStatus.REGRESSION)
    # No seeded linkage: audit trail is empty.

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )

    assert proposal.outcome is RecoveryOutcome.BLOCKED_NO_LINKAGE
    assert proposal.reason_code == "linkage_missing"


def test_recovery_links_to_original_decision(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """Audit events share the original ``correlation_id`` and decision id."""
    decision = _decision()
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    _bump(inverse_executor._twin, "P001")  # type: ignore[attr-defined]

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )
    execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )

    # The seeded linkage event is recorded separately; the proposal and
    # execution events share the recovery id and correlation id.
    events = [e for e in recovery_audit.events() if e.recovery_id == "recovery:dec-1:r1"]
    assert [event.stage for event in events] == ["propose", "execute"]
    assert all(event.correlation_id == CORRELATION for event in events)
    assert all(event.original_decision_id == "dec-1" for event in events)


# ─── Execution gates ─────────────────────────────────────────────────────────


class _FixedAuthPipeline:
    """A test double that returns a configurable guard result."""

    def __init__(self, *, allow: bool, entity_versions: dict[str, int]) -> None:
        self._allow = allow
        self._versions = entity_versions

    def authorize(self, decision: Decision) -> tuple[DCGVerdictResult, CommitBinding | None]:
        if not self._allow:
            return (
                DCGVerdictResult(
                    verdict=DCGVerdict.DENY,
                    reason_code="DCG_DENY",
                    context_version=decision.context_version,
                    context_hash="h",
                    expiry=T0,
                    policy_result={"failed_gate": "policy", "checks": [], "store_id": "", "correlation_id": "", "entity_versions": {}},
                ),
                None,
            )
        return (
            DCGVerdictResult(
                verdict=DCGVerdict.ALLOW,
                reason_code="ALLOWED",
                context_version=decision.context_version,
                context_hash="h",
                expiry=T0,
                policy_result={
                    "failed_gate": None,
                    "checks": [],
                    "store_id": STORE,
                    "correlation_id": CORRELATION,
                    "entity_versions": {sku: str(v) for sku, v in self._versions.items()},
                },
            ),
            CommitBinding(
                decision_id=decision.decision_id,
                store_id=STORE,
                context_hash="h",
                entity_versions=dict(self._versions),
                expiry=T0 + timedelta(seconds=60),
            ),
        )


def test_recovery_blocks_on_stale_context(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """If the live version moved between proposal and execution, the recovery is refused."""
    decision = _decision()
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )

    # The binding the auth pipeline produces reports a newer live version.
    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 5}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )

    assert result.outcome is RecoveryOutcome.BLOCKED_NO_LINKAGE
    assert result.reason_code == "stale_recovery"
    assert result.new_versions == {}


def test_recovery_blocks_on_dcg_denied(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """A DCG ``DENY`` returns a blocked result and does not write the Live Twin."""
    decision = _decision()
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )

    before = inverse_executor._twin.get_inventory(STORE, "P001")  # type: ignore[attr-defined]
    assert before is not None

    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=False, entity_versions={}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )

    assert result.outcome is RecoveryOutcome.BLOCKED_NO_LINKAGE
    assert result.reason_code == "DCG_DENY"
    after = inverse_executor._twin.get_inventory(STORE, "P001")  # type: ignore[attr-defined]
    assert after is not None and after.version == before.version


# ─── Audit trail ─────────────────────────────────────────────────────────────


def test_recovery_emits_audit_trail(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """Both ``propose`` and ``execute`` write one event each, sharing correlation id."""
    decision = _decision(actions=[ChangeFacings(sku="P001", facings=4)])
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION, reason="STATE_MISMATCH")

    _bump(inverse_executor._twin, "P001")  # type: ignore[attr-defined]

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )
    assert proposal.outcome is RecoveryOutcome.PROPOSED
    assert proposal.inverse_action.kind == "change_facings"
    assert proposal.inverse_action.facings == 2  # restored from baseline

    execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )

    events = [e for e in recovery_audit.events() if e.recovery_id == "recovery:dec-1:r1"]
    assert len(events) == 2
    propose_event, execute_event = events
    assert propose_event.stage == "propose"
    assert propose_event.outcome is RecoveryOutcome.PROPOSED
    assert execute_event.stage == "execute"
    assert execute_event.outcome is RecoveryOutcome.EXECUTED
    assert execute_event.reason_code == "executed"
    assert execute_event.correlation_id == CORRELATION
    assert execute_event.original_decision_id == "dec-1"
    assert execute_event.inverse_kind == "change_facings"


def test_recovery_uses_real_guard_for_auth(
    recovery_audit: InMemoryRecoveryAudit,
    inverse_executor: InverseExecutor,
    gate: NoStaleCommit,
) -> None:
    """The wired entry-point goes through ``NoStaleCommit.authorize``."""
    decision = _decision()
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 1},
        enabled=True,
    )
    result = execute_recovery(
        proposal,
        auth_pipeline=gate,
        executor=inverse_executor,
        audit_trail=recovery_audit,
        now=T0,
    )
    assert result.outcome is RecoveryOutcome.EXECUTED
    assert result.new_versions == {"P001": 2}


def test_recovery_handles_move_inverse(
    recovery_audit: InMemoryRecoveryAudit, inverse_executor: InverseExecutor
) -> None:
    """``move_product`` is recovered by swapping the slots back."""
    decision = _decision(actions=[MoveProduct(sku="P001", from_slot="S1", to_slot="S9")])
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )
    assert proposal.outcome is RecoveryOutcome.PROPOSED
    assert proposal.inverse_action.kind == "move_product"
    assert proposal.inverse_action.from_slot == "S9"  # where it currently is
    assert proposal.inverse_action.to_slot == "S1"    # where it came from

    # Place the SKU at S9 so the inverse move is feasible.
    twin = inverse_executor._twin  # type: ignore[attr-defined]
    current = twin.get_inventory(STORE, "P001")
    assert current is not None
    twin.upsert_inventory(current.model_copy(update={"slot_id": "S9", "version": 2}), expected_version=1)

    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=inverse_executor,
        audit_trail=recovery_audit,
    )
    assert result.outcome is RecoveryOutcome.EXECUTED
    final = twin.get_inventory(STORE, "P001")
    assert final is not None and final.slot_id == "S1"


def test_recovery_proposes_inverse_for_change_facings(
    recovery_audit: InMemoryRecoveryAudit,
) -> None:
    """``change_facings`` is recovered by restoring the baseline facings count."""
    decision = _decision(actions=[ChangeFacings(sku="P001", facings=8)])
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(facings=4),
        current_versions={"P001": 2},
        enabled=True,
    )
    assert proposal.outcome is RecoveryOutcome.PROPOSED
    assert proposal.inverse_action.kind == "change_facings"
    assert proposal.inverse_action.facings == 4  # baseline value


def test_recovery_disabled_does_not_block_proposal_construction(
    recovery_audit: InMemoryRecoveryAudit,
) -> None:
    """Even when the feature flag is off, the proposal is constructed and audited."""
    decision = _decision()
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 1},
        enabled=False,
    )
    events = recovery_audit.events()
    assert len(events) == 1
    assert events[0].outcome is RecoveryOutcome.HUMAN_REVIEW_REQUIRED
    assert events[0].reason_code == "feature_disabled"


def test_recovery_caps_max_attempts_via_env(
    recovery_audit: InMemoryRecoveryAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``RETAILTWIN_RECOVERY_MAX_ATTEMPTS`` controls the budget."""
    monkeypatch.setenv("RETAILTWIN_RECOVERY_MAX_ATTEMPTS", "3")
    from retailtwin_api.agents.executor.recovery import max_attempts_from_env

    assert max_attempts_from_env() == 3

    monkeypatch.delenv("RETAILTWIN_RECOVERY_MAX_ATTEMPTS", raising=False)
    assert max_attempts_from_env() == 1


# ─── Inventory conservation (CHANGES_REQUESTED on PR #251) ─────────────────


def test_inverse_rejects_when_shelf_too_low(
    twin: InMemoryTwinRepository, clock: Clock
) -> None:
    """``deplete_shelf`` is refused when intervening sales have drained the shelf.

    The original action replenished 6 units; the inverse must remove 6. The
    shelf currently holds 4 because intervening sales drew 6 units away. The
    bug (CHANGES_REQUESTED on PR #251) clamped the shelf subtraction to zero
    while still crediting the full 6 to the backroom, breaking conservation.
    The fix raises :class:`RecoveryConservationError` before any write and
    leaves the Live Twin untouched.
    """
    # Move P001 to a known live state: shelf 4, backroom 30, version 2.
    doc = twin.get_inventory(STORE, "P001")
    assert doc is not None
    twin.upsert_inventory(
        doc.model_copy(update={"shelf_quantity": 4, "backroom_quantity": 30, "version": 2}),
        expected_version=doc.version,
    )
    original_doc = twin.get_inventory(STORE, "P001")
    assert original_doc is not None

    inverse = InverseAction(kind="deplete_shelf", sku="P001", quantity=6)
    with pytest.raises(RecoveryConservationError) as exc_info:
        _apply_inverse(inverse, {inverse.sku: original_doc}, clock())

    err = exc_info.value
    assert err.sku == "P001"
    assert err.kind == "deplete_shelf"
    assert err.reason == "shelf_underflow"
    assert err.required == 6
    assert err.available == 4

    # The Live Twin is untouched: no partial subtraction, no backroom credit.
    after = twin.get_inventory(STORE, "P001")
    assert after is not None
    assert after.shelf_quantity == original_doc.shelf_quantity
    assert after.backroom_quantity == original_doc.backroom_quantity
    assert after.version == original_doc.version


def test_inverse_rejects_when_backroom_too_high(
    twin: InMemoryTwinRepository, clock: Clock
) -> None:
    """``deplete_shelf`` is refused when the backroom is already at capacity.

    The original ``replenish_shelf`` moved 6 units from backroom to shelf. The
    inverse must move them back. If intervening deliveries (or any other
    writes) have pushed the backroom to its declared capacity, the inverse
    would overflow. The recovery commit port refuses the inverse under the
    same No-Stale-Commit path that the rest of #55 uses.
    """
    # Seed P001 with a backroom capacity of 30, then bump the backroom to
    # that capacity and the shelf to a value that would let the inverse
    # otherwise apply. Version is bumped to 2 to mirror a post-commit state.
    doc = twin.get_inventory(STORE, "P001")
    assert doc is not None
    twin.upsert_inventory(
        doc.model_copy(
            update={
                "shelf_quantity": 10,
                "backroom_quantity": 30,
                "backroom_capacity": 30,
                "version": 2,
            }
        ),
        expected_version=doc.version,
    )
    original_doc = twin.get_inventory(STORE, "P001")
    assert original_doc is not None
    assert original_doc.backroom_capacity == 30

    inverse = InverseAction(kind="deplete_shelf", sku="P001", quantity=6)
    with pytest.raises(RecoveryConservationError) as exc_info:
        _apply_inverse(inverse, {inverse.sku: original_doc}, clock())

    err = exc_info.value
    assert err.sku == "P001"
    assert err.kind == "deplete_shelf"
    assert err.reason == "backroom_overflow"
    assert err.required == 36  # 30 current + 6 inverse
    assert err.available == 30  # backroom capacity

    after = twin.get_inventory(STORE, "P001")
    assert after is not None
    assert after.shelf_quantity == original_doc.shelf_quantity
    assert after.backroom_quantity == original_doc.backroom_quantity
    assert after.version == original_doc.version


def test_inverse_atomic_under_concurrent_sale(
    twin: InMemoryTwinRepository, clock: Clock, recovery_audit: InMemoryRecoveryAudit
) -> None:
    """A concurrent sale that drains the shelf makes the recovery fail closed.

    Scenario:

    * The Verifier accepted the original ``replenish_shelf`` of 6 units; P001
      advanced to version 2 and the proposal binds to that version.
    * Before the recovery executes, a sale lands on the Live Twin: P001's
      shelf drops to 4 and the document advances to version 3.
    * The recovery is dispatched with ``required_versions={P001: 2}`` (the
      version the proposal recorded). The InverseExecutor re-reads the live
      state, sees the version has moved, and refuses to write.
    * ``execute_recovery`` reports the recovery as a no-op: the Live Twin
      is unchanged and the audit trail carries a ``BLOCKED_NO_LINKAGE``
      outcome with reason ``stale_recovery``.
    """
    # Advance P001 to version 2 (post-commit baseline).
    _bump(twin, "P001")

    # Concurrent sale: shelf drained, version bumped to 3.
    doc = twin.get_inventory(STORE, "P001")
    assert doc is not None
    twin.upsert_inventory(
        doc.model_copy(update={"shelf_quantity": 4, "version": doc.version + 1}),
        expected_version=doc.version,
    )
    sold_doc = twin.get_inventory(STORE, "P001")
    assert sold_doc is not None
    assert sold_doc.shelf_quantity == 4
    assert sold_doc.version == 3

    decision = _decision(actions=[ReplenishShelf(sku="P001", quantity=6)])
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},  # stale: the live version is 3
        enabled=True,
    )
    assert proposal.outcome is RecoveryOutcome.PROPOSED

    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=InverseExecutor(twin, STORE, clock=clock),
        audit_trail=recovery_audit,
    )

    # The recovery is refused without touching the Live Twin: the version
    # check fires before _apply_inverse is even reached.
    assert result.outcome is RecoveryOutcome.BLOCKED_NO_LINKAGE
    assert result.reason_code == "stale_recovery"
    assert result.new_versions == {}

    final = twin.get_inventory(STORE, "P001")
    assert final is not None
    assert final.shelf_quantity == 4
    assert final.backroom_quantity == 30
    assert final.version == 3


def test_inverse_succeeds_on_fresh_context(
    twin: InMemoryTwinRepository, clock: Clock, recovery_audit: InMemoryRecoveryAudit
) -> None:
    """The happy path applies the inverse through the same No-Stale-Commit read.

    When the live shelf and backroom still support the inverse quantity, the
    recovery commit port rewrites the SKU with the original ``correlation_id``
    and the post-write version. The audit trail records a single
    ``EXECUTED`` outcome paired with the original decision's correlation id.
    """
    # The recovery executor is called with the version the proposal bound.
    _bump(twin, "P001")
    doc = twin.get_inventory(STORE, "P001")
    assert doc is not None
    assert doc.version == 2
    assert doc.shelf_quantity == 10
    assert doc.backroom_quantity == 30

    decision = _decision(actions=[ReplenishShelf(sku="P001", quantity=6)])
    _seed_linkage(recovery_audit, decision)
    report = _report(decision, status=VerificationStatus.REGRESSION)

    proposal = propose_recovery(
        decision,
        report,
        recovery_audit,
        baseline=_baseline(),
        current_versions={"P001": 2},
        enabled=True,
    )
    assert proposal.outcome is RecoveryOutcome.PROPOSED

    result = execute_recovery(
        proposal,
        auth_pipeline=_FixedAuthPipeline(allow=True, entity_versions={"P001": 2}),
        executor=InverseExecutor(twin, STORE, clock=clock),
        audit_trail=recovery_audit,
    )

    assert result.outcome is RecoveryOutcome.EXECUTED
    assert result.reason_code == "executed"
    assert result.new_versions == {"P001": 3}

    final = twin.get_inventory(STORE, "P001")
    assert final is not None
    assert final.shelf_quantity == 4
    assert final.backroom_quantity == 36
    assert final.version == 3