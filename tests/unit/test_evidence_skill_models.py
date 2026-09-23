"""Tests for evidence.py skill validation models (ADR-006 / SKILL_GATE_VALIDATOR_CONTRACT_SPEC)."""
import pytest
from opsswarm.evidence import (
    SkillValidationResult,
    EvidenceRecord,
    save_skill_evidence,
    load_skill_evidence,
)
from datetime import datetime, timezone


class TestSkillValidationResult:
    def test_creation(self):
        r = SkillValidationResult(skill_id="s1", static_pass=True)
        assert r.skill_id == "s1"
        assert r.static_pass is True
        assert r.runnable_pass is True
        assert r.coverage is None
        assert r.evidence_refs == []

    def test_full_result(self):
        r = SkillValidationResult(
            skill_id="s2",
            static_pass=True,
            static_errors=[],
            runnable_pass=True,
            tests_collected=24,
            tests_passed=24,
            coverage=95.0,
        )
        assert r.tests_collected == 24
        assert r.tests_passed == 24
        assert r.coverage == 95.0

    def test_with_errors(self):
        r = SkillValidationResult(
            skill_id="s3",
            static_pass=False,
            static_errors=["missing description"],
            runnable_pass=False,
            runnable_errors=["import error"],
        )
        assert r.static_pass is False
        assert "missing description" in r.static_errors


class TestSaveAndLoadSkillEvidence:
    def test_save_and_load(self, tmp_path):
        result = SkillValidationResult(
            skill_id="s1-intent-guard",
            static_pass=True,
            runnable_pass=True,
            tests_collected=24,
            tests_passed=24,
        )
        record = EvidenceRecord(
            run_id="test-run-1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor="skill-gates.yml",
            validation_mode="all",
            skills_validated=["s1-intent-guard"],
            results=[result],
            overall_pass=True,
        )
        path = save_skill_evidence(record, data_dir=str(tmp_path))
        assert path.exists()

        records = load_skill_evidence("test-run-1", data_dir=str(tmp_path))
        assert len(records) == 1
        assert records[0]["run_id"] == "test-run-1"
        assert records[0]["overall_pass"] is True
        assert records[0]["skills_validated"] == ["s1-intent-guard"]

    def test_load_nonexistent(self, tmp_path):
        records = load_skill_evidence("nonexistent-run", data_dir=str(tmp_path))
        assert records == []

    def test_multiple_records_same_run(self, tmp_path):
        for i in range(3):
            result = SkillValidationResult(skill_id=f"s{i+1}", static_pass=True)
            record = EvidenceRecord(
                run_id="multi-run",
                timestamp=datetime.now(timezone.utc).isoformat(),
                actor="test",
                validation_mode="static",
                skills_validated=[f"s{i+1}"],
                results=[result],
                overall_pass=True,
            )
            save_skill_evidence(record, data_dir=str(tmp_path))

        records = load_skill_evidence("multi-run", data_dir=str(tmp_path))
        assert len(records) == 3

    def test_failing_validation_record(self, tmp_path):
        result = SkillValidationResult(
            skill_id="s99",
            static_pass=False,
            static_errors=["name field missing", "description field missing"],
        )
        record = EvidenceRecord(
            run_id="fail-run",
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor="skill-gates.yml",
            validation_mode="static",
            skills_validated=["s99"],
            results=[result],
            overall_pass=False,
            failures=["s99 static validation failed"],
        )
        path = save_skill_evidence(record, data_dir=str(tmp_path))
        records = load_skill_evidence("fail-run", data_dir=str(tmp_path))
        assert records[0]["overall_pass"] is False
        assert len(records[0]["failures"]) == 1
