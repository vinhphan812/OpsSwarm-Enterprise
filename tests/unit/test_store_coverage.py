"""Additional contract tests covering the FileStore surface not yet exercised.

These target real, reachable behaviour of :mod:`opsswarm.store` rather than
defensive filler: checkpoint discovery/deletion across both on-disk formats,
CAS against missing or mismatched revisions, malformed checkpoint payloads,
and the cross-platform lock release path.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from opsswarm.models import RunRecord, RunState
from opsswarm.store import FileStore


def _store(tmp_path: Path, **kwargs: object) -> FileStore:
    return FileStore(str(tmp_path), **kwargs)  # type: ignore[arg-type]


def test_has_checkpoint_detects_new_format_envelope(tmp_path: Path) -> None:
    """A run checkpointed in the envelope format is reported as having a checkpoint."""
    store = _store(tmp_path)
    store.save(RunRecord(run_id="run-1", issue_number=1))
    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    assert store.has_checkpoint("run-1") is True


def test_has_checkpoint_detects_legacy_snapshot(tmp_path: Path) -> None:
    """A legacy RunRecord checkpoint snapshot is reported as having a checkpoint."""
    store = _store(tmp_path)
    store.save_checkpoint(
        RunRecord(run_id="run-1", issue_number=1, state=RunState.TRIAGE), "triage"
    )

    assert store.has_checkpoint("run-1") is True


def test_delete_checkpoint_removes_new_format_envelope(tmp_path: Path) -> None:
    """Deleting a checkpoint removes the envelope file and reports success."""
    store = _store(tmp_path)
    store.save(RunRecord(run_id="run-1", issue_number=1))
    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    assert store.delete_checkpoint("run-1") is True
    assert not (store.path / "run-1.checkpoint.json").exists()
    assert store.has_checkpoint("run-1") is False
    assert store.get_last_checkpoint("run-1") is None


def test_delete_checkpoint_removes_both_formats(tmp_path: Path) -> None:
    """Deleting a checkpoint clears the legacy snapshot and the envelope together."""
    store = _store(tmp_path)
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.TRIAGE)
    store.save_checkpoint(run, "triage")
    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    assert store.delete_checkpoint("run-1") is True
    assert not (store.path / "run-1.checkpoint").exists()
    assert not (store.path / "run-1.checkpoint.json").exists()
    assert store.has_checkpoint("run-1") is False


def test_delete_checkpoint_reports_missing_file(tmp_path: Path) -> None:
    """Deleting a checkpoint that was never written reports that nothing was removed."""
    store = _store(tmp_path)

    assert store.delete_checkpoint("never-written") is False


def test_get_last_checkpoint_returns_none_without_checkpoint(tmp_path: Path) -> None:
    """Reading the last checkpoint of an unknown run returns None."""
    store = _store(tmp_path)

    assert store.get_last_checkpoint("never-written") is None


def test_get_last_checkpoint_ignores_non_object_payload(tmp_path: Path) -> None:
    """A checkpoint file holding a JSON array is not a usable checkpoint."""
    store = _store(tmp_path)
    (store.path / "run-1.checkpoint.json").write_text("[1, 2, 3]", encoding="utf-8")

    assert store.get_last_checkpoint("run-1") is None


def test_get_last_checkpoint_returns_none_for_unreadable_envelope(
    tmp_path: Path,
) -> None:
    """A corrupt envelope without a legacy snapshot yields no checkpoint."""
    store = _store(tmp_path)
    (store.path / "run-1.checkpoint.json").write_text("{invalid", encoding="utf-8")

    assert store.get_last_checkpoint("run-1") is None


def test_load_checkpoint_returns_none_for_corrupt_snapshot(tmp_path: Path) -> None:
    """A corrupt legacy checkpoint snapshot is reported as absent."""
    store = _store(tmp_path)
    (store.path / "run-1.checkpoint").write_text("{invalid", encoding="utf-8")

    assert store.load_checkpoint("run-1") is None


def test_update_with_cas_rejects_missing_run(tmp_path: Path) -> None:
    """A compare-and-swap against an unknown run fails instead of creating one."""
    store = _store(tmp_path)

    assert store.update_with_cas("never-written", {"state": RunState.RESOLVED}, 1) is False
    assert store.load("never-written") is None


def test_update_with_cas_rejects_mismatched_revision(tmp_path: Path) -> None:
    """A compare-and-swap with a stale expected revision leaves the record untouched."""
    store = _store(tmp_path)
    run = RunRecord(run_id="run-1", issue_number=1, revision=3)
    store.save(run)

    assert store.update_with_cas("run-1", {"error": "changed"}, 1) is False

    loaded = store.load("run-1")
    assert loaded is not None and loaded.revision == 3
    assert loaded.error is None


def test_update_with_cas_ignores_unknown_fields(tmp_path: Path) -> None:
    """Fields that are not part of the run record are ignored by the swap."""
    store = _store(tmp_path)
    store.save(RunRecord(run_id="run-1", issue_number=1, revision=1))

    assert store.update_with_cas("run-1", {"not_a_run_field": "value"}, 1) is True

    loaded = store.load("run-1")
    assert loaded is not None and loaded.revision == 2
    assert not hasattr(loaded, "not_a_run_field")


def test_save_checkpoint_for_unknown_run_still_writes_envelope(tmp_path: Path) -> None:
    """An envelope can be written for a run that has no stored record yet."""
    store = _store(tmp_path)

    checkpoint_id = store.save_checkpoint("run-1", "state_transition", {"state": "triage"})

    assert checkpoint_id
    envelope = json.loads((store.path / "run-1.checkpoint.json").read_text(encoding="utf-8"))
    assert envelope["checkpoint_id"] == checkpoint_id
    assert envelope["run_id"] == "run-1"
    assert envelope["payload"] == {"state": "triage"}


def test_process_lock_release_failure_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failure while releasing the advisory lock is logged instead of raised."""
    import types

    import opsswarm.store as store_module

    store = _store(tmp_path)

    def _locking(_fd: int, mode: int, _nbytes: int) -> None:
        if mode == 1:  # msvcrt.LK_UNLCK
            raise OSError("release failed")

    def _flock(_fd: int, operation: int) -> None:
        if operation == 8:  # fcntl.LOCK_UN
            raise OSError("release failed")

    fake_msvcrt = types.SimpleNamespace(
        LK_NBLCK=2, LK_UNLCK=1, locking=_locking
    )
    fake_fcntl = types.SimpleNamespace(
        LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=_flock
    )
    monkeypatch.setattr(store_module, "msvcrt", fake_msvcrt, raising=False)
    monkeypatch.setattr(store_module, "fcntl", fake_fcntl, raising=False)

    with caplog.at_level("ERROR"):
        with store._process_lock("run-1"):
            pass

    assert "Failed to release run store lock" in caplog.text


def test_process_lock_retries_until_the_holder_releases(tmp_path: Path) -> None:
    """Lock acquisition waits and retries while another holder owns the lock."""
    store = _store(tmp_path, persistence_config={"lock_timeout_seconds": 30})
    holder_released = threading.Event()
    acquired = threading.Event()
    failures: list[BaseException] = []

    def _holder() -> None:
        with store._process_lock("run-1"):
            holder_released.wait(timeout=10)

    def _waiter() -> None:
        try:
            with store._process_lock("run-1"):
                acquired.set()
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            failures.append(exc)

    holder = threading.Thread(target=_holder)
    holder.start()
    try:
        # Give the holder time to take the lock before contending for it.
        time.sleep(0.2)
        waiter = threading.Thread(target=_waiter)
        waiter.start()
        time.sleep(0.2)
        assert not acquired.is_set(), "the waiter must not acquire a held lock"

        holder_released.set()
        holder.join(timeout=10)
        waiter.join(timeout=10)
    finally:
        holder_released.set()
        holder.join(timeout=10)

    assert not failures
    assert acquired.is_set(), "the waiter must acquire the lock once it is released"


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    """Successful atomic writes clean up their temporary files."""
    store = _store(tmp_path)

    store.save(RunRecord(run_id="run-1", issue_number=1))
    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    assert not list(store.path.glob(".*.tmp"))
    assert not list(store.path.glob(".*.checkpoint.tmp"))


def test_load_all_ignores_checkpoint_envelope_files(tmp_path: Path) -> None:
    """Checkpoint envelopes are not mistaken for run records when listing runs."""
    store = _store(tmp_path)
    store.save(RunRecord(run_id="run-1", issue_number=1))
    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    assert [run.run_id for run in store.load_all()] == ["run-1"]


def test_legacy_run_snapshot_survives_a_new_format_checkpoint(tmp_path: Path) -> None:
    """Writing an envelope never rewrites the stored run snapshot."""
    store = _store(tmp_path)
    run = RunRecord(run_id="run-1", issue_number=1, state=RunState.INVESTIGATING)
    store.save(run)
    snapshot = (store.path / "run-1.json").read_text(encoding="utf-8")

    store.save_checkpoint("run-1", "state_transition", {"state": "resolved"})

    loaded = store.load("run-1")
    assert loaded is not None and loaded.state == RunState.INVESTIGATING
    assert loaded.checkpoint_sequence == 1
    assert (store.path / "run-1.json").read_text(encoding="utf-8") != snapshot


def test_store_backend_configuration_defaults_to_filesystem() -> None:
    """The store configuration section defaults to the filesystem backend."""
    from opsswarm.config import get_store

    assert get_store({})["backend"] == "filesystem"
    assert get_store({"store": {"backend": "postgres"}})["backend"] == "postgres"


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only advisory lock path")
def test_process_lock_uses_posix_flock(tmp_path: Path) -> None:
    """On POSIX hosts the advisory lock is taken with fcntl.flock."""
    store = _store(tmp_path)

    with store._process_lock("run-1"):
        assert (store.path / ".run-1.lock").exists()
