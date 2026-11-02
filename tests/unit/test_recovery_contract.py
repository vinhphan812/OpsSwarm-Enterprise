"""Recovery-path tests that consume the FileStore checkpoint contract.

These exercise :class:`opsswarm.reconciliation.ReconciliationManager` against
real ``FileStore`` checkpoints, covering the backward-compatibility contract
between the legacy RunRecord checkpoint snapshot and the current envelope
format, plus the recovery recommendations that depend on it.
"""

from __future__ import annotations

import json
from pathlib import Path

from opsswarm.models import RunRecord, RunState
from opsswarm.reconciliation import ReconciliationManager
from opsswarm.store import FileStore


def test_recovery_uses_a_legacy_checkpoint_snapshot(tmp_path: Path) -> None:
    """A legacy RunRecord checkpoint is used to resume a run."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(
        run_id="run-1",
        issue_number=1,
        state=RunState.EXECUTING,
        checkpoint_state="execution",
        checkpoint_sequence=4,
    )
    manager.store.save_checkpoint(run, "execution")

    result = manager.recover_run(run)

    assert result.recovered is True
    assert result.resume_from_checkpoint is True
    # save_checkpoint() increments the run's checkpoint sequence before persisting it.
    assert result.checkpoint_sequence == 5
    assert result.state_at_recovery == RunState.EXECUTING


def test_recovery_falls_back_to_evidence_without_a_checkpoint(tmp_path: Path) -> None:
    """Without a checkpoint the run resumes from its evidence log."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.INVESTIGATING)
    manager.store.save(run)
    manager.evidence.append("run-1", "S4.finding", {"task_id": "t1"})

    result = manager.recover_run(run)

    assert result.recovered is True
    assert result.resume_from_checkpoint is False
    assert result.checkpoint_sequence is None
    assert "evidence log" in result.message


def test_recovery_reports_resuming_from_saved_run_state(tmp_path: Path) -> None:
    """A run with neither checkpoint nor evidence resumes from its saved state."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.OPEN)
    manager.store.save(run)

    result = manager.recover_run(run)

    assert result.recovered is True
    assert result.resume_from_checkpoint is False
    assert result.state_at_recovery == RunState.OPEN
    assert "saved run state" in result.message


def test_recovery_plan_selects_the_checkpoint_strategy(tmp_path: Path) -> None:
    """The recovery plan picks the checkpoint strategy when a checkpoint exists."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(
        run_id="run-1",
        issue_number=1,
        state=RunState.EXECUTING,
        checkpoint_sequence=2,
    )
    manager.store.save_checkpoint(run, "execution")

    plan = manager.get_recovery_plan(run)

    assert plan["recovery_strategy"] == "checkpoint"
    assert plan["has_checkpoint"] is True
    # The plan reports the sequence carried by the run record after checkpointing.
    assert plan["checkpoint_sequence"] == 3
    assert "checkpoint" in plan["recommendation"]


def test_recovery_plan_selects_evidence_replay_without_a_checkpoint(tmp_path: Path) -> None:
    """The recovery plan replays evidence when there is no checkpoint."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.INVESTIGATING)
    manager.store.save(run)
    manager.evidence.append("run-1", "S4.finding", {"task_id": "t1"})

    plan = manager.get_recovery_plan(run)

    assert plan["recovery_strategy"] == "evidence_replay"
    assert plan["has_checkpoint"] is False
    assert plan["checkpoint_sequence"] is None


def test_recovery_plan_requires_manual_intervention_without_records(tmp_path: Path) -> None:
    """The recovery plan asks for manual intervention when there is nothing to replay."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.OPEN)
    manager.store.save(run)

    plan = manager.get_recovery_plan(run)

    assert plan["recovery_strategy"] == "manual_intervention"
    assert "manual investigation required" in plan["recommendation"]


def test_recovery_plan_reports_evidence_gaps(tmp_path: Path) -> None:
    """The recovery plan names the detected evidence gaps in its recommendation."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.INVESTIGATING)
    manager.store.save(run)
    manager.evidence.append(
        "run-1", "S2.task_graph", {"tasks": [{"id": "t1"}, {"id": "t2"}]}
    )
    manager.evidence.append("run-1", "S4.finding", {"task_id": "t1"})

    plan = manager.get_recovery_plan(run)

    assert plan["gaps_detected"]
    assert "gaps" in plan["recommendation"]


def test_load_non_terminal_runs_skips_terminal_runs(tmp_path: Path) -> None:
    """Only non-terminal runs are offered for recovery on startup."""
    manager = ReconciliationManager(str(tmp_path))
    manager.store.save(RunRecord(run_id="open-run", issue_number=1, state=RunState.OPEN))
    manager.store.save(RunRecord(run_id="done-run", issue_number=2, state=RunState.ABORTED))

    recoverable = {run.run_id for run in manager.load_non_terminal_runs()}

    assert "open-run" in recoverable
    assert "done-run" not in recoverable


def test_new_format_checkpoint_is_visible_to_the_recovery_plan(tmp_path: Path) -> None:
    """A checkpoint written in the envelope format is recognised by recovery."""
    manager = ReconciliationManager(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.EXECUTING)
    manager.store.save(run)
    manager.store.save_checkpoint("run-1", "execution", {"phase": "post_execution"})

    plan = manager.get_recovery_plan(run)

    assert plan["has_checkpoint"] is True
    assert plan["recovery_strategy"] == "checkpoint"


def test_envelope_checkpoint_is_readable_after_a_restart(tmp_path: Path) -> None:
    """An envelope checkpoint survives a store restart and stays readable."""
    store = FileStore(str(tmp_path))
    store.save(RunRecord(run_id="run-1", issue_number=1))
    store.save_checkpoint("run-1", "execution", {"phase": "post_execution"})

    restarted = FileStore(str(tmp_path))
    checkpoint = restarted.get_last_checkpoint("run-1")

    assert checkpoint is not None
    assert checkpoint["checkpoint_type"] == "execution"
    assert checkpoint["payload"]["phase"] == "post_execution"


def test_legacy_run_snapshot_is_recovered_after_a_restart(tmp_path: Path) -> None:
    """A run snapshot written before a restart is still recovered afterwards."""
    store = FileStore(str(tmp_path))
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.INVESTIGATING)
    store.save(run)
    (store.path / "run-1.json").write_text(
        json.dumps(run.model_dump(mode="json")), encoding="utf-8"
    )

    restarted = FileStore(str(tmp_path))
    loaded = restarted.load("run-1")

    assert loaded is not None
    assert loaded.run_id == "run-1"
    assert loaded.state == RunState.INVESTIGATING
    assert loaded.revision == 1
