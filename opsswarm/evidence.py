from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MalformedEvidenceError(Exception):
    """Raised when evidence record is malformed in a way that breaks integrity."""
    pass

# Signature key fields per event kind (from ADR-009-4)
SIGNATURE_KEY_FIELDS: dict[str, list[str]] = {
    "S1.incident": ["issue_number", "service"],
    "S2.task_graph": ["task_ids", "types"],
    "S4.finding": ["task_id", "finding"],
    "RCA.root_cause": ["proximate_cause", "root_cause"],
    "S3.recovery_plan": ["option_ids"],
    "S5.execution": ["option_id", "summary"],
    "S7.verification": ["verified", "summary"],
    "human.approval": ["actor", "option"],
    "human.input": ["actor", "text"],
}


class EvidenceStore:
    def __init__(self, data_dir: str, enable_idempotency: bool = True,
                 persistence_config: dict[str, Any] | None = None):
        """Initialize the evidence store.

        Args:
            data_dir: Directory to store evidence logs.
            enable_idempotency: Enable idempotency checks (default True).
            persistence_config: Full persistence config dict for feature flag checks.
        """
        self.path = Path(data_dir) / "evidence"
        self.path.mkdir(parents=True, exist_ok=True)

        # Feature flags from config
        self.persistence_config = persistence_config or {}
        self.enable_idempotency = self.persistence_config.get("enable_idempotency", enable_idempotency)

        # In-memory index for seen signatures (payload-based): {run_id: set of signatures}
        self._index: dict[str, set[str]] = {}
        # Last signature for hash chaining: {run_id: last_signature}
        self._last_signature: dict[str, str] = {}
        # Concurrency lock
        self._lock = threading.Lock()

        # Duplicate counter for logging
        self._duplicate_count: int = 0
        # Corruption counter for logging
        self._corrupt_count: int = 0

        # Log warnings for legacy mode
        if not self.enable_idempotency:
            logger.warning("[LEGACY] Idempotency disabled - duplicate evidence may be stored")

    def _signature(self, kind: str, payload: dict[str, Any]) -> str:
        """Calculate stable signature for duplicate detection (payload-based)."""
        # Get key fields for this kind, or use all non-volatile fields
        key_fields = SIGNATURE_KEY_FIELDS.get(kind)
        if key_fields is None:
            # Fallback: exclude volatile fields
            stable = {k: v for k, v in payload.items()
                      if k not in ('timestamp', 'eid', 'id', 'run_id')}
        else:
            # Use kind-specific key fields
            stable = {k: payload.get(k) for k in key_fields if k in payload}

        # Create stable JSON for hashing
        sig_input = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}"
        return hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]

    def _signature_with_chain(self, kind: str, payload: dict[str, Any], prev_sig: str) -> str:
        """Calculate stable signature for tamper-evidency (chained)."""
        # Get key fields for this kind, or use all non-volatile fields
        key_fields = SIGNATURE_KEY_FIELDS.get(kind)
        if key_fields is None:
            # Fallback: exclude volatile fields
            stable = {k: v for k, v in payload.items()
                      if k not in ('timestamp', 'eid', 'id', 'run_id')}
        else:
            # Use kind-specific key fields
            stable = {k: payload.get(k) for k in key_fields if k in payload}

        # Create stable JSON for hashing
        # Include prev_sig for tamper-evidency chain
        sig_input = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}:{prev_sig}"
        return hashlib.sha256(sig_input.encode("utf-8")).hexdigest()[:16]

    def _compute_idempotency_key(self, event_id: str | None, run_id: str, kind: str) -> str:
        """Compute idempotency key from event_id, run_id, and kind."""
        if event_id is None:
            return ""
        key_input = f"{event_id}:{run_id}:{kind}"
        return hashlib.sha256(key_input.encode("utf-8")).hexdigest()

    def append(self, run_id: str, kind: str, payload: dict[str, Any], event_id: str | None = None) -> tuple[
        str | None, bool]:
        """Append evidence to the log with signature-based deduplication and tamper-evidence.

        Deduplication is based on the payload signature.
        The audit log signature is a rolling hash chain.

        Args:
            run_id: The run identifier.
            kind: The type of evidence (e.g., 'finding', 'verification').
            payload: The evidence payload data.
            event_id: Optional event identifier for idempotency key computation.

        Returns:
            Tuple of (evidence_id, is_duplicate):
            - Evidence ID if appended, None if skipped
            - True if this was a duplicate (skipped), False if new evidence
        """
        with self._lock:
            # Initialize run in index if needed
            if run_id not in self._index:
                self._index[run_id] = set()
                # Load existing signatures and last signature from disk for this run
                self._load_existing_signatures(run_id)

            # Calculate signature for duplicate detection (payload-only)
            sig_payload = self._signature(kind, payload)

            # Check for duplicate using in-memory index
            if self.enable_idempotency and sig_payload in self._index[run_id]:
                # Skip duplicate evidence
                self._duplicate_count += 1
                logger.debug(f"Skipping duplicate evidence (payload signature: {sig_payload})")
                return None, True

            # Get previous signature (or Genesis)
            prev_sig = self._last_signature.get(run_id, "GENESIS")

            # Calculate signature for audit (chained)
            sig_chain = self._signature_with_chain(kind, payload, prev_sig=prev_sig)

            # Add signature to index
            self._index[run_id].add(sig_payload)
            # Update last signature
            self._last_signature[run_id] = sig_chain

            # Compute idempotency key if event_id is provided
            idempotency_key = ""
            if self.enable_idempotency and event_id is not None:
                idempotency_key = self._compute_idempotency_key(event_id, run_id, kind)

            eid = f"EV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
            rec = {
                "id": eid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "kind": kind,
                "payload": payload,
                "signature": sig_chain,  # Store signature for audit
            }
            # Add idempotency_key to record if computed
            if idempotency_key:
                rec["idempotency_key"] = idempotency_key

            with (self.path / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            return eid, False

    def _load_existing_signatures(self, run_id: str) -> None:
        """Load all existing signatures for a run into the in-memory index and update last_signature."""
        p = self.path / f"{run_id}.jsonl"
        if not p.exists():
            return
        # Ensure run_id exists in index
        if run_id not in self._index:
            self._index[run_id] = set()

        last_sig = "GENESIS"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                try:
                    rec = json.loads(line)
                    # Re-derive payload signature for deduplication index
                    sig_payload = self._signature(rec.get("kind", ""), rec.get("payload", {}))
                    self._index[run_id].add(sig_payload)
                    # Use stored chained signature for audit chain
                    sig_chain = rec.get("signature", "")
                    if sig_chain:
                        last_sig = sig_chain
                except json.JSONDecodeError as e:
                    self._corrupt_count += 1
                    logger.error(f"Malformed JSONL row in evidence for run {run_id} at line {i + 1}")
                    # Move to corrupt file
                    corrupt_path = self.path / f"{run_id}.corrupt"
                    with corrupt_path.open("a", encoding="utf-8") as cf:
                        cf.write(line + "\n")
                    raise MalformedEvidenceError(f"Malformed JSONL row in evidence for run {run_id} at line {i + 1}") from e
        self._last_signature[run_id] = last_sig

    def get_duplicate_count(self) -> int:
        """Get the number of duplicate evidence events skipped."""
        return self._duplicate_count

    def list(self, run_id: str) -> list[dict[str, Any]]:
        p = self.path / f"{run_id}.jsonl"
        if not p.exists(): return []

        records = []
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                self._corrupt_count += 1
                logger.error(f"Malformed JSONL row in evidence for run {run_id} at line {i + 1}")
                # Move to corrupt file
                corrupt_path = self.path / f"{run_id}.corrupt"
                with corrupt_path.open("a", encoding="utf-8") as cf:
                    cf.write(line + "\n")
                continue
        return records

    def checkpoint(self, run_id: str, checkpoint_type: str, payload: dict[str, Any]) -> str:
        """Record a checkpoint event for recovery (ADR-009-3).

        Args:
            run_id: The run identifier.
            checkpoint_type: The type of checkpoint (STATE_TRANSITION, HUMAN_GATE, EXECUTION).
            payload: The checkpoint payload data (e.g., state, task progress, etc.).

        Returns:
            Evidence ID for the checkpoint event.
        """
        return self.append(run_id, "checkpoint", {
            "checkpoint_type": checkpoint_type,
            "payload": payload,
        })[0]

    def get_last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """Get the last checkpoint event for a run.

        Args:
            run_id: The run identifier.

        Returns:
            The last checkpoint event, or None if no checkpoints exist.
        """
        events = self.list(run_id)
        checkpoints = [e for e in events if e.get("kind") == "checkpoint"]
        if not checkpoints:
            return None
        return checkpoints[-1]


# =============================================================================
# Skill-Gate Validator Evidence Models (per SKILL_GATE_VALIDATOR_CONTRACT_SPEC)
# =============================================================================
#
from dataclasses import dataclass, field


@dataclass
class SkillValidationResult:
    """Result of skill validation for evidence recording."""
    skill_id: str
    static_pass: bool
    static_errors: list[str] = field(default_factory=list)
    runnable_pass: bool = True
    runnable_errors: list[str] = field(default_factory=list)
    tests_collected: int = 0
    tests_passed: int | None = None
    coverage: float | None = None
    cross_skill_valid: bool = True
    dependencies_valid: bool = True
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class EvidenceRecord:
    """Complete evidence record for skill validation runs."""
    run_id: str
    timestamp: str
    actor: str
    validation_mode: str  # "static", "runnable", or "all"
    skills_validated: list[str]
    results: list[SkillValidationResult]
    overall_pass: bool
    failures: list[str] = field(default_factory=list)


def save_skill_evidence(record: EvidenceRecord, data_dir: str | None = None) -> Path:
    """Save skill validation evidence to runtime-data/evidence/{run_id}.jsonl.

    Args:
        record: The evidence record to save.
        data_dir: Optional data directory override.

    Returns:
        Path to the saved evidence file.
    """
    if data_dir is None:
        # Default to runtime-data/evidence relative to this module
        data_dir = Path(__file__).parent.parent / "runtime-data" / "evidence"
    else:
        data_dir = Path(data_dir)

    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    output_path = evidence_dir / f"{record.run_id}.jsonl"

    # Convert dataclass to dict for JSON serialization
    record_dict = {
        "run_id": record.run_id,
        "timestamp": record.timestamp,
        "actor": record.actor,
        "validation_mode": record.validation_mode,
        "skills_validated": record.skills_validated,
        "results": [
            {
                "skill_id": r.skill_id,
                "static_pass": r.static_pass,
                "static_errors": r.static_errors,
                "runnable_pass": r.runnable_pass,
                "runnable_errors": r.runnable_errors,
                "tests_collected": r.tests_collected,
                "tests_passed": r.tests_passed,
                "coverage": r.coverage,
                "cross_skill_valid": r.cross_skill_valid,
                "dependencies_valid": r.dependencies_valid,
                "evidence_refs": r.evidence_refs,
            }
            for r in record.results
        ],
        "overall_pass": record.overall_pass,
        "failures": record.failures,
    }

    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record_dict, ensure_ascii=False, default=str) + "\n")

    return output_path


def load_skill_evidence(run_id: str, data_dir: str | None = None) -> list[dict[str, Any]]:
    """Load skill validation evidence from runtime-data/evidence/{run_id}.jsonl.

    Args:
        run_id: The run identifier to load.
        data_dir: Optional data directory override.

    Returns:
        List of evidence records.
    """
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "runtime-data" / "evidence"
    else:
        data_dir = Path(data_dir)

    evidence_dir = data_dir / "evidence"
    evidence_file = evidence_dir / f"{run_id}.jsonl"

    if not evidence_file.exists():
        return []

    records = []
    for line in evidence_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return records
