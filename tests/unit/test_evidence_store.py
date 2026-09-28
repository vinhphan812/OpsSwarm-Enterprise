"""Tests for EvidenceStore core functionality."""
import hashlib
import json

from opsswarm.evidence import EvidenceStore


def _sig(kind, payload):
    """Compute expected 16-char chained signature for a record."""
    stable = {k: v for k, v in payload.items()
              if k not in ("timestamp", "eid", "id", "run_id")}
    inp = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}"
    return hashlib.sha256(inp.encode()).hexdigest()[:16]


def _sig_chain(kind, payload, prev_sig):
    """Compute expected 16-char CHAINED signature for a record."""
    stable = {k: v for k, v in payload.items()
              if k not in ("timestamp", "eid", "id", "run_id")}
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
        """list() now fails closed on corrupt JSONL: raises MalformedEvidenceError."""
        from opsswarm.evidence import MalformedEvidenceError
        import pytest as _pytest
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-list-corrupt"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Manually write JSONL with a valid record + corrupt line + valid record.
        # Each record needs a correct CHAINED signature (C-02 fix requires this).
        sig1 = _sig_chain("finding", {"msg": "good"}, "GENESIS")
        sig2 = _sig_chain("finding", {"msg": "also good"}, sig1)
        p.write_text(
            json.dumps({"kind": "finding", "payload": {"msg": "good"}}) + f', "signature": "{sig1}"}}\n'
            'invalid json here\n'
            + json.dumps({"kind": "finding", "payload": {"msg": "also good"}}) + f', "signature": "{sig2}"}}\n',
        )

        # Fail closed: corrupt line raises rather than silently returning partial results
        with _pytest.raises(MalformedEvidenceError):
            ev.list(run_id)
        # Corrupt counter is incremented before raising
        assert ev._corrupt_count == 1
        # Corrupt line is moved to .corrupt sidecar
        corrupt_path = tmp_path / "evidence" / f"{run_id}.corrupt"
        assert corrupt_path.exists()

    def test_duplicate_count_tracked(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        ev.append("r1", "finding", {"x": 1})
        ev.append("r1", "finding", {"x": 1})
        ev.append("r1", "finding", {"x": 1})
        assert ev.get_duplicate_count() == 2


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

    def test_reload_skips_corrupt_lines(self, tmp_path):
        """Corrupt lines are now observable by raising MalformedEvidenceError."""
        from opsswarm.evidence import MalformedEvidenceError
        import pytest
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        run_id = "run-corrupt"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write a valid record with plain sig
        sig1 = _sig("finding", {"msg": "good"})
        p.write_text(json.dumps({
            "id": "EV-1", "kind": "finding", "payload": {"msg": "good"},
            "signature": sig1, "idempotency_key": "k1"
        }) + "\n")
        # Append corrupt line
        with p.open("a") as f:
            f.write("totally invalid json\n")
        # Load: should raise MalformedEvidenceError
        with pytest.raises(MalformedEvidenceError):
            ev.append(run_id, "finding", {"msg": "another"})

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
        assert ev._index.get(run_id) == set(index_before), \
            "Index must not be updated after a failed write"
        assert ev._last_signature.get(run_id) == chain_before, \
            "Chain head must not advance after a failed write"

    def test_malformed_jsonl_public_behavior(self, tmp_path):
        """list() must raise MalformedEvidenceError and not silently serve a
        partial audit trail when JSONL contains a corrupt line (r4111809778)."""
        from opsswarm.evidence import MalformedEvidenceError
        import pytest

        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "partial-list"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Use correct CHAINED signatures for S4.finding records (C-02 fix).
        sig1 = _sig_chain("S4.finding", {"task_id": "T1", "finding": "ok"}, "GENESIS")
        sig2 = _sig_chain("S4.finding", {"task_id": "T2", "finding": "ok2"}, sig1)
        p.write_text(
            json.dumps({"kind": "S4.finding", "payload": {"task_id": "T1", "finding": "ok"}, "signature": sig1}) + "\n"
            "not json at all\n"
            + json.dumps({"kind": "S4.finding", "payload": {"task_id": "T2", "finding": "ok2"}, "signature": sig2}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(MalformedEvidenceError):
            ev.list(run_id)
        assert ev._corrupt_count == 1
        assert (tmp_path / "evidence" / f"{run_id}.corrupt").exists()
