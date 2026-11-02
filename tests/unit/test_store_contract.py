"""Regression tests for legacy persistence and cross-process store contracts."""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from opsswarm.models import RunRecord, RunState
from opsswarm.store import FileStore


def _save_worker(data_dir: str, barrier: multiprocessing.Barrier, writer_id: int) -> None:
    """Contend on one run using independent store instances in processes."""
    store = FileStore(data_dir)
    barrier.wait(timeout=10)
    for sequence in range(10):
        store.save(
            RunRecord(
                run_id="legacy-run-42",
                issue_number=42,
                error=f"writer-{writer_id}-{sequence}",
            )
        )


def _cas_worker(
    data_dir: str, barrier: multiprocessing.Barrier, result_queue: multiprocessing.Queue
) -> None:
    """Race one CAS update against another process for the same revision."""
    store = FileStore(data_dir)
    barrier.wait(timeout=10)
    result_queue.put(store.update_with_cas("legacy-run-42", {"error": str(os.getpid())}, 1))


def test_get_last_checkpoint_returns_none_for_malformed_checkpoint(tmp_path: Path) -> None:
    """Malformed checkpoint envelopes fall back to a legacy snapshot when possible."""
    store = FileStore(str(tmp_path))
    store.save_checkpoint(
        RunRecord(run_id="legacy-run-42", issue_number=42, state=RunState.TRIAGE), "triage"
    )
    (store.path / "legacy-run-42.checkpoint.json").write_text("{invalid", encoding="utf-8")

    checkpoint = store.get_last_checkpoint("legacy-run-42")

    assert checkpoint is not None
    assert checkpoint["checkpoint_type"] == "state_transition"
    assert checkpoint["payload"]["state"] == "TRIAGE"


def test_process_lock_releases_when_operation_raises(tmp_path: Path) -> None:
    """The advisory lock is released after a failed operation."""
    store = FileStore(str(tmp_path), persistence_config={"lock_timeout_seconds": 0.1})

    with pytest.raises(RuntimeError):
        with store._process_lock("legacy-run-42"):
            raise RuntimeError("operation failed")

    with store._process_lock("legacy-run-42"):
        pass


def test_process_lock_times_out_when_already_locked(tmp_path: Path) -> None:
    """Lock acquisition reports a timeout instead of hanging indefinitely."""
    store = FileStore(str(tmp_path), persistence_config={"lock_timeout_seconds": 0})

    with store._process_lock("legacy-run-42"):
        with pytest.raises(TimeoutError, match="Timed out acquiring run store lock"):
            with store._process_lock("legacy-run-42"):
                pass


def test_missing_and_malformed_run_files_are_ignored(tmp_path: Path) -> None:
    """Missing and corrupt run snapshots do not break the remaining store reads."""
    store = FileStore(str(tmp_path))
    (store.path / "broken.json").write_text("{invalid", encoding="utf-8")

    assert store.load("missing") is None
    assert store.load("broken") is None
    assert store.load_all() == []


def test_disabled_checkpoints_hide_existing_checkpoint(tmp_path: Path) -> None:
    """The checkpoint feature flag disables both reads and writes."""
    store = FileStore(str(tmp_path), enable_checkpoints=False)
    (store.path / "run.checkpoint.json").write_text("{}", encoding="utf-8")

    assert store.save_checkpoint("run", "state_transition", {}) == ""
    assert store.get_last_checkpoint("run") is None
    assert store.has_checkpoint("run") is False


def test_loads_legacy_run_snapshot_and_checkpoint_without_revision(tmp_path: Path) -> None:
    """A pre-Phase-1 snapshot keeps its defaults and checkpoint state intact.

    The fixture is a captured run record from the pre-Phase-1 release
    (v2.2.0, commit 4e930336), which predates the ``revision`` field.  It is
    loaded from disk rather than generated from the current model so the test
    fails if a future model change stops accepting the snapshot that release
    actually wrote.
    """
    store = FileStore(str(tmp_path))
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "legacy_run_record_pre_phase1_v2.2.0.json"
    )
    record = json.loads(fixture.read_text(encoding="utf-8"))
    assert "revision" not in record
    (store.path / "legacy-run-42.json").write_text(json.dumps(record), encoding="utf-8")
    (store.path / "legacy-run-42.checkpoint").write_text(json.dumps(record), encoding="utf-8")

    loaded = store.load("legacy-run-42")
    checkpoint = store.load_checkpoint("legacy-run-42")

    assert loaded is not None and checkpoint is not None
    assert loaded.revision == 1
    assert checkpoint.revision == 1
    assert loaded.checkpoint_sequence == checkpoint.checkpoint_sequence == 3
    assert loaded.state == checkpoint.state == RunState.INVESTIGATING


def test_loads_legacy_checkpoint_envelope(tmp_path: Path) -> None:
    """Legacy checkpoint payloads are returned through the current envelope API."""
    store = FileStore(str(tmp_path))
    payload = {"state": "investigating", "checkpoint_sequence": 3}
    (store.path / "legacy-run-42.checkpoint").write_text(json.dumps(payload), encoding="utf-8")

    checkpoint = store.get_last_checkpoint("legacy-run-42")

    assert checkpoint == {
        "run_id": "legacy-run-42",
        "checkpoint_type": "state_transition",
        "payload": payload,
    }


def test_new_checkpoint_write_preserves_legacy_checkpoint_file(tmp_path: Path) -> None:
    """New checkpoint envelopes do not replace legacy RunRecord checkpoint snapshots."""
    store = FileStore(str(tmp_path))
    run = RunRecord(
        run_id="legacy-run-42",
        issue_number=42,
        state=RunState.INVESTIGATING,
        checkpoint_state="legacy-state",
        checkpoint_sequence=3,
    )
    store.save_checkpoint(run, "legacy-state")
    legacy_path = store.path / "legacy-run-42.checkpoint"
    legacy_content = legacy_path.read_text(encoding="utf-8")

    store.save_checkpoint("legacy-run-42", "state_transition", {"state": "resolved"})

    assert legacy_path.read_text(encoding="utf-8") == legacy_content
    loaded_legacy = store.load_checkpoint("legacy-run-42")
    current = store.get_last_checkpoint("legacy-run-42")
    assert loaded_legacy is not None and loaded_legacy.checkpoint_sequence == 4
    assert current is not None and current["payload"] == {"state": "resolved"}


def test_legacy_evidence_records_remain_readable(tmp_path: Path) -> None:
    """Evidence files in the existing JSONL format remain loadable by EvidenceStore."""
    from opsswarm.evidence import EvidenceStore

    legacy = EvidenceStore(str(tmp_path))
    evidence_id, is_duplicate = legacy.append(
        "legacy-run-42", "S4.finding", {"task_id": "t1", "finding": "legacy"}
    )
    assert evidence_id is not None and not is_duplicate

    restarted = EvidenceStore(str(tmp_path))
    records = restarted.list("legacy-run-42")
    assert len(records) == 1
    assert records[0]["payload"] == {"task_id": "t1", "finding": "legacy"}


def test_concurrent_process_saves_leave_a_valid_snapshot(tmp_path: Path) -> None:
    """Concurrent writers publish complete snapshots without temp-file collisions."""
    store = FileStore(str(tmp_path))
    store.save(RunRecord(run_id="legacy-run-42", issue_number=42))
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(4)
    workers = [
        ctx.Process(target=_save_worker, args=(str(tmp_path), barrier, idx)) for idx in range(3)
    ]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=10)
    for worker in workers:
        worker.join(timeout=30)

    assert all(not worker.is_alive() and worker.exitcode == 0 for worker in workers)
    loaded = store.load("legacy-run-42")
    assert loaded is not None and loaded.error is not None
    assert loaded.error.startswith("writer-")
    assert not list(store.path.glob(".*.tmp"))


def test_only_one_cross_process_cas_wins(tmp_path: Path) -> None:
    """CAS comparison and replacement are serialized across processes."""
    store = FileStore(str(tmp_path))
    store.save(RunRecord(run_id="legacy-run-42", issue_number=42, revision=1))
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    workers = [
        ctx.Process(target=_cas_worker, args=(str(tmp_path), barrier, results)) for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)

    assert all(not worker.is_alive() and worker.exitcode == 0 for worker in workers)
    assert sorted([results.get(timeout=2), results.get(timeout=2)]) == [False, True]
    loaded = store.load("legacy-run-42")
    assert loaded is not None and loaded.revision == 2


def test_atomic_replace_failure_preserves_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed publish leaves the old snapshot readable and cleans its temp file."""
    store = FileStore(str(tmp_path))
    original = RunRecord(run_id="legacy-run-42", issue_number=42, error="old")
    store.save(original)
    replacement = original.model_copy(update={"error": "new"})

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("interrupted before publish")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted before publish"):
        store.save(replacement)

    loaded = store.load("legacy-run-42")
    assert loaded is not None and loaded.error == "old"
    assert not list(store.path.glob(".*.tmp"))
