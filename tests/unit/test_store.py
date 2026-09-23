"""Unit tests for opsswarm.store module."""
import pytest

from opsswarm.models import RunRecord, RunState
from opsswarm.store import RunStore


@pytest.fixture
def store(tmp_path):
    """Create a RunStore with temp directory."""
    return RunStore(str(tmp_path / "runs"))


def make_run(run_id: str, state: RunState) -> RunRecord:
    """Helper to create a RunRecord."""
    return RunRecord(
        run_id=run_id,
        issue_number=1,
        state=state,
        risk="read",
        checkpoint_state=None,
        last_checkpoint_at=None,
        checkpoint_sequence=0,
    )


class TestStoreInit:
    """Tests for RunStore initialization."""

    def test_init_creates_directory(self, store, tmp_path):
        """Creates data directory on init."""
        assert store.path.exists()

    def test_default_flags_enabled(self, store):
        """Feature flags default to enabled."""
        assert store.enable_atomic_writes is True
        assert store.enable_checkpoints is True

    def test_custom_flags(self, tmp_path):
        """Can disable feature flags."""
        config = {"enable_atomic_writes": False, "enable_checkpoints": False}
        store = RunStore(str(tmp_path / "runs"), persistence_config=config)
        assert store.enable_atomic_writes is False
        assert store.enable_checkpoints is False


class TestSaveRun:
    """Tests for saving runs."""

    def test_save_creates_file(self, store):
        """Save creates JSON file."""
        run = make_run("run-1", RunState.OPEN)
        store.save(run)
        assert (store.path / "run-1.json").exists()

    def test_save_with_atomic_writes(self, store):
        """Atomic writes work."""
        run = make_run("run-2", RunState.TRIAGE)
        store.save(run)
        assert (store.path / "run-2.json").exists()

    def test_save_without_atomic_writes(self, tmp_path):
        """Can disable atomic writes."""
        store = RunStore(str(tmp_path / "runs"), enable_atomic_writes=False)
        run = make_run("run-3", RunState.INVESTIGATING)
        store.save(run)
        assert (store.path / "run-3.json").exists()


class TestLoadRuns:
    """Tests for loading runs."""

    def test_load_empty(self, store):
        """Load returns empty list when no files."""
        assert store.load_all() == []

    def test_load_returns_saved_runs(self, store):
        """Load returns previously saved runs."""
        run = make_run("run-1", RunState.OPEN)
        store.save(run)

        runs = store.load_all()
        assert len(runs) == 1
        assert runs[0].run_id == "run-1"


class TestSaveWithRetry:
    """Tests for retry logic."""

    def test_save_with_retry_success(self, store):
        """Saves on first attempt."""
        run = make_run("run-retry", RunState.OPEN)
        result = store.save_with_retry(run)
        assert result is True

    def test_save_with_retry_fails(self, store):
        """Returns False when all retries fail."""
        original_save = store.save
        call_count = [0]

        def failing_save(run):
            call_count[0] += 1
            raise IOError("Test failure")

        store.save = failing_save
        run = make_run("run-fail", RunState.OPEN)

        result = store.save_with_retry(run, max_retries=3)

        assert result is False
        assert call_count[0] == 3


class TestCheckpoints:
    """Tests for checkpoint functionality."""

    def test_save_checkpoint_disabled(self, store, caplog):
        """Skips when checkpoints disabled."""
        store.enable_checkpoints = False
        run = make_run("run-1", RunState.OPEN)

        store.save_checkpoint(run, "data")

        assert not (store.path / "run-1.checkpoint").exists()

    def test_save_checkpoint(self, store):
        """Saves checkpoint successfully."""
        run = make_run("run-1", RunState.OPEN)
        store.save_checkpoint(run, "test-data")

        assert (store.path / "run-1.checkpoint").exists()

    def test_load_checkpoint_not_exists(self, store):
        """Returns None when checkpoint doesn't exist."""
        result = store.load_checkpoint("nonexistent")
        assert result is None

    def test_load_checkpoint(self, store):
        """Loads existing checkpoint."""
        run = make_run("run-1", RunState.OPEN)
        store.save_checkpoint(run, "data")

        loaded = store.load_checkpoint("run-1")
        assert loaded is not None

    def test_has_checkpoint(self, store):
        """Correctly identifies checkpoint existence."""
        run = make_run("run-1", RunState.OPEN)
        store.save_checkpoint(run, "data")

        assert store.has_checkpoint("run-1") is True
        assert store.has_checkpoint("nonexistent") is False

    def test_delete_checkpoint(self, store):
        """Deletes checkpoint file."""
        run = make_run("run-1", RunState.OPEN)
        store.save_checkpoint(run, "data")

        result = store.delete_checkpoint("run-1")
        assert result is True
        assert not store.has_checkpoint("run-1")
