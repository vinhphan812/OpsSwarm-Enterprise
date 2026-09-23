from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import RunRecord

logger = logging.getLogger(__name__)


class RunStore:
    def __init__(self, data_dir: str, enable_atomic_writes: bool = True, enable_checkpoints: bool = True,
                 persistence_config: dict[str, Any] | None = None):
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
        self.enable_atomic_writes = self.persistence_config.get("enable_atomic_writes", enable_atomic_writes)
        self.enable_checkpoints = self.persistence_config.get("enable_checkpoints", enable_checkpoints)

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

            # Write to temp file
            tmp_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

            # Atomic rename - os.replace is atomic on both POSIX and Windows
            # It handles cross-device moves and replaces existing files atomically
            os.replace(tmp_path, dest)
        else:
            # Direct write (non-atomic, for legacy compatibility)
            dest.write_text(run.model_dump_json(indent=2), encoding="utf-8")

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
                logger.warning(f"Save attempt {attempt + 1}/{max_retries} failed for run {run.run_id}: {e}")
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

    def save_checkpoint(self, run: RunRecord, checkpoint_data: str) -> None:
        """Save a checkpoint for a run with atomic write (tmp + rename).

        Args:
            run: The RunRecord to checkpoint.
            checkpoint_data: Serialized checkpoint data string.

        Note:
            Only saves if enable_checkpoints is True in config.
        """
        if not self.enable_checkpoints:
            logger.debug("[LEGACY] Checkpoints disabled, skipping checkpoint save")
            return

        checkpoint_file = self.path / f"{run.run_id}.checkpoint"
        tmp_path = self.path / f".{run.run_id}.checkpoint.tmp"

        # Update checkpoint fields on the run record
        run.checkpoint_state = checkpoint_data
        run.last_checkpoint_at = datetime.now(UTC)
        run.checkpoint_sequence += 1

        # Clean up any stale tmp file from previous crash
        if tmp_path.exists():
            tmp_path.unlink()

        # Atomic write: write to tmp, then atomic rename
        tmp_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, checkpoint_file)

    def load_checkpoint(self, run_id: str) -> RunRecord | None:
        """Load a checkpoint if it exists for the given run.

        Args:
            run_id: The run ID to load checkpoint for.

        Returns:
            RunRecord if checkpoint exists and enabled, None otherwise.
        """
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

        Args:
            run_id: The run ID to check.

        Returns:
            True if checkpoint exists and enabled, False otherwise.
        """
        if not self.enable_checkpoints:
            return False
        return (self.path / f"{run_id}.checkpoint").exists()

    def delete_checkpoint(self, run_id: str) -> bool:
        """Delete a checkpoint for a run.

        Args:
            run_id: The run ID whose checkpoint to delete.

        Returns:
            True if checkpoint was deleted, False if it didn't exist.
        """
        checkpoint_file = self.path / f"{run_id}.checkpoint"
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            return True
        return False
