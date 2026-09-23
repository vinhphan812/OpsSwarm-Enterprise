"""Unit tests for opsswarm.reconciliation module."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from opsswarm.models import RunState
from opsswarm.reconciliation import ReconciliationManager, ReconciliationReport, RecoveryResult


@pytest.fixture
def manager(tmp_path):
    """Create a ReconciliationManager with temp directory."""
    data_dir = str(tmp_path / "data")
    return ReconciliationManager(data_dir)


class TestReconciliationManager:
    """Tests for ReconciliationManager class."""

    def test_init(self, manager):
        """Manager initializes correctly."""
        assert manager.data_dir is not None
        assert manager.store is not None
        assert manager.evidence is not None


class TestReconcile:
    """Tests for reconcile method."""

    def test_reconcile_empty_evidence(self, manager):
        """Returns empty report when no evidence."""
        with patch.object(manager.evidence, "list", return_value=[]):
            report = manager.reconcile("test-run")

        assert report.run_id == "test-run"
        assert report.total_records == 0
        assert "No evidence records found" in report.gaps_detected

    def test_reconcile_with_evidence(self, manager):
        """Analyzes evidence records correctly."""
        evidence = [
            {"id": "1", "kind": "S1.incident", "idempotency_key": "key1", "timestamp": "2024-01-01T00:00:00Z"},
            {"id": "2", "kind": "S2.task_graph", "idempotency_key": "key2", "timestamp": "2024-01-01T01:00:00Z"},
        ]

        with patch.object(manager.evidence, "list", return_value=evidence):
            report = manager.reconcile("test-run")

        assert report.total_records == 2
        assert report.unique_idempotency_keys == 2

    def test_reconcile_detects_duplicates(self, manager):
        """Counts duplicate idempotency keys."""
        evidence = [
            {"id": "1", "kind": "S1.incident", "idempotency_key": "same-key"},
            {"id": "2", "kind": "S2.task_graph", "idempotency_key": "same-key"},
            {"id": "3", "kind": "S4.finding", "idempotency_key": "other-key"},
        ]

        with patch.object(manager.evidence, "list", return_value=evidence):
            report = manager.reconcile("test-run")

        assert report.duplicates_skipped == 1
        assert report.unique_idempotency_keys == 2

    def test_reconcile_missing_expected_kinds(self, manager):
        """Detects missing expected evidence kinds."""
        evidence = [
            {"id": "1", "kind": "S1.incident", "idempotency_key": "key1"},
        ]

        with patch.object(manager.evidence, "list", return_value=evidence):
            report = manager.reconcile("test-run")

        assert "Missing expected evidence kind: S2.task_graph" in report.gaps_detected


class TestLoadNonTerminalRuns:
    """Tests for loading non-terminal runs."""

    def test_load_non_terminal_empty(self, manager):
        """Returns empty when no runs."""
        with patch.object(manager.store, "load_all", return_value=[]):
            runs = manager.load_non_terminal_runs()

        assert runs == []

    def test_load_non_terminal_filters_terminal(self, manager):
        """Filters out terminal runs."""
        terminal = MagicMock()
        terminal.state = RunState.RESOLVED
        non_terminal = MagicMock()
        non_terminal.state = RunState.INVESTIGATING

        with patch.object(manager.store, "load_all", return_value=[terminal, non_terminal]):
            runs = manager.load_non_terminal_runs()

        assert len(runs) == 1
        assert runs[0].state == RunState.INVESTIGATING


class TestRecoverRun:
    """Tests for run recovery."""

    def test_recover_from_checkpoint(self, manager):
        """Recovers from checkpoint when available."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.INVESTIGATING

        checkpoint = MagicMock()
        checkpoint.checkpoint_sequence = 5
        checkpoint.state = RunState.PLANNING

        with patch.object(manager.store, "has_checkpoint", return_value=True):
            with patch.object(manager.store, "load_checkpoint", return_value=checkpoint):
                result = manager.recover_run(run)

        assert result.recovered is True
        assert result.resume_from_checkpoint is True

    def test_recover_from_evidence(self, manager):
        """Recovers from evidence when no checkpoint."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.PLANNING

        with patch.object(manager.store, "has_checkpoint", return_value=False):
            with patch.object(manager.evidence, "list", return_value=[{"id": "1"}]):
                result = manager.recover_run(run)

        assert result.recovered is True
        assert result.resume_from_checkpoint is False

    def test_recover_from_state_only(self, manager):
        """Recovers from state when no checkpoint or evidence."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.EXECUTING

        with patch.object(manager.store, "has_checkpoint", return_value=False):
            with patch.object(manager.evidence, "list", return_value=[]):
                result = manager.recover_run(run)

        assert result.recovered is True


class TestGetRecoveryPlan:
    """Tests for recovery plan generation."""

    def test_plan_checkpoint_strategy(self, manager):
        """Returns checkpoint strategy when checkpoint exists."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.INVESTIGATING
        run.checkpoint_sequence = 3

        with patch.object(manager.store, "has_checkpoint", return_value=True):
            plan = manager.get_recovery_plan(run)

        assert plan["recovery_strategy"] == "checkpoint"

    def test_plan_evidence_replay(self, manager):
        """Returns evidence replay when no checkpoint but has evidence."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.INVESTIGATING

        with patch.object(manager.store, "has_checkpoint", return_value=False):
            with patch.object(manager.evidence, "list", return_value=[{"id": "1"}]):
                plan = manager.get_recovery_plan(run)

        assert plan["recovery_strategy"] == "evidence_replay"

    def test_plan_manual_intervention(self, manager):
        """Returns manual intervention when no data."""
        run = MagicMock()
        run.run_id = "test"
        run.state = RunState.INVESTIGATING

        with patch.object(manager.store, "has_checkpoint", return_value=False):
            with patch.object(manager.evidence, "list", return_value=[]):
                plan = manager.get_recovery_plan(run)

        assert plan["recovery_strategy"] == "manual_intervention"


class TestReconciliationReport:
    """Tests for ReconciliationReport dataclass."""

    def test_report_creation(self):
        """Can create a report."""
        report = ReconciliationReport(
            run_id="test",
            total_records=10,
            unique_idempotency_keys=8,
            duplicates_skipped=2,
            evidence_kinds=["S1.incident"],
            gaps_detected=[],
            last_evidence_timestamp=datetime.now(timezone.utc),
            generated_at=datetime.now(timezone.utc)
        )

        assert report.run_id == "test"
        assert report.total_records == 10


class TestRecoveryResult:
    """Tests for RecoveryResult dataclass."""

    def test_result_creation(self):
        """Can create a result."""
        result = RecoveryResult(
            run_id="test",
            recovered=True,
            resume_from_checkpoint=True,
            checkpoint_sequence=5,
            state_at_recovery=RunState.PLANNING,
            message="Success"
        )

        assert result.recovered is True
        assert result.checkpoint_sequence == 5
