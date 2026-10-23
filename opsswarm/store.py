from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import RunRecord

logger = logging.getLogger(__name__)


from abc import ABC, abstractmethod
import uuid
import json


class BaseStore(ABC):
    """Abstract base class for OpsSwarm persistence backends (ADR-030)."""

    @abstractmethod
    def save(self, run: RunRecord) -> None:
        """Save a run record."""
        pass

    @abstractmethod
    def load(self, run_id: str) -> RunRecord | None:
        """Load a run record by ID."""
        pass

    @abstractmethod
    def load_all(self) -> list[RunRecord]:
        """Load all run records."""
        pass

    @abstractmethod
    def save_checkpoint(
        self, run_id: str, checkpoint_type: str, payload: dict[str, Any]
    ) -> str:
        """Save a checkpoint for a run and return checkpoint ID."""
        pass

    @abstractmethod
    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get the last checkpoint for a run."""
        pass

    @abstractmethod
    def update_with_cas(
        self, run_id: str, new_data: dict[str, Any], expected_revision: int
    ) -> bool:
        """Update run record with Compare-And-Swap (CAS) on revision."""
        pass


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

        # Log warnings for legacy mode
        if not self.enable_atomic_writes:
            logger.warning("[LEGACY] Atomic writes disabled - data may be corrupted on crash")

    def save(self, run: RunRecord) -> None:
        """Save a run record with atomic write (write to temp, then rename).

        Args:
            run: The RunRecord to save.
        """
        dest = self.path / f"{run.run_id}.json"

        if self.enable_atomic_writes:
            # Atomic write: write to .tmp file first, then atomic rename
            tmp_path = self.path / f".{run.run_id}.tmp"

            # Clean up any stale tmp file from previous crash
            if tmp_path.exists():
                tmp_path.unlink()

            # Write and flush the complete snapshot before publishing it.
            with tmp_path.open("w", encoding="utf-8") as tmp_file:
                tmp_file.write(run.model_dump_json(indent=2))
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            # Atomic rename - os.replace is atomic on both POSIX and Windows
            # It handles cross-device moves and replaces existing files atomically
            os.replace(tmp_path, dest)
        else:
            # Direct write (non-atomic, for legacy compatibility)
            dest.write_text(run.model_dump_json(indent=2), encoding="utf-8")

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
            tmp_path = self.path / f".{run_id}.checkpoint.tmp"

            run.checkpoint_state = checkpoint_data
            run.last_checkpoint_at = datetime.now(UTC)
            run.checkpoint_sequence += 1

            if tmp_path.exists():
                tmp_path.unlink()

            tmp_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp_path, checkpoint_file)
            return run_id
        else:
            run_id = run_id_or_run
            checkpoint_type = checkpoint_type_or_data
            payload = payload or {}
            ckpt_id = str(uuid.uuid4())
            checkpoint_file = self.path / f"{run_id}.checkpoint"
            tmp_path = self.path / f".{run_id}.checkpoint.tmp"

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
            if tmp_path.exists():
                tmp_path.unlink()
            tmp_path.write_text(json.dumps(ckpt_payload, indent=2), encoding="utf-8")
            os.replace(tmp_path, checkpoint_file)
            return ckpt_id

    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get the last checkpoint for a run."""
        if not self.enable_checkpoints:
            return None
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
        self.save(run)
        return True

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
        """Check if a checkpoint exists for the given run."""
        if not self.enable_checkpoints:
            return False
        return (self.path / f"{run_id}.checkpoint").exists()

    def delete_checkpoint(self, run_id: str) -> bool:
        """Delete a checkpoint for a run."""
        checkpoint_file = self.path / f"{run_id}.checkpoint"
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            return True
        return False


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
