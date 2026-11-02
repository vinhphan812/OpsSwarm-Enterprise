"""Regression tests for the FileStore branches introduced by the store refactor.

The store refactor that introduced :class:`opsswarm.store.BaseStore` and
:class:`opsswarm.store.FileStore` added a number of behaviours that the
persistence layer depends on and that nothing else exercised: loading a
single run, the two checkpoint file formats, the compare-and-swap update,
and the legacy checkpoint fallback.  Each of them is a place where a silent
failure would lose run state rather than raise, so each is pinned here.
"""

from __future__ import annotations

import json

import pytest

from opsswarm.models import RunRecord, RunState
from opsswarm.store import FileStore


@pytest.fixture
def store(tmp_path):
    """Create a FileStore rooted in a temporary directory."""
    return FileStore(str(tmp_path / "runs"))


def make_run(run_id: str = "run-1", state: RunState = RunState.OPEN) -> RunRecord:
    """Build a minimal run record."""
    return RunRecord(
        run_id=run_id,
        issue_number=1,
        state=state,
        risk="read",
        checkpoint_state=None,
        last_checkpoint_at=None,
        checkpoint_sequence=0,
    )


# --------------------------------------------------------------------------- #
# Loading a single run
# --------------------------------------------------------------------------- #


def test_load_returns_none_for_an_unknown_run(store: FileStore) -> None:
    """A run that was never saved loads as ``None`` rather than raising."""
    assert store.load("never-saved") is None


def test_load_returns_none_for_a_corrupt_run_file(store: FileStore) -> None:
    """A truncated or corrupt run file loads as ``None`` rather than raising.

    A partially written file must not take down the caller: the run is
    treated as absent so the orchestrator can start a fresh one.
    """
    (store.path / "broken.json").write_text("{not json", encoding="utf-8")

    assert store.load("broken") is None


def test_load_all_skips_a_corrupt_run_file(store: FileStore) -> None:
    """One corrupt file does not hide the healthy runs beside it."""
    store.save(make_run("healthy"))
    (store.path / "broken.json").write_text("{not json", encoding="utf-8")

    runs = store.load_all()

    assert [run.run_id for run in runs] == ["healthy"]


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #


def test_save_discards_a_stale_temporary_file(store: FileStore) -> None:
    """A leftover ``.tmp`` file from a crashed write is discarded.

    The temporary file is only ever a half-written copy of the run, so it
    must never be promoted into the run file itself.
    """
    stale = store.path / ".run-1.tmp"
    stale.write_text("half written", encoding="utf-8")

    store.save(make_run("run-1"))

    assert not stale.exists()
    assert store.load("run-1") is not None


def test_save_preserves_another_writers_unique_temporary_file(store: FileStore) -> None:
    """Cleanup removes only the legacy fixed name, never a live unique temp.

    Atomic writes name each attempt ``.run_id.<uuid>.tmp``.  A cleanup that
    globbed the run-id prefix would delete a concurrent writer's in-flight
    temporary file between its ``write`` and its ``os.replace``, turning a
    healthy write into a lost update.  Only the exact legacy names may be
    removed.
    """
    in_flight = store.path / ".run-1.0f4c8a2b9d6e4a17b3c5d8e9f0a1b2c3.tmp"
    in_flight.write_text("concurrent writer still writing", encoding="utf-8")

    store.save(make_run("run-1"))

    assert in_flight.exists()
    assert in_flight.read_text(encoding="utf-8") == "concurrent writer still writing"


def test_save_checkpoint_preserves_another_writers_unique_temporary_file(
    store: FileStore,
) -> None:
    """Checkpoint cleanup likewise spares a concurrent unique temp file."""
    in_flight = store.path / ".run-1.9e7d6c5b4a39281706f5e4d3c2b1a09f.checkpoint.tmp"
    in_flight.write_text("concurrent checkpoint still writing", encoding="utf-8")

    store.save_checkpoint(make_run("run-1"), "data")

    assert in_flight.exists()
    assert in_flight.read_text(encoding="utf-8") == "concurrent checkpoint still writing"


# --------------------------------------------------------------------------- #
# Checkpoints
# --------------------------------------------------------------------------- #


def test_save_checkpoint_discards_a_stale_temporary_file(store: FileStore) -> None:
    """A leftover checkpoint ``.tmp`` file is discarded before the write."""
    stale = store.path / ".run-1.checkpoint.tmp"
    stale.write_text("half written", encoding="utf-8")

    store.save_checkpoint(make_run("run-1"), "data")

    assert not stale.exists()
    assert store.has_checkpoint("run-1") is True


def test_save_checkpoint_by_run_id_discards_a_stale_temporary_file(store: FileStore) -> None:
    """The run-id form of the checkpoint write also discards a stale ``.tmp``."""
    store.save(make_run("run-1"))
    stale = store.path / ".run-1.checkpoint.tmp"
    stale.write_text("half written", encoding="utf-8")

    store.save_checkpoint("run-1", "state_transition", {"state": "open"})

    assert not stale.exists()


def test_save_checkpoint_for_an_unknown_run_still_writes_the_checkpoint(store: FileStore) -> None:
    """A checkpoint for a run that is not on disk is still recorded.

    The checkpoint file carries its own payload, so it remains recoverable
    even when the run record itself is gone.
    """
    checkpoint_id = store.save_checkpoint("unknown-run", "state_transition", {"state": "open"})

    assert checkpoint_id
    assert store.has_checkpoint("unknown-run") is True


def test_get_last_checkpoint_returns_none_when_disabled(store: FileStore) -> None:
    """With checkpoints disabled there is no checkpoint to report."""
    store.enable_checkpoints = False

    assert store.get_last_checkpoint("run-1") is None


def test_get_last_checkpoint_returns_none_when_absent(store: FileStore) -> None:
    """A run without a checkpoint file reports no checkpoint."""
    assert store.get_last_checkpoint("run-1") is None


def test_get_last_checkpoint_wraps_a_legacy_payload(store: FileStore) -> None:
    """A checkpoint file holding a bare payload is normalised.

    The earliest checkpoint format wrote the payload on its own, without
    the ``checkpoint_type``/``payload`` envelope.  Such a file is still
    readable and must be presented through the current envelope so callers
    do not have to know which format is on disk.
    """
    (store.path / "run-1.checkpoint").write_text(
        json.dumps({"state": "investigating"}), encoding="utf-8"
    )

    checkpoint = store.get_last_checkpoint("run-1")

    assert checkpoint is not None
    assert checkpoint["run_id"] == "run-1"
    assert checkpoint["checkpoint_type"] == "state_transition"
    assert checkpoint["payload"] == {"state": "investigating"}


def test_get_last_checkpoint_falls_back_to_the_run_record(store: FileStore) -> None:
    """A checkpoint file that is not JSON is recovered from the run record.

    The run-id form of the checkpoint write stores the whole run record in
    the checkpoint file.  When that file cannot be parsed as the current
    envelope, the state it carried is still recoverable.
    """
    run = make_run("run-1", RunState.INVESTIGATING)
    (store.path / "run-1.checkpoint").write_text(run.model_dump_json(indent=2), encoding="utf-8")

    checkpoint = store.get_last_checkpoint("run-1")

    assert checkpoint is not None
    assert checkpoint["run_id"] == "run-1"
    assert checkpoint["checkpoint_type"] == "state_transition"
    assert checkpoint["payload"]["state"] == RunState.INVESTIGATING.value


def test_get_last_checkpoint_returns_none_for_an_unreadable_file(store: FileStore) -> None:
    """A checkpoint file that is neither envelope nor run record is dropped."""
    (store.path / "run-1.checkpoint").write_text("not json at all", encoding="utf-8")

    assert store.get_last_checkpoint("run-1") is None


def test_load_checkpoint_returns_none_when_disabled(store: FileStore) -> None:
    """With checkpoints disabled no checkpoint is loaded."""
    store.enable_checkpoints = False
    store.save_checkpoint(make_run("run-1"), "data")

    assert store.load_checkpoint("run-1") is None


def test_load_checkpoint_returns_none_for_a_corrupt_file(store: FileStore) -> None:
    """A corrupt checkpoint file loads as ``None`` rather than raising."""
    (store.path / "run-1.checkpoint").write_text("not json", encoding="utf-8")

    assert store.load_checkpoint("run-1") is None


def test_has_checkpoint_returns_false_when_disabled(store: FileStore) -> None:
    """With checkpoints disabled no checkpoint is reported as present."""
    store.enable_checkpoints = False
    store.save_checkpoint(make_run("run-1"), "data")

    assert store.has_checkpoint("run-1") is False


def test_delete_checkpoint_returns_false_when_absent(store: FileStore) -> None:
    """Deleting a checkpoint that is not there reports that nothing was deleted."""
    assert store.delete_checkpoint("run-1") is False


# --------------------------------------------------------------------------- #
# Compare-and-swap
# --------------------------------------------------------------------------- #


def test_update_with_cas_refuses_an_unknown_run(store: FileStore) -> None:
    """A compare-and-swap update against a missing run changes nothing."""
    assert store.update_with_cas("never-saved", {"state": RunState.RESOLVED}, 1) is False


def test_update_with_cas_ignores_unknown_fields(store: FileStore) -> None:
    """A compare-and-swap update only applies fields the run actually has.

    An update carrying a field the record does not model must not create
    it: silently adding an attribute would persist a value no other code
    reads back.
    """
    run = make_run("run-1")
    run.revision = 3
    store.save(run)

    assert store.update_with_cas("run-1", {"not_a_field": "x"}, 3) is True

    updated = store.load("run-1")
    assert updated.revision == 4
    assert not hasattr(updated, "not_a_field")
