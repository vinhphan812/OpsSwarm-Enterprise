"""Tests for opsswarm.evidence EvidenceStore checkpoint and list methods."""
import pytest
from opsswarm.evidence import EvidenceStore
from pathlib import Path


class TestEvidenceStoreCheckpoint:
    def test_checkpoint_recorded(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        eid = ev.checkpoint("run1", "STATE_TRANSITION", {"state": "WAITING_APPROVAL"})
        assert eid is not None
        cp = ev.get_last_checkpoint("run1")
        assert cp is not None
        assert cp["kind"] == "checkpoint"
        assert cp["payload"]["checkpoint_type"] == "STATE_TRANSITION"

    def test_checkpoint_none_for_missing_run(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        assert ev.get_last_checkpoint("nonexistent") is None

    def test_checkpoint_multiple_returns_last(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        ev.checkpoint("run2", "STATE_TRANSITION", {"state": "INVESTIGATING"})
        ev.checkpoint("run2", "HUMAN_GATE", {"state": "WAITING_APPROVAL"})
        ev.checkpoint("run2", "EXECUTION", {"state": "EXECUTING"})
        cp = ev.get_last_checkpoint("run2")
        assert cp["payload"]["checkpoint_type"] == "EXECUTION"


class TestEvidenceStoreList:
    def test_list_empty_run(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        assert ev.list("nonexistent") == []

    def test_list_returns_all_evidence(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path)
        ev.append("run3", "finding", {"msg": "test1"})
        ev.append("run3", "finding", {"msg": "test2"})
        ev.append("run3", "checkpoint", {"checkpoint_type": "STATE"})
        items = ev.list("run3")
        assert len(items) == 3

    def test_duplicate_count(self, tmp_path):
        ev = EvidenceStore(data_dir=tmp_path, enable_idempotency=True)
        ev.append("run4", "finding", {"msg": "same"})
        ev.append("run4", "finding", {"msg": "same"})
        assert ev.get_duplicate_count() == 1
