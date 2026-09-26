"""Tests for EvidenceStore core functionality."""
import hashlib
import json

from opsswarm.evidence import EvidenceStore


def _sig(kind, payload):
    """Compute expected 16-char signature for a record."""
    stable = {k: v for k, v in payload.items()
              if k not in ("timestamp", "eid", "id", "run_id")}
    inp = f"{kind}:{json.dumps(stable, sort_keys=True, default=str)}"
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
        ev = EvidenceStore(data_dir=tmp_path)
        run_id = "run-list-corrupt"
        p = tmp_path / "evidence" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Manually write JSONL with a malformed line
        p.write_text('{"kind": "finding", "payload": {"msg": "good"}}\n'
                     'invalid json here\n'
                     '{"kind": "finding", "payload": {"msg": "also good"}}\n')

        records = ev.list(run_id)
        assert len(records) == 2
        assert records[0]["payload"]["msg"] == "good"
        assert records[1]["payload"]["msg"] == "also good"
        assert ev._corrupt_count == 1

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
