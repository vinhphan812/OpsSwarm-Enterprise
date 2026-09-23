"""Reconciliation and crash recovery for OpsSwarm runs.

This module provides:
- Reconciliation report generation: comparing evidence logs with expected sequences
- Run recovery: loading non-terminal runs on startup and resuming from checkpoints
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence import EvidenceStore
from .models import RunRecord, RunState, TERMINAL_STATES
from .store import RunStore

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationReport:
    """Report of reconciliation analysis for a run."""
    run_id: str
    total_records: int
    unique_idempotency_keys: int
    duplicates_skipped: int
    evidence_kinds: list[str]
    gaps_detected: list[str]
    last_evidence_timestamp: datetime | None
    generated_at: datetime


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    run_id: str
    recovered: bool
    resume_from_checkpoint: bool
    checkpoint_sequence: int | None
    state_at_recovery: RunState
    message: str


class ReconciliationManager:
    """Manages reconciliation reports and crash recovery for runs."""

    def __init__(self, data_dir: str):
        self.store = RunStore(data_dir)
        self.evidence = EvidenceStore(data_dir)
        self.data_dir = Path(data_dir)

    def reconcile(self, run_id: str) -> ReconciliationReport:
        """Generate a reconciliation report for a run.
        
        Compares the evidence log with expected sequence and reports:
        - Total evidence records
        - Unique idempotency keys
        - Duplicates found and skipped
        - Evidence kinds present
        - Gaps detected in the sequence
        
        Args:
            run_id: The run identifier to reconcile.
            
        Returns:
            ReconciliationReport with analysis results.
        """
        evidence_records = self.evidence.list(run_id)

        if not evidence_records:
            return ReconciliationReport(
                run_id=run_id,
                total_records=0,
                unique_idempotency_keys=0,
                duplicates_skipped=0,
                evidence_kinds=[],
                gaps_detected=["No evidence records found"],
                last_evidence_timestamp=None,
                generated_at=datetime.now(timezone.utc)
            )

        # Count records and unique idempotency keys
        total_records = len(evidence_records)
        idempotency_keys: set[str] = set()
        duplicates_skipped = 0

        for rec in evidence_records:
            key = rec.get("idempotency_key", "")
            if key:
                if key in idempotency_keys:
                    duplicates_skipped += 1
                else:
                    idempotency_keys.add(key)

        # Extract evidence kinds
        evidence_kinds = list(set(rec.get("kind", "unknown") for rec in evidence_records))

        # Detect gaps in evidence sequence
        gaps_detected = self._detect_gaps(evidence_records)

        # Get last evidence timestamp
        timestamps = [rec.get("timestamp") for rec in evidence_records if rec.get("timestamp")]
        last_timestamp = None
        if timestamps:
            try:
                last_timestamp = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return ReconciliationReport(
            run_id=run_id,
            total_records=total_records,
            unique_idempotency_keys=len(idempotency_keys),
            duplicates_skipped=duplicates_skipped,
            evidence_kinds=sorted(evidence_kinds),
            gaps_detected=gaps_detected,
            last_evidence_timestamp=last_timestamp,
            generated_at=datetime.now(timezone.utc)
        )

    def _detect_gaps(self, evidence_records: list[dict[str, Any]]) -> list[str]:
        """Detect gaps in the evidence sequence.
        
        Args:
            evidence_records: List of evidence records to analyze.
            
        Returns:
            List of gap descriptions.
        """
        gaps = []

        # Check for expected evidence kinds based on run state
        kinds_present = set(rec.get("kind", "") for rec in evidence_records)

        # Expected evidence kinds in typical flow
        expected_kinds = [
            "S1.incident",
            "S2.task_graph",
            "S4.finding",
            "RCA.root_cause",
            "S3.recovery_plan",
            "S5.execution",
            "S7.verification"
        ]

        # Check for missing expected evidence
        for expected in expected_kinds:
            if expected not in kinds_present:
                gaps.append(f"Missing expected evidence kind: {expected}")

        # Check for gaps in finding sequence
        finding_count = sum(1 for rec in evidence_records if rec.get("kind") == "S4.finding")
        task_graph_records = [rec for rec in evidence_records if rec.get("kind") == "S2.task_graph"]

        if task_graph_records:
            try:
                task_data = task_graph_records[0].get("payload", {})
                expected_findings = len(task_data.get("tasks", []))
                if finding_count < expected_findings:
                    gaps.append(f"Expected {expected_findings} findings, found {finding_count}")
            except (KeyError, TypeError):
                pass

        return gaps

    def load_non_terminal_runs(self) -> list[RunRecord]:
        """Load all non-terminal runs for recovery.
        
        On startup, this loads all runs that are not in terminal states
        (RESOLVED, FAILED, ABORTED) and can be resumed.
        
        Returns:
            List of RunRecord objects that can be recovered.
        """
        all_runs = self.store.load_all()
        non_terminal = []

        for run in all_runs:
            if run.state not in TERMINAL_STATES:
                non_terminal.append(run)
                logger.info(f"Found non-terminal run {run.run_id} in state {run.state.value}")
            else:
                logger.debug(f"Skipping terminal run {run.run_id} in state {run.state.value}")

        return non_terminal

    def recover_run(self, run: RunRecord) -> RecoveryResult:
        """Attempt to recover a run from its checkpoint.
        
        Args:
            run: The RunRecord to recover.
            
        Returns:
            RecoveryResult with recovery status and details.
        """
        run_id = run.run_id

        # Check if checkpoint exists
        if self.store.has_checkpoint(run_id):
            checkpoint = self.store.load_checkpoint(run_id)
            if checkpoint:
                return RecoveryResult(
                    run_id=run_id,
                    recovered=True,
                    resume_from_checkpoint=True,
                    checkpoint_sequence=checkpoint.checkpoint_sequence,
                    state_at_recovery=checkpoint.state,
                    message=f"Recovered from checkpoint sequence {checkpoint.checkpoint_sequence}"
                )

        # No checkpoint - check if we can resume from evidence
        evidence_records = self.evidence.list(run_id)
        if evidence_records:
            return RecoveryResult(
                run_id=run_id,
                recovered=True,
                resume_from_checkpoint=False,
                checkpoint_sequence=None,
                state_at_recovery=run.state,
                message=f"Resuming from evidence log ({len(evidence_records)} records)"
            )

        # No checkpoint or evidence - but the run record exists
        # This is valid for a fresh non-terminal run that hasn't produced evidence yet
        return RecoveryResult(
            run_id=run_id,
            recovered=True,
            resume_from_checkpoint=False,
            checkpoint_sequence=None,
            state_at_recovery=run.state,
            message="Resuming from saved run state"
        )

    def get_recovery_plan(self, run: RunRecord) -> dict[str, Any]:
        """Generate a recovery plan for a run.
        
        Args:
            run: The RunRecord to plan recovery for.
            
        Returns:
            Dictionary with recovery plan details.
        """
        run_id = run.run_id

        # Get reconciliation report
        report = self.reconcile(run_id)

        # Determine recovery strategy
        has_checkpoint = self.store.has_checkpoint(run_id)
        has_evidence = report.total_records > 0

        strategy = "unknown"
        if has_checkpoint:
            strategy = "checkpoint"
        elif has_evidence:
            strategy = "evidence_replay"
        else:
            strategy = "manual_intervention"

        return {
            "run_id": run_id,
            "current_state": run.state.value,
            "recovery_strategy": strategy,
            "has_checkpoint": has_checkpoint,
            "checkpoint_sequence": run.checkpoint_sequence if has_checkpoint else None,
            "evidence_records": report.total_records,
            "evidence_kinds": report.evidence_kinds,
            "gaps_detected": report.gaps_detected,
            "duplicates_skipped": report.duplicates_skipped,
            "recommendation": self._get_recovery_recommendation(report, has_checkpoint)
        }

    def _get_recovery_recommendation(self, report: ReconciliationReport, has_checkpoint: bool) -> str:
        """Get recovery recommendation based on reconciliation report."""
        if has_checkpoint:
            return "Resume from checkpoint - most reliable recovery path"

        if report.total_records == 0:
            return "No evidence found - manual investigation required"

        if report.gaps_detected:
            return f"Resume from evidence with gaps: {', '.join(report.gaps_detected[:2])}"

        return "Resume from evidence log - replay from last known state"
