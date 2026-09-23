# Focused tests for RunState transition validation
import pytest

from opsswarm.models import (
    RunState, RunRecord, VALID_TRANSITIONS, TERMINAL_STATES, InvalidStateTransition
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

    def test_resolved_is_terminal(self):
        assert RunState.RESOLVED in TERMINAL_STATES

    def test_failed_is_terminal(self):
        assert RunState.FAILED in TERMINAL_STATES

    def test_aborted_is_terminal(self):
        assert RunState.ABORTED in TERMINAL_STATES

    def test_no_transitions_from_resolved(self):
        assert VALID_TRANSITIONS[RunState.RESOLVED] == set()

    def test_no_transitions_from_aborted(self):
        assert VALID_TRANSITIONS[RunState.ABORTED] == set()


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
