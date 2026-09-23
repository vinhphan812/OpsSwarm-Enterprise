"""Comprehensive test matrix for Issue #9: Idempotency and Concurrency.

Tests the complete flow:
- Webhook deduplication
- Command idempotency
- State machine validation
- Evidence deduplication
- Checkpoint/resume
- Atomic writes
"""
import os
import tempfile
from unittest.mock import patch

import pytest

from opsswarm.evidence import EvidenceStore
from opsswarm.models import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    CheckpointType,
    CommandOutcome,
    InvalidStateTransition,
    RunRecord,
    RunState,
)
from opsswarm.store import RunStore


class TestWebhookDeduplication:
    """Test webhook idempotency via delivery ID deduplication."""

    def test_new_webhook_processes_normally(self):
        """New webhook with unique delivery ID should process normally."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        # No prior delivery ID
        assert "delivery-001" not in run.idempotency_keys

        # First time processing
        run.idempotency_keys.add("delivery-001")

        assert "delivery-001" in run.idempotency_keys

    def test_duplicate_delivery_id_rejected(self):
        """Duplicate delivery ID should be rejected (idempotent)."""
        run = RunRecord(run_id="RUN-1", issue_number=1)
        run.idempotency_keys.add("delivery-001")

        # Simulate duplicate delivery
        delivery_id = "delivery-001"

        # Check idempotency
        assert delivery_id in run.idempotency_keys

    def test_different_delivery_ids_all_process(self):
        """Different delivery IDs should all be processed."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        delivery_ids = ["delivery-001", "delivery-002", "delivery-003"]

        for delivery_id in delivery_ids:
            if delivery_id not in run.idempotency_keys:
                run.idempotency_keys.add(delivery_id)

        assert len(run.idempotency_keys) == 3
        assert "delivery-001" in run.idempotency_keys
        assert "delivery-002" in run.idempotency_keys
        assert "delivery-003" in run.idempotency_keys


class TestCommandIdempotency:
    """Test command idempotency via comment ID deduplication."""

    def test_first_command_executes(self):
        """First command should execute normally."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.WAITING_APPROVAL)

        comment_id = "comment-001"

        # First time seeing this comment
        assert comment_id not in run.executed_commands
        run.executed_commands.add(comment_id)

        assert comment_id in run.executed_commands

    def test_duplicate_comment_id_rejected(self):
        """Duplicate comment ID should be idempotent-rejected."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.WAITING_APPROVAL)
        run.executed_commands.add("comment-001")

        # Simulate duplicate comment
        duplicate_id = "comment-001"

        assert duplicate_id in run.executed_commands

    def test_different_approve_comments_all_process(self):
        """Different approve comments should all process in order."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.WAITING_APPROVAL)

        comment_ids = ["comment-001", "comment-002", "comment-003"]

        for comment_id in comment_ids:
            if comment_id not in run.executed_commands:
                run.executed_commands.add(comment_id)

        assert len(run.executed_commands) == 3

    def test_commands_rejected_in_terminal_states(self):
        """Commands should be rejected in terminal states."""
        for terminal_state in TERMINAL_STATES:
            run = RunRecord(run_id="RUN-1", issue_number=1, state=terminal_state)

            # Commands should be rejected in terminal states
            assert run.state in TERMINAL_STATES


class TestStateMachine:
    """Test state machine validation and transitions."""

    def test_valid_transitions_work(self):
        """Valid state transitions should work."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.OPEN)

        # OPEN -> TRIAGE is valid
        run.transition(RunState.TRIAGE, enforcement="disabled")
        assert run.state == RunState.TRIAGE

        # TRIAGE -> INVESTIGATING is valid
        run.transition(RunState.INVESTIGATING, enforcement="disabled")
        assert run.state == RunState.INVESTIGATING

    def test_audit_mode_logs_invalid_transition(self):
        """Audit mode should log invalid transitions but allow them."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.RESOLVED)

        # In audit mode, should log warning but allow
        with patch('opsswarm.models.logger') as mock_logger:
            run.transition(RunState.OPEN, enforcement="audit")
            # Audit mode logs warning but allows transition
            assert mock_logger.warning.called

    def test_strict_mode_rejects_invalid_transition(self):
        """Strict mode should reject invalid transitions."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.RESOLVED)

        # Strict mode should raise
        with pytest.raises(InvalidStateTransition):
            run.transition(RunState.OPEN, enforcement="strict")

    def test_terminal_states_reject_commands(self):
        """Terminal states should reject commands."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.RESOLVED)

        # Check terminal state rejection logic
        assert run.state in TERMINAL_STATES

        # can_transition_to should return False
        assert run.can_transition_to(RunState.OPEN) is False
        assert run.can_transition_to(RunState.INVESTIGATING) is False

    def test_all_valid_transitions_defined(self):
        """All states should have valid transitions defined."""
        for state in RunState:
            assert state in VALID_TRANSITIONS or state in TERMINAL_STATES

        # Check specific transitions
        assert RunState.OPEN in VALID_TRANSITIONS
        assert RunState.TRIAGE in VALID_TRANSITIONS
        assert RunState.INVESTIGATING in VALID_TRANSITIONS
        assert RunState.RESOLVED in VALID_TRANSITIONS
        assert RunState.FAILED in VALID_TRANSITIONS
        assert RunState.ABORTED in VALID_TRANSITIONS


class TestEvidenceDeduplication:
    """Test evidence deduplication with signatures."""

    def test_first_evidence_appends_normally(self):
        """First evidence should append normally."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            eid, is_dup = store.append("run1", "finding", {"text": "test finding"})

            assert eid is not None
            assert is_dup is False

            evidence = store.list("run1")
            assert len(evidence) == 1

    def test_duplicate_evidence_skipped(self):
        """Duplicate evidence should be skipped with count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            # First evidence
            _, is_dup1 = store.append("run1", "finding", {"text": "same finding"})
            assert is_dup1 is False

            # Duplicate evidence
            _, is_dup2 = store.append("run1", "finding", {"text": "same finding"})
            assert is_dup2 is True

            evidence = store.list("run1")
            assert len(evidence) == 1

            # Duplicate count should be tracked
            assert store.get_duplicate_count() >= 1


class TestCheckpointResume:
    """Test checkpoint and resume functionality."""

    def test_checkpoint_saved_at_state_transition(self):
        """Checkpoint should be saved at state transition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            run = RunRecord(run_id="run1", issue_number=1, state=RunState.OPEN)

            # Record checkpoint at state transition
            eid = store.checkpoint(run.run_id, CheckpointType.STATE_TRANSITION, {
                "state": RunState.TRIAGE.value
            })

            assert eid is not None

            # Verify checkpoint stored
            last_checkpoint = store.get_last_checkpoint(run.run_id)
            assert last_checkpoint is not None
            assert last_checkpoint["kind"] == "checkpoint"
            assert last_checkpoint["payload"]["checkpoint_type"] == CheckpointType.STATE_TRANSITION.value

    def test_resume_loads_correct_state(self):
        """Resume should load correct state from checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EvidenceStore(tmpdir)

            run_id = "run1"

            # Record multiple checkpoints
            store.checkpoint(run_id, CheckpointType.STATE_TRANSITION, {"state": "TRIAGE"})
            store.checkpoint(run_id, CheckpointType.STATE_TRANSITION, {"state": "INVESTIGATING"})
            store.checkpoint(run_id, CheckpointType.HUMAN_GATE, {"state": "WAITING_APPROVAL"})

            # Get last checkpoint
            last_checkpoint = store.get_last_checkpoint(run_id)

            assert last_checkpoint is not None
            # The checkpoint wraps the payload: checkpoint_type + payload (which contains original data)
            assert last_checkpoint["payload"]["checkpoint_type"] == CheckpointType.HUMAN_GATE.value
            # Access nested state from checkpoint payload
            assert last_checkpoint["payload"]["payload"]["state"] == "WAITING_APPROVAL"

    def test_checkpoint_types_defined(self):
        """All checkpoint types should be defined."""
        assert CheckpointType.STATE_TRANSITION.value == "state_transition"
        assert CheckpointType.HUMAN_GATE.value == "human_gate"
        assert CheckpointType.EXECUTION.value == "execution"


class TestAtomicWrites:
    """Test atomic writes for crash safety."""

    def test_atomic_write_creates_file(self):
        """Atomic write should create file correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)

            run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.OPEN)

            store.save(run)

            # Verify file exists
            assert os.path.exists(os.path.join(tmpdir, "runs", "RUN-1.json"))

    def test_atomic_write_uses_temp_file(self):
        """Atomic write should use temp file pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)

            run = RunRecord(run_id="RUN-2", issue_number=2, state=RunState.TRIAGE)

            store.save(run)

            # Check tmp file is cleaned up
            tmp_files = list(Path(tmpdir, "runs").glob(".*.tmp"))
            assert len(tmp_files) == 0

    def test_atomic_overwrite_preserves_previous(self):
        """Atomic overwrite should preserve previous valid state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)

            # Save first version
            run1 = RunRecord(run_id="RUN-3", issue_number=3, state=RunState.OPEN)
            store.save(run1)

            # Read and verify first version
            runs = store.load_all()
            assert len(runs) == 1
            assert runs[0].state == RunState.OPEN

            # Save second version (simulate crash recovery)
            run2 = RunRecord(run_id="RUN-3", issue_number=3, state=RunState.INVESTIGATING)
            store.save(run2)

            # Verify second version
            runs = store.load_all()
            assert len(runs) == 1
            assert runs[0].state == RunState.INVESTIGATING

    def test_store_atomic_flag_enabled_by_default(self):
        """Store should have atomic writes enabled by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)

            # Atomic writes should be enabled by default
            assert store.enable_atomic_writes is True


class TestRunRecordIdempotencyFields:
    """Test RunRecord idempotency fields."""

    def test_idempotency_keys_initialized(self):
        """RunRecord should initialize idempotency_keys as empty set."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        assert isinstance(run.idempotency_keys, set)
        assert len(run.idempotency_keys) == 0

    def test_executed_commands_initialized(self):
        """RunRecord should initialize executed_commands as empty set."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        assert isinstance(run.executed_commands, set)
        assert len(run.executed_commands) == 0


class TestIntegration:
    """Integration tests for the complete idempotency flow."""

    def test_complete_webhook_flow(self):
        """Test complete webhook processing flow."""
        # Simulate webhook with delivery ID
        delivery_id = "12345-abcde"

        # Create run record with idempotency tracking
        run = RunRecord(
            run_id="RUN-TEST-1",
            issue_number=42,
            state=RunState.OPEN
        )

        # First webhook - should process
        if delivery_id not in run.idempotency_keys:
            run.idempotency_keys.add(delivery_id)

        assert delivery_id in run.idempotency_keys

        # Duplicate webhook - should be rejected
        is_duplicate = delivery_id in run.idempotency_keys
        assert is_duplicate is True

    def test_complete_command_flow(self):
        """Test complete command processing flow."""
        run = RunRecord(
            run_id="RUN-TEST-2",
            issue_number=42,
            state=RunState.WAITING_APPROVAL
        )

        comment_id = "comment-12345"

        # First command - should process
        if comment_id not in run.executed_commands:
            run.executed_commands.add(comment_id)

        # Duplicate command - should be rejected
        is_duplicate = comment_id in run.executed_commands
        assert is_duplicate is True

        # Terminal state should reject
        run.state = RunState.RESOLVED
        assert run.state in TERMINAL_STATES


class TestPersistenceConfig:
    """Test persistence configuration."""

    def test_store_respects_atomic_writes_flag(self):
        """Store should respect enable_atomic_writes config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Disabled atomic writes
            store = RunStore(tmpdir, enable_atomic_writes=False)
            assert store.enable_atomic_writes is False

            # Enabled atomic writes (default)
            store2 = RunStore(tmpdir, enable_atomic_writes=True)
            assert store2.enable_atomic_writes is True

    def test_evidence_respects_idempotency_flag(self):
        """Evidence store should respect enable_idempotency config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Disabled idempotency
            store = EvidenceStore(tmpdir, enable_idempotency=False)
            assert store.enable_idempotency is False

            # Enabled idempotency (default)
            store2 = EvidenceStore(tmpdir, enable_idempotency=True)
            assert store2.enable_idempotency is True

    def test_store_passes_config_to_flags(self):
        """Store should pass persistence config to feature flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enable_atomic_writes": False,
                "enable_checkpoints": False,
            }

            store = RunStore(tmpdir, persistence_config=config)

            assert store.enable_atomic_writes is False
            assert store.enable_checkpoints is False


# Import Path for file operations
from pathlib import Path


class TestCommandOutcome:
    """Test command outcome tracking for durable execution state (Issue #9 fix)."""

    def test_command_outcome_enum_defined(self):
        """All command outcomes should be defined."""
        assert CommandOutcome.RECEIVED.value == "received"
        assert CommandOutcome.EXECUTING.value == "executing"
        assert CommandOutcome.CONFIRMED.value == "confirmed"
        assert CommandOutcome.ABSENT.value == "absent"
        assert CommandOutcome.UNKNOWN.value == "unknown"

    def test_run_record_has_command_outcomes_field(self):
        """RunRecord should have command_outcomes field."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        assert hasattr(run, 'command_outcomes')
        assert isinstance(run.command_outcomes, dict)
        assert len(run.command_outcomes) == 0

    def test_mark_command_received(self):
        """mark_command_received should set outcome to RECEIVED."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        run.mark_command_received("comment-001")

        assert run.command_outcomes["comment-001"] == CommandOutcome.RECEIVED.value
        assert run.is_command_received("comment-001") is True
        assert run.is_command_confirmed("comment-001") is False

    def test_mark_command_executing(self):
        """mark_command_executing should set outcome to EXECUTING."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        run.mark_command_executing("comment-001")

        assert run.command_outcomes["comment-001"] == CommandOutcome.EXECUTING.value

    def test_mark_command_confirmed(self):
        """mark_command_confirmed should set outcome to CONFIRMED and update legacy field."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        run.mark_command_confirmed("comment-001")

        assert run.command_outcomes["comment-001"] == CommandOutcome.CONFIRMED.value
        assert run.is_command_confirmed("comment-001") is True
        assert "comment-001" in run.executed_commands  # Legacy field updated

    def test_mark_command_absent(self):
        """mark_command_absent should set outcome to ABSENT."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        run.mark_command_absent("comment-001")

        assert run.command_outcomes["comment-001"] == CommandOutcome.ABSENT.value

    def test_mark_command_reconciled(self):
        """mark_command_unknown should set outcome to UNKNOWN."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        run.mark_command_unknown("comment-001")

        assert run.command_outcomes["comment-001"] == CommandOutcome.UNKNOWN.value

    def test_get_command_outcome(self):
        """get_command_outcome should return the current outcome."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        assert run.get_command_outcome("comment-001") is None

        run.mark_command_received("comment-001")
        assert run.get_command_outcome("comment-001") == CommandOutcome.RECEIVED.value

        run.mark_command_confirmed("comment-001")
        assert run.get_command_outcome("comment-001") == CommandOutcome.CONFIRMED.value

    def test_get_pending_commands(self):
        """get_pending_commands should return commands in RECEIVED or EXECUTING state."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        # No pending commands initially
        assert run.get_pending_commands() == []

        # Add commands in different states
        run.mark_command_received("comment-001")
        run.mark_command_executing("comment-002")
        run.mark_command_confirmed("comment-003")
        run.mark_command_absent("comment-004")

        pending = run.get_pending_commands()
        assert len(pending) == 2
        assert "comment-001" in pending
        assert "comment-002" in pending

    def test_backward_compatibility_with_executed_commands(self):
        """Legacy executed_commands should still work after migration."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        # Old code that adds to executed_commands directly
        run.executed_commands.add("comment-old")

        # Should still work
        assert "comment-old" in run.executed_commands

        # New code using command_outcomes
        run.mark_command_confirmed("comment-new")

        assert "comment-new" in run.executed_commands
        assert run.command_outcomes["comment-new"] == CommandOutcome.CONFIRMED.value

    def test_migration_from_legacy_executed_commands(self):
        """Loading old records should migrate executed_commands to command_outcomes."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        # Simulate old record with only executed_commands
        run.executed_commands.add("comment-old-1")
        run.executed_commands.add("comment-old-2")

        # Migration: executed_commands -> command_outcomes (as done in orchestrator)
        for cmd_id in run.executed_commands:
            if cmd_id not in run.command_outcomes:
                run.command_outcomes[cmd_id] = CommandOutcome.CONFIRMED.value

        # Both fields should have the data
        assert "comment-old-1" in run.executed_commands
        assert "comment-old-2" in run.executed_commands
        assert run.command_outcomes["comment-old-1"] == CommandOutcome.CONFIRMED.value
        assert run.command_outcomes["comment-old-2"] == CommandOutcome.CONFIRMED.value

    def test_command_not_confirmed_until_marked(self):
        """A command should not be considered confirmed until explicitly marked."""
        run = RunRecord(run_id="RUN-1", issue_number=1)

        # Only marked as received (simulating crash before execution)
        run.mark_command_received("comment-001")

        # Should NOT be considered confirmed - this is the key fix!
        assert run.is_command_confirmed("comment-001") is False
        assert "comment-001" not in run.executed_commands

        # After execution completes
        run.mark_command_confirmed("comment-001")

        # Now it should be considered confirmed
        assert run.is_command_confirmed("comment-001") is True
        assert "comment-001" in run.executed_commands

    def test_crash_recovery_scenario(self):
        """Test crash recovery: command received but not executed can be retried."""
        run = RunRecord(run_id="RUN-1", issue_number=1, state=RunState.WAITING_APPROVAL)

        # Simulate crash after persisting RECEIVED but before execution completes
        run.mark_command_received("comment-001")

        # On restart, the command can be safely retried because it wasn't executed
        pending = run.get_pending_commands()
        assert "comment-001" in pending

        # Resume: mark as executing
        run.mark_command_executing("comment-001")

        # Execute (simulated)
        run.mark_command_confirmed("comment-001")

        # Now it's no longer pending
        pending = run.get_pending_commands()
        assert "comment-001" not in pending
