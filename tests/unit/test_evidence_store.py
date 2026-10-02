"""Tests for EvidenceStore core functionality."""

import hashlib
import json

from opsswarm.evidence import EvidenceStore


def _sig(kind, payload):
    """Compute expected 16-char chained signature for a record."""
    stable = {k: v for k, v in payload.items() if k not in ("timestamp", "eid", "id", "run_id")}
    inp = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}"
    return hashlib.sha256(inp.encode()).hexdigest()[:16]


def _sig_chain(kind, payload, prev_sig):
    """Compute expected 16-char CHAINED signature for a record."""
    stable = {k: v for k, v in payload.items() if k not in ("timestamp", "eid", "id", "run_id")}
    inp = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}:{prev_sig}"
    return hashlib.sha256(inp.encode()).hexdigest()[:16]


class TestEvidenceStoreCore:
    """Core EvidenceStore append/list/dedup tests."""

    def test_append_returns_eid_and_not_dup(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        eid, dup = ev.append("r1", "finding", {"msg": "hello"})
        assert eid is not None
        assert dup is False

    def test_duplicate_is_skipped(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        ev.append("r1", "finding", {"msg": "same"})
        _, dup2 = ev.append("r1", "finding", {"msg": "same"})
        assert dup2 is True

    def test_list_returns_all(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        ev.append("r1", "finding", {"n": 1})
        ev.append("r1", "finding", {"n": 2})
        records = ev.list("r1")
        assert len(records) == 2

    def test_list_skips_corrupt_lines(self, tmp_path):
        """list() continues through corrupt JSONL rows per ADR-009-1 tolerant mode:
        - no exception is raised
        - corrupt line is written to .corrupt sidecar
        - _corrupt_count is incremented
        - valid records before and after the corrupt line are returned"""
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-list-corrupt"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Manually write JSONL with a valid record + corrupt line + valid record.
        # Each record needs a correct CHAINED signature (C-02 fix requires this).
        sig1 = _sig_chain("S4.finding", {"task_id": "t1", "finding": "good"}, "GENESIS")
        sig2 = _sig_chain("S4.finding", {"task_id": "t2", "finding": "also good"}, sig1)
        rec1 = json.dumps({"kind": "S4.finding", "payload": {"task_id": "t1", "finding": "good"}, "signature": sig1})
        rec2 = json.dumps({"kind": "S4.finding", "payload": {"task_id": "t2", "finding": "also good"}, "signature": sig2})
        p.write_text("\n".join([rec1, "invalid json here", rec2, ""]))

        # ADR-009-1 tolerant mode: no exception raised; valid records returned
        records = ev.list(run_id)
        assert len(records) == 2
        assert records[0]["payload"]["task_id"] == "t1"
        assert records[1]["payload"]["task_id"] == "t2"
        # Corrupt counter is incremented
        assert ev._corrupt_count == 1
        # Corrupt line is moved to .corrupt sidecar
        corrupt_path = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt_path.exists()
        assert "invalid json here" in corrupt_path.read_text(encoding="utf-8")

    def test_duplicate_count_tracked(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        ev.append("r1", "finding", {"x": 1})
        ev.append("r1", "finding", {"x": 1})
        ev.append("r1", "finding", {"x": 1})
        assert ev.get_duplicate_count() == 2

    def test_tolerant_mode_continues_through_corrupt_jsonl(self, tmp_path):
        """ADR-009-1 tolerant mode (issue #28): append() and list() continue through
        malformed JSONL rows, log as WARNING with ADR-009-1 note, write corrupt rows to
        .corrupt sidecar, and preserve chain continuity for valid records."""
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-tolerant-28"

        # --- Phase 1: append two valid records, then inject a corrupt line ---
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "good"})
        ev.append(run_id, "S4.finding", {"task_id": "T2", "finding": "also good"})

        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write("this is not json\n")

        # --- Phase 2: append a third record after the corrupt line ---
        eid3, dup3 = ev.append(run_id, "S4.finding", {"task_id": "T3", "finding": "third"})
        assert eid3 is not None
        assert dup3 is False
        # _corrupt_count was incremented during reload inside append()
        assert ev._corrupt_count == 1
        # .corrupt sidecar exists with the bad line
        corrupt_path = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt_path.exists()
        assert "this is not json" in corrupt_path.read_text(encoding="utf-8")

        # --- Phase 3: list() also tolerates the corrupt line ---
        records = ev.list(run_id)
        # Returns only the two valid records; corrupt line is skipped
        assert len(records) == 3
        assert [r["payload"]["task_id"] for r in records] == ["T1", "T2", "T3"]
        # Chain is unbroken: all three records have consistent chained signatures
        assert all(r["signature"] for r in records)


class TestEvidenceStoreReload:
    """Test that append() correctly reloads existing JSONL on first append."""

    def test_reload_deduplicates_on_restart(self, tmp_path):
        """Simulating a restart: existing JSONL is reloaded and prevents duplicates."""
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        run_id = "run-reload"
        ev.append(run_id, "finding", {"msg": "first"})
        ev.append(run_id, "finding", {"msg": "second"})
        # Simulate restart: new store reads the existing JSONL
        ev2 = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        _, dup = ev2.append(run_id, "finding", {"msg": "first"})
        assert dup is True  # "first" sig already known

    def test_reload_tolerates_corrupt_lines(self, tmp_path):
        """ADR-009-1 tolerant mode: corrupt JSONL lines during reload are logged as
        WARNING, written to .corrupt sidecar, and do not prevent appending new records."""
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        run_id = "run-corrupt"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write a valid record with a CHAINED signature (prev_sig="GENESIS")
        sig1 = _sig_chain("finding", {"msg": "good"}, "GENESIS")
        p.write_text(
            json.dumps(
                {
                    "id": "EV-1",
                    "kind": "finding",
                    "payload": {"msg": "good"},
                    "signature": sig1,
                    "idempotency_key": "k1",
                }
            )
            + "\n"
        )
        # Append corrupt line
        with p.open("a") as f:
            f.write("totally invalid json\n")
        # Reload with tolerant mode: no exception raised; corrupt count incremented
        ev2 = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        assert ev2._corrupt_count == 0  # fresh store
        # Trigger reload by appending
        eid, dup = ev2.append(run_id, "finding", {"msg": "another"})
        # Append succeeded (tolerant mode)
        assert eid is not None
        assert dup is False
        # Corrupt line was detected during reload
        assert ev2._corrupt_count == 1
        corrupt_path = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt_path.exists()
        assert "totally invalid json" in corrupt_path.read_text(encoding="utf-8")

    def test_last_signature_tracked(self, tmp_path):
        """_last_signature is updated after append."""
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        run_id = "run-chain"
        ev.append(run_id, "checkpoint", {"state": "OPEN"})
        ev.append(run_id, "checkpoint", {"state": "DIAGNOSED"})
        assert run_id in ev._last_signature
        # Stored signature is always 16-char hex
        assert len(ev._last_signature[run_id]) == 16
        assert ev._last_signature[run_id].isalnum()


class TestEvidenceIntegrityRegression:
    """Regression tests for discussion_r4111809761 (chain verification) and
    discussion_r4111809967 (write-before-index ordering)."""

    def test_tampered_payload_detected_on_reload(self, tmp_path):
        """A record whose payload was mutated after writing must be detected
        during reload because the recomputed chain sig won't match stored."""
        from opsswarm.evidence import MalformedEvidenceError
        import pytest

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "tamper-reload"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "original"})
        ev.append(run_id, "S4.finding", {"task_id": "T2", "finding": "second"})

        # Tamper the first record in the JSONL file
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["payload"]["finding"] = "TAMPERED"
        lines[0] = json.dumps(first)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # A new store loading this run must detect chain breakage
        ev2 = EvidenceStore(data_dir=tmp_path)
        with pytest.raises(MalformedEvidenceError, match="chain broken|chain"):
            ev2.append(run_id, "S4.finding", {"task_id": "T3", "finding": "new"})

    def test_broken_predecessor_signature_detected(self, tmp_path):
        """A record whose stored signature field itself was mutated must be
        detected on reload — recomputed sig differs from the stored one."""
        from opsswarm.evidence import MalformedEvidenceError
        import pytest

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "broken-sig"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "ok"})
        ev.append(run_id, "S4.finding", {"task_id": "T2", "finding": "ok2"})

        # Corrupt the stored signature of the second record
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        rec2 = json.loads(lines[1])
        rec2["signature"] = "deadbeefdeadbeef"  # wrong hex
        lines[1] = json.dumps(rec2)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ev2 = EvidenceStore(data_dir=tmp_path)
        with pytest.raises(MalformedEvidenceError):
            ev2.append(run_id, "S4.finding", {"task_id": "T3", "finding": "new"})

    def test_append_failure_rollback_index_untouched(self, tmp_path):
        """If the durable write fails the in-memory index must not be updated,
        so a retry attempt is not mistakenly treated as a duplicate."""
        import unittest.mock as mock
        import pytest
        from pathlib import Path

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "rollback-run"
        ev.append(run_id, "S4.finding", {"task_id": "T1", "finding": "first"})

        # Snapshot index state before the failing write
        index_before = frozenset(ev._index.get(run_id, set()))
        chain_before = ev._last_signature.get(run_id)

        # Patch Path.open at the module level so only the JSONL write fails
        original_open = Path.open

        def failing_open(self_path, mode="r", **kwargs):
            if mode == "a" and str(self_path).endswith(".jsonl"):
                raise OSError("disk full")
            return original_open(self_path, mode, **kwargs)

        with mock.patch.object(Path, "open", failing_open):
            with pytest.raises(OSError):
                ev.append(run_id, "S4.finding", {"task_id": "T2", "finding": "second"})

        # Index and chain head must be unchanged — retry is still possible
        assert ev._index.get(run_id) == set(index_before), (
            "Index must not be updated after a failed write"
        )
        assert ev._last_signature.get(run_id) == chain_before, (
            "Chain head must not advance after a failed write"
        )

    def test_list_continues_after_malformed_jsonl(self, tmp_path):
        """ADR-009-1 tolerant mode: list() does not raise on a corrupt JSONL line;
        it writes the corrupt line to .corrupt sidecar and continues, returning only
        valid records (r4111809778)."""
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "tolerant-list"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Use correct CHAINED signatures for S4.finding records (C-02 fix).
        sig1 = _sig_chain("S4.finding", {"task_id": "T1", "finding": "ok"}, "GENESIS")
        sig2 = _sig_chain("S4.finding", {"task_id": "T2", "finding": "ok2"}, sig1)
        p.write_text(
            json.dumps(
                {
                    "kind": "S4.finding",
                    "payload": {"task_id": "T1", "finding": "ok"},
                    "signature": sig1,
                }
            )
            + "\n"
            "not json at all\n"
            + json.dumps(
                {
                    "kind": "S4.finding",
                    "payload": {"task_id": "T2", "finding": "ok2"},
                    "signature": sig2,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        # Tolerant mode: no exception, valid records returned
        records = ev.list(run_id)
        assert len(records) == 2
        assert ev._corrupt_count == 1
        corrupt_path = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt_path.exists()
        assert "not json at all" in corrupt_path.read_text(encoding="utf-8")


class TestEvidenceVerify:
    """Tests for EvidenceStore.verify() — independent chain verification."""

    def test_verify_returns_valid_for_clean_chain(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-verify-clean"
        # Append two records
        ev.append(run_id, "checkpoint", {"phase": "start"})
        ev.append(run_id, "checkpoint", {"phase": "end"})
        valid, errors = ev.verify(run_id)
        assert valid is True
        assert errors == []

    def test_verify_returns_errors_for_tampered_chain(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-verify-tampered"
        ev.append(run_id, "checkpoint", {"phase": "start"})
        # Tamper the file: change payload after signature was computed
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"phase": "start"', '"phase": "HACKED"')
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        valid, errors = ev.verify(run_id)
        assert valid is False
        assert len(errors) == 1
        assert "chain broken" in errors[0]

    def test_verify_returns_errors_for_missing_file(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        valid, errors = ev.verify("nonexistent-run")
        assert valid is False
        assert "No evidence file" in errors[0]

    def test_verify_rejects_non_mapping_json_records(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-verify-shape"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.write_text("[]\n42\n\"record\"\n", encoding="utf-8")

        valid, errors = ev.verify(run_id)

        assert valid is False
        assert len(errors) == 3
        assert all("mapping" in error for error in errors)

    def test_verify_rejects_non_mapping_payload(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-verify-payload-shape"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.write_text(
            json.dumps({"kind": "checkpoint", "payload": [], "signature": "bad"})
            + "\n"
            + json.dumps({"kind": "checkpoint", "payload": "bad", "signature": "bad"})
            + "\n",
            encoding="utf-8",
        )

        valid, errors = ev.verify(run_id)

        assert valid is False
        assert len(errors) == 2
        assert all("payload" in error and "mapping" in error for error in errors)

    def test_verify_continues_after_malformed_rows(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-verify-malformed"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.write_text(
            "not json\n"
            + json.dumps({"kind": "checkpoint", "payload": {}, "signature": ""})
            + "\n",
            encoding="utf-8",
        )

        valid, errors = ev.verify(run_id)

        assert valid is False
        assert len(errors) == 2
        assert "Malformed JSONL" in errors[0]
        assert "invalid signature" in errors[1]
