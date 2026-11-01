from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
import uuid

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .models import RunRecord

logger = logging.getLogger(__name__)


class BaseStore(ABC):
    """Abstract base class for OpsSwarm persistence backends (ADR-030)."""

    @abstractmethod
    def save(self, run: RunRecord) -> None:
        """Save a run record."""

    @abstractmethod
    def load(self, run_id: str) -> RunRecord | None:
        """Load a run record by ID."""

    @abstractmethod
    def load_all(self) -> list[RunRecord]:
        """Load all run records."""

    @abstractmethod
    def save_checkpoint(
        self, run_id: str, checkpoint_type: str, payload: dict[str, Any]
    ) -> str:
        """Save a checkpoint for a run and return checkpoint ID."""

    @abstractmethod
    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get the last checkpoint for a run."""

    @abstractmethod
    def update_with_cas(
        self, run_id: str, new_data: dict[str, Any], expected_revision: int
    ) -> bool:
        """Update run record with Compare-And-Swap (CAS) on revision."""


class FileStore(BaseStore):
    def __init__(
        self,
        data_dir: str,
        enable_atomic_writes: bool = True,
        enable_checkpoints: bool = True,
        persistence_config: dict[str, Any] | None = None,
    ):
        """Initialize the run store.

        Args:
            data_dir: Directory to store run records.
            enable_atomic_writes: Enable atomic writes (tmp + rename).
            enable_checkpoints: Enable checkpoint saving/loading.
            persistence_config: Full persistence config dict for feature flag checks.
        """
        self.path = Path(data_dir) / "runs"
        self.path.mkdir(parents=True, exist_ok=True)

        # Feature flags from config
        self.persistence_config = persistence_config or {}
        self.enable_atomic_writes = self.persistence_config.get(
            "enable_atomic_writes", enable_atomic_writes
        )
        self.enable_checkpoints = self.persistence_config.get(
            "enable_checkpoints", enable_checkpoints
        )
        self._lock_timeout = float(self.persistence_config.get("lock_timeout_seconds", 30.0))

        # Log warnings for legacy mode
        if not self.enable_atomic_writes:
            logger.warning("[LEGACY] Atomic writes disabled - data may be corrupted on crash")

    @contextmanager
    def _process_lock(self, run_id: str) -> Iterator[None]:
        """Serialize operations on one run across threads and processes."""
        lock_path = self.path / f".{run_id}.lock"
        with lock_path.open("a+b") as lock_file:
            if os.name == "nt" and lock_path.stat().st_size == 0:
                lock_file.write(b"0")
                lock_file.flush()
            deadline = time.monotonic() + self._lock_timeout
            while True:
                try:
                    if os.name == "nt":
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring run store lock for {run_id}")
                    time.sleep(0.01)
            try:
                yield
            finally:
                try:
                    if os.name == "nt":
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    logger.exception("Failed to release run store lock for %s", run_id)

    def _discard_legacy_stale_temps(self, run_id: str) -> None:
        """Remove leftover fixed-name temp files from an interrupted write.

        Atomic writes use a unique temp name per attempt (``.run_id.<uuid>.tmp``),
        so a crashed write can never publish a half-written run file. Older
        releases used a fixed temp name (``.run_id.tmp`` / ``.run_id.checkpoint.tmp``);
        a file left behind under those names is stale by definition and is
        discarded so it is never mistaken for a valid temporary.

        Only the exact legacy names are removed: a glob would race with a
        concurrent writer's unique temp file.

        Args:
            run_id: The run whose legacy temp files should be discarded.
        """
        for legacy_name in (f".{run_id}.tmp", f".{run_id}.checkpoint.tmp"):
            legacy_path = self.path / legacy_name
            try:
                legacy_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Failed to discard stale temp file %s", legacy_path, exc_info=True
                )

    def save(self, run: RunRecord) -> None:
        """Save a run record with atomic write (write to temp, then rename).

        Args:
            run: The RunRecord to save.
        """
        with self._process_lock(run.run_id):
            self._discard_legacy_stale_temps(run.run_id)
            self._save_locked(run)

    def load(self, run_id: str) -> RunRecord | None:
        """Load a single run record by ID."""
        dest = self.path / f"{run_id}.json"
        if not dest.exists():
            return None
        try:
            return RunRecord.model_validate_json(dest.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_with_retry(self, run: RunRecord, max_retries: int = 3) -> bool:
        """Save a run record with retry on failure.

        Args:
            run: The RunRecord to save.
            max_retries: Maximum number of retry attempts.

        Returns:
            True if save succeeded, False after max_retries attempts.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                self.save(run)
                return True
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Save attempt {attempt + 1}/{max_retries} failed for run {run.run_id}: {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff

        logger.error(f"Failed to save run {run.run_id} after {max_retries} attempts: {last_error}")
        return False

    def load_all(self) -> list[RunRecord]:
        out = []
        for p in self.path.glob("*.json"):
            try:
                out.append(RunRecord.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return out

    def save_checkpoint(
        self,
        run_id_or_run: str | RunRecord,
        checkpoint_type_or_data: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Save a checkpoint for a run with atomic write (tmp + rename)."""
        if not self.enable_checkpoints:
            logger.debug("[LEGACY] Checkpoints disabled, skipping checkpoint save")
            return ""

        if isinstance(run_id_or_run, RunRecord):
            run = run_id_or_run
            run_id = run.run_id
            checkpoint_data = checkpoint_type_or_data
            checkpoint_file = self.path / f"{run_id}.checkpoint"
            tmp_path = self.path / f".{run_id}.{uuid.uuid4().hex}.checkpoint.tmp"

            run.checkpoint_state = checkpoint_data
            run.last_checkpoint_at = datetime.now(UTC)
            run.checkpoint_sequence += 1

            try:
                with self._process_lock(run_id):
                    self._discard_legacy_stale_temps(run_id)
                    with tmp_path.open("w", encoding="utf-8") as checkpoint_tmp:
                        checkpoint_tmp.write(run.model_dump_json(indent=2))
                        checkpoint_tmp.flush()
                        os.fsync(checkpoint_tmp.fileno())
                    os.replace(tmp_path, checkpoint_file)
            finally:
                tmp_path.unlink(missing_ok=True)
            return run_id
        else:
            run_id = run_id_or_run
            checkpoint_type = checkpoint_type_or_data
            payload = payload or {}
            ckpt_id = str(uuid.uuid4())
            checkpoint_file = self.path / f"{run_id}.checkpoint.json"
            tmp_path = self.path / f".{run_id}.{uuid.uuid4().hex}.checkpoint.tmp"

            run = self.load(run_id)
            if run:
                run.checkpoint_state = json.dumps(payload)
                run.last_checkpoint_at = datetime.now(UTC)
                run.checkpoint_sequence += 1
                self.save(run)

            ckpt_payload = {
                "checkpoint_id": ckpt_id,
                "run_id": run_id,
                "checkpoint_type": checkpoint_type,
                "payload": payload,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                with self._process_lock(run_id):
                    self._discard_legacy_stale_temps(run_id)
                    with tmp_path.open("w", encoding="utf-8") as checkpoint_tmp:
                        json.dump(ckpt_payload, checkpoint_tmp, indent=2)
                        checkpoint_tmp.flush()
                        os.fsync(checkpoint_tmp.fileno())
                    os.replace(tmp_path, checkpoint_file)
            finally:
                tmp_path.unlink(missing_ok=True)
            return ckpt_id

    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get the last checkpoint for a run."""
        if not self.enable_checkpoints:
            return None
        checkpoint_file = self.path / f"{run_id}.checkpoint.json"
        if not checkpoint_file.exists():
            checkpoint_file = self.path / f"{run_id}.checkpoint"
        if not checkpoint_file.exists():
            return None
        try:
            content = checkpoint_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                if "checkpoint_type" in data or "payload" in data:
                    return data
                else:
                    return {
                        "run_id": run_id,
                        "checkpoint_type": "state_transition",
                        "payload": data,
                    }
            return None
        except Exception:
            run = self.load_checkpoint(run_id)
            if run:
                return {
                    "run_id": run_id,
                    "checkpoint_type": "state_transition",
                    "payload": {
                        "state": run.state.value
                        if hasattr(run.state, "value")
                        else str(run.state)
                    },
                }
            return None

    def update_with_cas(
        self, run_id: str, new_data: dict[str, Any], expected_revision: int
    ) -> bool:
        """Update run record with Compare-And-Swap (CAS) on revision."""
        with self._process_lock(run_id):
            run = self.load(run_id)
            if not run:
                return False
            current_revision = getattr(run, "revision", 1)
            if current_revision != expected_revision:
                return False

            for k, v in new_data.items():
                if hasattr(run, k):
                    setattr(run, k, v)

            run.revision = expected_revision + 1
            run.updated_at = datetime.now(UTC)
            self._save_locked(run)
            return True

    def _save_locked(self, run: RunRecord) -> None:
        """Persist a run when the caller already owns its process lock."""
        dest = self.path / f"{run.run_id}.json"
        if self.enable_atomic_writes:
            tmp_path = self.path / f".{run.run_id}.{uuid.uuid4().hex}.tmp"
            try:
                with tmp_path.open("w", encoding="utf-8") as tmp_file:
                    tmp_file.write(run.model_dump_json(indent=2))
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                os.replace(tmp_path, dest)
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            dest.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    def load_checkpoint(self, run_id: str) -> RunRecord | None:
        """Load a checkpoint if it exists for the given run."""
        if not self.enable_checkpoints:
            return None

        checkpoint_file = self.path / f"{run_id}.checkpoint"
        if not checkpoint_file.exists():
            return None
        try:
            return RunRecord.model_validate_json(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def has_checkpoint(self, run_id: str) -> bool:
        """Check if a checkpoint exists for the given run.

        Both the legacy RunRecord snapshot (``.checkpoint``) and the current
        envelope format (``.checkpoint.json``) are recognised, so the answer
        stays consistent with :meth:`get_last_checkpoint`.
        """
        if not self.enable_checkpoints:
            return False
        return any(
            (self.path / f"{run_id}{suffix}").exists()
            for suffix in (".checkpoint", ".checkpoint.json")
        )

    def delete_checkpoint(self, run_id: str) -> bool:
        """Delete every checkpoint artefact for a run.

        Returns True when at least one checkpoint file was removed.
        """
        deleted = False
        for suffix in (".checkpoint", ".checkpoint.json"):
            checkpoint_file = self.path / f"{run_id}{suffix}"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                deleted = True
        return deleted


RunStore = FileStore


class HaRunStore(BaseStore):
    """PostgreSQL-backed High Availability Run Store (implemented in Phase 2/3/4)."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}

    def save(self, run: RunRecord) -> None:
        raise NotImplementedError("HaRunStore.save requires PostgreSQL backend (Phase 2/3)")

    def load(self, run_id: str) -> RunRecord | None:
        raise NotImplementedError("HaRunStore.load requires PostgreSQL backend (Phase 2/3)")

    def load_all(self) -> list[RunRecord]:
        raise NotImplementedError("HaRunStore.load_all requires PostgreSQL backend (Phase 2/3)")

    def save_checkpoint(
        self, run_id: str, checkpoint_type: str, payload: dict[str, Any]
    ) -> str:
        raise NotImplementedError("HaRunStore.save_checkpoint requires PostgreSQL backend (Phase 2/3)")

    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        raise NotImplementedError("HaRunStore.get_last_checkpoint requires PostgreSQL backend (Phase 2/3)")

    def update_with_cas(
        self, run_id: str, new_data: dict[str, Any], expected_revision: int
    ) -> bool:
        raise NotImplementedError("HaRunStore.update_with_cas requires PostgreSQL backend (Phase 2/3)")
