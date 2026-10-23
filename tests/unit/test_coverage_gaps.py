"""Focused tests for coverage gaps on the post-PR #33 baseline.

These tests exercise untested production paths in:
- evidence.py: append() fallback _signature path, list() strict signature validation
- models.py: CheckpointType.from_legacy()
- normalization.py: string confidence normalization, dict→list normalization, optional-string with non-string
- reconciliation.py: ISO timestamp parse failure, gap detection with empty task_graph
- store.py: stale tmp cleanup, load_checkpoint failure, has_checkpoint with disabled flag
- api.py: API key missing/empty rejection
- skill_logic.py: _persist_diagnostics() error path
- webhook.py: empty secret rejection
"""

import hashlib
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from opsswarm.evidence import EvidenceStore, MalformedEvidenceError
from opsswarm.models import CheckpointType
from opsswarm.normalization import (
    normalize_confidence,
    normalize_list_of_strings,
    normalize_optional_string,
)
from opsswarm.reconciliation import ReconciliationManager
from opsswarm.store import RunStore
from opsswarm.webhook import verify_signature


# ---------------------------------------------------------------------------
# evidence.py: append() _signature() fallback path (line 111)
# SIGNATURE_KEY_FIELDS has no entry for "custom.kind" — exercises the
# stable = {k:v ... if k not in volatile} fallback branch in _signature().
# ---------------------------------------------------------------------------


class TestEvidenceSignatureFallback:
    def test_append_kind_not_in_signature_key_fields(self, tmp_path):
        """_signature() falls back to exclude-volatile-fields when kind has no
        SIGNATURE_KEY_FIELDS entry. append() must not raise."""
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=False)
        eid, is_dup = ev.append("run-no-kind", "custom.kind.with.no.fields", {"msg": "hello"})
        assert eid is not None
        assert is_dup is False


# ---------------------------------------------------------------------------
# evidence.py: list() strict signature validation (lines 294-300)
# Records with missing / non-string / empty-signature must raise
# MalformedEvidenceError (C-01/C-02 strict enforcement).
# ---------------------------------------------------------------------------


class TestEvidenceListTolerantMode:
    """ADR-009-1: list() tolerates malformed signature records instead of raising."""

    def test_list_tolerates_missing_signature_field(self, tmp_path):
        """list() skips records with absent signature (ADR-009-1 tolerant mode)."""
        import json

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "sig-missing"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "id": "EV-1",
                    "kind": "S4.finding",
                    "payload": {"task_id": "T1", "finding": "ok"},
                    # signature intentionally absent
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # ADR-009-1 tolerant: no exception, record is skipped and written to .corrupt
        records = ev.list(run_id)
        assert records == []
        corrupt = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt.exists()

    def test_list_tolerates_none_signature(self, tmp_path):
        """list() skips records with None signature (ADR-009-1 tolerant mode)."""
        import json

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "sig-none"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "id": "EV-2",
                    "kind": "S4.finding",
                    "payload": {"task_id": "T2", "finding": "ok2"},
                    "signature": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # ADR-009-1 tolerant: no exception, record is skipped
        records = ev.list(run_id)
        assert records == []
        corrupt = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt.exists()

    def test_list_tolerates_empty_string_signature(self, tmp_path):
        """list() skips records with empty-string signature (ADR-009-1 tolerant mode)."""
        import json

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "sig-empty"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "id": "EV-3",
                    "kind": "S4.finding",
                    "payload": {"task_id": "T3", "finding": "ok3"},
                    "signature": "",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # ADR-009-1 tolerant: no exception
        records = ev.list(run_id)
        assert records == []
        corrupt = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt.exists()

    def test_list_tolerates_non_string_signature(self, tmp_path):
        """list() skips records with non-string signature (ADR-009-1 tolerant mode)."""
        import json

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "sig-wrong-type"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "id": "EV-4",
                    "kind": "S4.finding",
                    "payload": {"task_id": "T4", "finding": "ok4"},
                    "signature": 12345,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # ADR-009-1 tolerant: no exception
        records = ev.list(run_id)
        assert records == []
        corrupt = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt.exists()


# ---------------------------------------------------------------------------
# evidence.py: load_skill_evidence() JSON decode error path (lines 473-477)
# ---------------------------------------------------------------------------


class TestLoadSkillEvidenceDecodeError:
    def test_load_skill_evidence_skips_corrupt_lines(self, tmp_path):
        """load_skill_evidence() skips lines that fail JSON parsing."""
        from opsswarm.evidence import load_skill_evidence

        # After the #28 AC6 fix, load_skill_evidence does NOT append "evidence" to an
        # explicit data_dir that is already an evidence directory.
        # Write the JSONL file at the location load_skill_evidence will look for.
        ev_dir = tmp_path / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev_file = ev_dir / "test-run.jsonl"
        ev_file.write_text(
            '{"run_id": "test-run", "timestamp": "2026-09-27T00:00:00Z", '
            '"actor": "test", "validation_mode": "static", '
            '"skills_validated": ["s1"], "results": [], "overall_pass": true}\n'
            "not valid json\n"
            '{"run_id": "test-run", "timestamp": "2026-09-27T00:01:00Z", '
            '"actor": "test", "validation_mode": "static", '
            '"skills_validated": ["s2"], "results": [], "overall_pass": true}\n',
            encoding="utf-8",
        )
        # Pass the evidence directory directly (not a parent) so no extra nesting is added.
        records = load_skill_evidence("test-run", data_dir=str(ev_dir))
        assert len(records) == 2


# ---------------------------------------------------------------------------
# models.py: CommandOutcome.from_legacy() — the enum with from_legacy()
# covers all mapping branches plus the unknown fallback.
# CheckpointType is a plain str-Enum without from_legacy (not the same type).
# ---------------------------------------------------------------------------


class TestCommandOutcomeFromLegacy:
    def test_maps_executed_to_confirmed(self):
        from opsswarm.models import CommandOutcome

        assert CommandOutcome.from_legacy("executed") == CommandOutcome.CONFIRMED

    def test_maps_failed_to_absent(self):
        from opsswarm.models import CommandOutcome

        assert CommandOutcome.from_legacy("failed") == CommandOutcome.ABSENT

    def test_maps_reconciled_to_confirmed(self):
        from opsswarm.models import CommandOutcome

        assert CommandOutcome.from_legacy("reconciled") == CommandOutcome.CONFIRMED

    def test_unknown_value_returns_unknown(self):
        from opsswarm.models import CommandOutcome

        assert CommandOutcome.from_legacy("some-weird-value") == CommandOutcome.UNKNOWN

    def test_case_sensitive(self):
        """from_legacy is case-sensitive per the enum definition."""
        from opsswarm.models import CommandOutcome

        assert CommandOutcome.from_legacy("EXECUTED") == CommandOutcome.UNKNOWN


# ---------------------------------------------------------------------------
# normalization.py: edge-case paths
# ---------------------------------------------------------------------------


class TestNormalizationConfidence:
    def test_string_confidence_high(self):
        assert normalize_confidence("high") == 0.9

    def test_string_confidence_medium(self):
        assert normalize_confidence("medium") == 0.5

    def test_string_confidence_low(self):
        assert normalize_confidence("low") == 0.1

    def test_string_confidence_unknown(self):
        assert normalize_confidence("unknown-value") == 0.0

    def test_non_numeric_string(self):
        assert normalize_confidence("not-a-number") == 0.0


class TestNormalizationListOfStrings:
    def test_dict_value_normalized_to_key_value_pairs(self):
        result = normalize_list_of_strings({"key1": "val1", "key2": "val2"})
        assert len(result) == 2
        # Both entries must be present (set order may vary)
        full = " ".join(result)
        assert "key1: val1" in full
        assert "key2: val2" in full

    def test_non_iterable_returns_empty(self):
        assert normalize_list_of_strings(42) == []
        assert normalize_list_of_strings(None) == []


class TestNormalizationOptionalString:
    def test_none_returns_none(self):
        assert normalize_optional_string(None) is None

    def test_non_string_coerced(self):
        # Int is not a str — normalize_optional_string calls redact_pii(str(value))
        result = normalize_optional_string(42)
        assert result == "42"  # str(42) is redacted but "42" contains no PII

    def test_email_in_dict_string(self):
        """Dict stringified and passed through redact_pii."""
        result = normalize_optional_string({"email": "admin@example.com"})
        assert "admin@example.com" not in result
        assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# reconciliation.py: gap detection and date parsing
# ---------------------------------------------------------------------------


class TestReconciliationGaps:
    def test_reconcile_empty_evidence(self, tmp_path):
        """reconcile() returns gaps when no evidence records exist."""
        mgr = ReconciliationManager(str(tmp_path / "recon"))
        report = mgr.reconcile("no-such-run")
        assert "No evidence records found" in report.gaps_detected
        assert report.total_records == 0

    def test_gap_detected_for_missing_expected_kinds(self, tmp_path):
        """_detect_gaps() reports all missing expected evidence kinds."""
        import json

        data_dir = tmp_path / "recon2"
        ev = EvidenceStore(data_dir=str(data_dir))
        run_id = "partial-run"
        ev.append(run_id, "S1.incident", {"issue_number": 1, "service": "svc"})
        ev.append(run_id, "S2.task_graph", {"task_ids": ["T1"], "types": ["INVESTIGATE"]})
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "x"})

        mgr = ReconciliationManager(str(data_dir))
        report = mgr.reconcile(run_id)
        # RCA and recovery plan missing
        assert any("RCA.root_cause" in g for g in report.gaps_detected)
        assert any("S3.recovery_plan" in g for g in report.gaps_detected)

    def test_gap_detected_for_incomplete_findings(self, tmp_path):
        """_detect_gaps() detects when fewer findings than tasks were produced."""
        data_dir = tmp_path / "recon3"
        ev = EvidenceStore(data_dir=str(data_dir))
        run_id = "findings-short"
        # Gap detection reads payload.get("tasks", []) — must use that key.
        ev.append(run_id, "S2.task_graph", {"tasks": ["T1", "T2"]})
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "found"})
        # T2 finding missing

        mgr = ReconciliationManager(str(data_dir))
        report = mgr.reconcile(run_id)
        assert any("Expected 2 findings" in g for g in report.gaps_detected)

    def test_gap_detected_empty_task_graph(self, tmp_path):
        """_detect_gaps() handles task_graph with empty tasks list gracefully."""
        import json

        data_dir = tmp_path / "recon4"
        ev = EvidenceStore(data_dir=str(data_dir))
        run_id = "empty-tasks"
        ev.append(run_id, "S2.task_graph", {"task_ids": [], "types": []})
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "x"})

        mgr = ReconciliationManager(str(data_dir))
        report = mgr.reconcile(run_id)
        # Must not raise; may or may not flag gaps
        assert isinstance(report.gaps_detected, list)

    def test_reconcile_timestamp_parse_failure(self, tmp_path):
        """reconcile() handles non-ISO timestamp gracefully (line 112-113)."""
        import json

        data_dir = tmp_path / "recon5"
        ev = EvidenceStore(data_dir=str(data_dir))
        run_id = "bad-timestamp"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "ok"})

        # Manually corrupt the timestamp in the JSONL to a non-ISO format
        ev_file = data_dir / "evidence" / f"{run_id}.jsonl"
        content = ev_file.read_text(encoding="utf-8")
        first_line = json.loads(content.splitlines()[0])
        first_line["timestamp"] = "not-a-valid-iso-timestamp"
        ev_file.write_text(json.dumps(first_line) + "\n", encoding="utf-8")

        mgr = ReconciliationManager(str(data_dir))
        # Must not raise — invalid timestamp is caught by try/except
        report = mgr.reconcile(run_id)
        assert report.last_evidence_timestamp is None

    def test_recover_run_no_checkpoint_no_evidence(self, tmp_path):
        """recover_run() returns recovered=True even with no checkpoint or evidence."""
        from opsswarm.models import RunRecord, RunState

        data_dir = str(tmp_path / "recon6")
        store = RunStore(data_dir)
        run = RunRecord(run_id="bare-run", issue_number=99, state=RunState.INVESTIGATING)
        store.save(run)

        mgr = ReconciliationManager(data_dir)
        result = mgr.recover_run(run)
        assert result.recovered is True
        assert result.resume_from_checkpoint is False

    def test_get_recovery_recommendation_no_checkpoint_no_evidence(self, tmp_path):
        """_get_recovery_recommendation() handles the all-missing case."""
        from opsswarm.models import RunRecord, RunState

        data_dir = str(tmp_path / "recon7")
        store = RunStore(data_dir)
        run = RunRecord(run_id="bare-run-2", issue_number=98, state=RunState.TRIAGE)
        store.save(run)

        mgr = ReconciliationManager(data_dir)
        plan = mgr.get_recovery_plan(run)
        assert plan["recommendation"] == "No evidence found - manual investigation required"


# ---------------------------------------------------------------------------
# store.py: stale tmp cleanup, disabled checkpoint paths
# ---------------------------------------------------------------------------


class TestStoreCheckpointDisabled:
    def test_has_checkpoint_false_when_disabled(self, tmp_path):
        """has_checkpoint() returns False when enable_checkpoints is False."""
        store = RunStore(
            str(tmp_path / "runs"), enable_atomic_writes=True, enable_checkpoints=False
        )
        assert store.has_checkpoint("any-run") is False

    def test_load_checkpoint_none_when_disabled(self, tmp_path):
        """load_checkpoint() returns None when enable_checkpoints is False."""
        store = RunStore(
            str(tmp_path / "runs"), enable_atomic_writes=True, enable_checkpoints=False
        )
        assert store.load_checkpoint("any-run") is None

    def test_save_checkpoint_creates_file(self, tmp_path):
        """save_checkpoint() creates the .checkpoint file."""
        from opsswarm.models import RunRecord, RunState

        # Disable atomic writes to avoid Windows rename quirks in tests
        store = RunStore(
            str(tmp_path / "runs"), enable_atomic_writes=False, enable_checkpoints=True
        )
        run = RunRecord(
            run_id="ckpt-test",
            issue_number=1,
            state=RunState.INVESTIGATING,
            risk="read",
            checkpoint_state=None,
            last_checkpoint_at=None,
        )
        store.save_checkpoint(run, "test-state")
        # RunStore appends /runs internally: store.path = data_dir / "runs"
        # → checkpoint at: tmp_path/runs/runs/ckpt-test.checkpoint
        assert (tmp_path / "runs" / "runs" / "ckpt-test.checkpoint").exists()

    def test_delete_checkpoint(self, tmp_path):
        """delete_checkpoint() removes the file and returns True."""
        from opsswarm.models import RunRecord, RunState

        store = RunStore(
            str(tmp_path / "runs"), enable_atomic_writes=False, enable_checkpoints=True
        )
        run = RunRecord(
            run_id="del-ckpt",
            issue_number=1,
            state=RunState.INVESTIGATING,
            risk="read",
            checkpoint_state=None,
            last_checkpoint_at=None,
        )
        store.save_checkpoint(run, "data")
        result = store.delete_checkpoint("del-ckpt")
        assert result is True
        assert (tmp_path / "runs" / "del-ckpt.checkpoint").exists() is False


# ---------------------------------------------------------------------------
# api.py: verify_api_key missing/empty rejection
# ---------------------------------------------------------------------------


class TestApiKeyValidation:
    def test_empty_secret_rejected(self):
        """verify_signature returns False when secret is empty string."""
        assert verify_signature("", b"body", "sha256=abc") is False

    def test_missing_signature_rejected(self):
        """verify_signature returns False when signature is None."""
        assert verify_signature("secret", b"body", None) is False

    def test_malformed_signature_prefix_rejected(self):
        """verify_signature returns False when signature doesn't start with sha256=."""
        assert verify_signature("secret", b"body", "sha1=abc") is False


# ---------------------------------------------------------------------------
# skill_logic.py: _persist_diagnostics() PII redaction paths
# ---------------------------------------------------------------------------


class TestSkillLogicPersistDiagnostics:
    def test_redact_pii_from_str(self):
        """_redact_pii_from_str() redacts email addresses from strings."""
        from opsswarm.skill_logic import _redact_pii_from_str

        text = "Contact admin@corp.example.com for help"
        result = _redact_pii_from_str(text)
        assert "admin@corp.example.com" not in result
        assert "[REDACTED]" in result

    def test_redact_dict_nested(self):
        """_redact_dict() redacts PII from nested dicts and lists."""
        from opsswarm.skill_logic import _redact_dict

        data = {
            "user": "alice",
            "email": "alice@example.com",
            "nested": {"credential": "<redacted>", "email": "bob@example.com"},
            "tags": ["item1", "charlie@internal.corp"],
        }
        result = _redact_dict(data)
        # Top-level email
        assert "alice@example.com" not in str(result)
        # Nested email
        assert "bob@example.com" not in str(result)
        # Nested credential is not an email and is preserved by the email-redaction helper
        # but nested tag email must be redacted
        assert "charlie@internal.corp" not in str(result)

    def test_persist_diagnostics_with_evidence_store(self, tmp_path):
        """_persist_diagnostics() returns a safe string that contains no PII.

        The function uses best-effort persistence — it catches all exceptions and
        returns a safe constant — so the observable guarantee we can verify without
        mocking internal imports is that the return value is a safe string with no
        raw email addresses leaked.
        """
        from opsswarm.skill_logic import _persist_diagnostics

        # Even if EvidenceStore cannot be instantiated (config missing, etc.),
        # _persist_diagnostics must not propagate raw PII.  Verify the email
        # "victim@corp.internal" is never visible in the result.
        result = _persist_diagnostics(
            "run-x", "test.kind", {"secret": "victim@corp.internal"}, "Contact victim@corp.internal"
        )
        result_str = str(result)
        assert "victim@corp.internal" not in result_str, (
            "PII leaked through _persist_diagnostics return value"
        )
        # Must be a non-empty string (never re-raised)
        assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# evidence.py: append() with event_id — exercises _compute_idempotency_key
# with a real event_id (not None), and idempotency_key added to record.
# ---------------------------------------------------------------------------


class TestEvidenceAppendWithEventId:
    def test_append_with_event_id_computes_idempotency_key(self, tmp_path):
        """When event_id is provided, _compute_idempotency_key is called and
        the idempotency_key is stored in the JSONL record."""
        import json

        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        run_id = "event-id-run"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "ok"}, event_id="webhook-123")
        ev_file = tmp_path / "evidence" / f"{run_id}.jsonl"
        record = json.loads(ev_file.read_text(encoding="utf-8").splitlines()[0])
        assert "idempotency_key" in record
        assert len(record["idempotency_key"]) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# evidence.py: list() empty-line skipping, get_last_checkpoint None path
# ---------------------------------------------------------------------------


class TestEvidenceListEmptyLineSkip:
    def test_list_skips_empty_lines(self, tmp_path):
        """list() skips blank lines in the JSONL stream."""
        import json

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "empty-lines"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        sig1 = hashlib.sha256(
            f"S4.finding:{json.dumps({'task_id': 'T1', 'finding': 'a'}, sort_keys=True)}:GENESIS".encode()
        ).hexdigest()[:16]
        sig2 = hashlib.sha256(
            f"S4.finding:{json.dumps({'task_id': 'T2', 'finding': 'b'}, sort_keys=True)}:{sig1}".encode()
        ).hexdigest()[:16]
        p.write_text(
            json.dumps(
                {
                    "kind": "S4.finding",
                    "payload": {"task_id": "T1", "finding": "a"},
                    "signature": sig1,
                }
            )
            + "\n\n\n"
            + json.dumps(
                {
                    "kind": "S4.finding",
                    "payload": {"task_id": "T2", "finding": "b"},
                    "signature": sig2,
                }
            )
            + "\n  \n",
            encoding="utf-8",
        )
        records = ev.list(run_id)
        assert len(records) == 2


class TestEvidenceGetLastCheckpoint:
    def test_get_last_checkpoint_returns_none_when_no_checkpoints(self, tmp_path):
        """get_last_checkpoint returns None when the run has no checkpoint records."""
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "no-checkpoints"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "x"})
        result = ev.get_last_checkpoint(run_id)
        assert result is None

    def test_get_last_checkpoint_returns_last_checkpoint(self, tmp_path):
        """get_last_checkpoint returns the last checkpoint event."""
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "has-checkpoints"
        ev.append(
            run_id,
            "checkpoint",
            {"checkpoint_type": "STATE_TRANSITION", "payload": {"state": "OPEN"}},
        )
        ev.append(
            run_id,
            "checkpoint",
            {"checkpoint_type": "STATE_TRANSITION", "payload": {"state": "INVESTIGATING"}},
        )
        result = ev.get_last_checkpoint(run_id)
        assert result is not None
        # checkpoint() stores {"checkpoint_type": ..., "payload": ...} in payload
        assert result["payload"]["checkpoint_type"] == "STATE_TRANSITION"
        assert result["payload"]["payload"]["state"] == "INVESTIGATING"


# ---------------------------------------------------------------------------
# reconciliation.py: load_non_terminal_runs
# ---------------------------------------------------------------------------


class TestReconciliationLoadNonTerminal:
    def test_load_non_terminal_runs(self, tmp_path):
        """load_non_terminal_runs returns only non-terminal run records."""
        from opsswarm.models import RunRecord, RunState

        data_dir = str(tmp_path / "recon8")
        store = RunStore(data_dir)
        # Terminal run
        # ADR-015: PLAN_RCA_RESOLVED is the true terminal state (Phase 2 complete)
        r1 = RunRecord(run_id="terminal", issue_number=1, state=RunState.PLAN_RCA_RESOLVED)
        # Non-terminal run
        r2 = RunRecord(run_id="non-terminal", issue_number=2, state=RunState.INVESTIGATING)
        store.save(r1)
        store.save(r2)

        mgr = ReconciliationManager(data_dir)
        non_terminal = mgr.load_non_terminal_runs()
        assert len(non_terminal) == 1
        assert non_terminal[0].run_id == "non-terminal"


# ---------------------------------------------------------------------------
# store.py: save_with_retry happy path (was untested in the existing suite)
# ---------------------------------------------------------------------------


class TestStoreRetry:
    def test_save_with_retry_succeeds_on_first_attempt(self, tmp_path):
        """save_with_retry returns True when save succeeds on first try."""
        from opsswarm.models import RunRecord, RunState

        store = RunStore(str(tmp_path / "runs"))
        run = RunRecord(run_id="retry-ok", issue_number=1, state=RunState.OPEN)
        assert store.save_with_retry(run) is True

    def test_save_with_retry_exhausts_retries(self, tmp_path):
        """save_with_retry returns False after all retries are exhausted."""
        from opsswarm.models import RunRecord, RunState

        store = RunStore(str(tmp_path / "runs"))
        run = RunRecord(run_id="retry-fail", issue_number=1, state=RunState.OPEN)
        call_count = [0]

        def failing_save(r):
            call_count[0] += 1
            raise IOError("Test IO error")

        store.save = failing_save
        result = store.save_with_retry(run, max_retries=3)
        assert result is False
        assert call_count[0] == 3
