"""Regression tests for evidence path normalization (Issue #28 AC6).

ADR-011 contract: runtime-data/evidence/{run_id}.jsonl

These tests verify that save_skill_evidence() and load_skill_evidence()
agree on the correct file location in the two scenarios used by CI:

  1. Skill-gates CI step uses --evidence flag with data_dir=runtime-data/evidence
     (the validate_skill.py RUNTIME_DATA_DIR constant).
     Expected: save and load both resolve to runtime-data/evidence/{run_id}.jsonl

  2. EvidenceStore is configured with data_dir pointing to the project root or a
     parent dir.  It uses Path(data_dir) / "evidence" internally.
     Expected: skill evidence saves/loads match the EvidenceStore convention.

The fix ensures that when data_dir is already the evidence directory path
(ending with "evidence"), no additional "evidence" segment is appended.
"""
from datetime import datetime, timezone

from opsswarm.evidence import (
    SkillValidationResult,
    EvidenceRecord,
    save_skill_evidence,
    load_skill_evidence,
)


def _make_record(run_id: str) -> EvidenceRecord:
    result = SkillValidationResult(skill_id="s1", static_pass=True)
    return EvidenceRecord(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor="test",
        validation_mode="static",
        skills_validated=["s1"],
        results=[result],
        overall_pass=True,
    )


class TestSkillEvidencePathRegression:
    """Regression tests for save_skill_evidence / load_skill_evidence path agreement."""

    def test_parent_dir_save_and_load_symmetric(self, tmp_path):
        """Parent dir (tmp_path) saves to tmp_path/evidence/{run_id}.jsonl and loads it back.

        This is the common CI / docker scenario where data_dir is the project root.
        EvidenceStore uses Path(data_dir) / "evidence" internally, so skill evidence
        must follow the same convention: parent_dir/evidence/{run_id}.jsonl.
        """
        record = _make_record("parent-save")
        save_path = save_skill_evidence(record, data_dir=str(tmp_path))
        assert save_path.name == f"{record.run_id}.jsonl"
        assert save_path.exists()

        # Load using the same data_dir argument -- must find the file
        records = load_skill_evidence(record.run_id, data_dir=str(tmp_path))
        assert len(records) == 1
        assert records[0]["run_id"] == record.run_id

    def test_runtime_data_evidence_dir_no_double_nesting(self, tmp_path):
        """Auto-computed default path (runtime-data/evidence) must NOT double-nest.

        RUNTIME_DATA_DIR = runtime-data/evidence.
        Before fix: save to runtime-data/evidence/evidence/{run_id}.jsonl  [WRONG]
        After fix:  save to runtime-data/evidence/{run_id}.jsonl           [CORRECT]
        """
        runtime_data = tmp_path / "runtime-data"
        runtime_data.mkdir(parents=True, exist_ok=True)
        evidence_dir = runtime_data / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        record = _make_record("default-path")
        save_path = save_skill_evidence(record, data_dir=str(evidence_dir))
        assert save_path.parent == evidence_dir, (
            f"Expected save to {evidence_dir}/{{run_id}}.jsonl, got {save_path.parent}"
        )
        assert save_path.exists()

        # Load from same path must find the file
        records = load_skill_evidence(record.run_id, data_dir=str(evidence_dir))
        assert len(records) == 1

    def test_save_and_load_round_trip(self, tmp_path):
        """save and load must agree on file location regardless of data_dir shape."""
        record = _make_record("round-trip")
        save_path = save_skill_evidence(record, data_dir=str(tmp_path))
        assert save_path.name == f"{record.run_id}.jsonl"

        # Load using the same data_dir argument
        records = load_skill_evidence(record.run_id, data_dir=str(tmp_path))
        assert len(records) == 1
        assert records[0]["overall_pass"] is True
        assert records[0]["skills_validated"] == ["s1"]
