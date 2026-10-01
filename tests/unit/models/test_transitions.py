# Focused tests for RunState transition validation
import pytest

from opsswarm.models import (
    RunState,
    RunRecord,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    InvalidStateTransition,
)


class TestValidTransitions:
    """Test the VALID_TRANSITIONS table matches expected workflow."""

    def test_open_to_triage(self):
        assert RunState.TRIAGE in VALID_TRANSITIONS[RunState.OPEN]

    def test_triage_to_investigating(self):
        assert RunState.INVESTIGATING in VALID_TRANSITIONS[RunState.TRIAGE]

    def test_investigating_to_diagnosed(self):
        assert RunState.DIAGNOSED in VALID_TRANSITIONS[RunState.INVESTIGATING]

    def test_diagnosed_to_planning(self):
        assert RunState.PLANNING in VALID_TRANSITIONS[RunState.DIAGNOSED]

    def test_planning_can_go_to_executing(self):
        assert RunState.EXECUTING in VALID_TRANSITIONS[RunState.PLANNING]

    def test_planning_can_go_to_waiting_approval(self):
        assert RunState.WAITING_APPROVAL in VALID_TRANSITIONS[RunState.PLANNING]

    def test_executing_to_verifying(self):
        assert RunState.VERIFYING in VALID_TRANSITIONS[RunState.EXECUTING]

    def test_verifying_to_resolved(self):
        assert RunState.RESOLVED in VALID_TRANSITIONS[RunState.VERIFYING]


class TestTerminalStates:
    """Test terminal states have no outgoing transitions."""

    def test_failed_is_terminal(self):
        assert RunState.FAILED in TERMINAL_STATES

    def test_aborted_is_terminal(self):
        assert RunState.ABORTED in TERMINAL_STATES

    def test_plan_rca_resolved_is_terminal(self):
        """ADR-015: PLAN_RCA_RESOLVED is the terminal state after Phase-2 RCA completes."""
        assert RunState.PLAN_RCA_RESOLVED in TERMINAL_STATES

    def test_plan_rca_resolved_has_no_outgoing_transitions(self):
        """ADR-015: PLAN_RCA_RESOLVED is a sink state."""
        assert VALID_TRANSITIONS[RunState.PLAN_RCA_RESOLVED] == set()


class TestPlanRcaTransitions:
    """ADR-015: two-phase plan — PLAN_RCA and PLAN_RCA_RESOLVED transitions."""

    def test_resolved_allows_plan_rca(self):
        """ADR-015: After verification, RESOLVED may transition to PLAN_RCA (Phase 2)."""
        assert RunState.PLAN_RCA in VALID_TRANSITIONS[RunState.RESOLVED]

    def test_resolved_allows_skip_rca(self):
        """ADR-015: RCA may be skipped via PLAN_RCA_RESOLVED when rca_enabled=false."""
        assert RunState.PLAN_RCA_RESOLVED in VALID_TRANSITIONS[RunState.RESOLVED]

    def test_plan_rca_transitions_to_rca_resolved(self):
        """ADR-015: PLAN_RCA progresses to PLAN_RCA_RESOLVED on successful synthesis."""
        assert RunState.PLAN_RCA_RESOLVED in VALID_TRANSITIONS[RunState.PLAN_RCA]

    def test_plan_rca_may_abort(self):
        """ADR-015: PLAN_RCA may be abandoned if budget is exhausted or RCA is not feasible."""
        assert RunState.ABORTED in VALID_TRANSITIONS[RunState.PLAN_RCA]

    def test_resolved_is_not_in_terminal_states(self):
        """ADR-015: RESOLVED alone is not terminal — PLAN_RCA is a valid exit path."""
        assert RunState.RESOLVED not in TERMINAL_STATES


class TestInvalidTransitions:
    """Test invalid transitions are properly detected."""

    def test_cannot_skip_to_resolved(self):
        """TRIAGE -> RESOLVED is not allowed."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        assert not run.can_transition_to(RunState.RESOLVED)

    def test_cannot_skip_to_verifying(self):
        """PLANNING -> VERIFYING is not allowed."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.PLANNING)
        assert not run.can_transition_to(RunState.VERIFYING)

    def test_cannot_go_back_to_open(self):
        """No state can transition back to OPEN."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        assert not run.can_transition_to(RunState.OPEN)


class TestRunRecordTransition:
    """Test RunRecord.transition() method behavior."""

    def test_valid_transition_audit_mode(self):
        """Valid transition should succeed in audit mode."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        run.transition(RunState.INVESTIGATING, enforcement="audit")
        assert run.state == RunState.INVESTIGATING

    def test_valid_transition_strict_mode(self):
        """Valid transition should succeed in strict mode."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        run.transition(RunState.INVESTIGATING, enforcement="strict")
        assert run.state == RunState.INVESTIGATING

    def test_invalid_transition_audit_mode_logs_warning(self, caplog):
        """Invalid transition should log warning in audit mode but allow."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        run.transition(RunState.RESOLVED, enforcement="audit")
        # In audit mode, transition is allowed but logged
        assert run.state == RunState.RESOLVED
        assert any("AUDIT" in record.message for record in caplog.records)

    def test_invalid_transition_strict_mode_raises(self):
        """Invalid transition should raise InvalidStateTransition in strict mode."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        with pytest.raises(InvalidStateTransition) as exc_info:
            run.transition(RunState.RESOLVED, enforcement="strict")
        assert exc_info.value.from_state == RunState.TRIAGE
        assert exc_info.value.to_state == RunState.RESOLVED

    def test_disabled_mode_allows_any_transition(self):
        """Disabled mode should skip validation entirely."""
        run = RunRecord(run_id="test", issue_number=1, state=RunState.TRIAGE)
        run.transition(RunState.RESOLVED, enforcement="disabled")
        assert run.state == RunState.RESOLVED


class TestS7Veto:
    """Test S7 veto capability in VerificationResult."""

    def test_verification_result_abort_field_exists(self):
        """VerificationResult should have abort field."""
        from opsswarm.models import VerificationResult

        vr = VerificationResult(verified=False, summary="test", abort=True)
        assert vr.abort is True
