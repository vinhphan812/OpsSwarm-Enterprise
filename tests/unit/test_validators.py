"""Tests for opsswarm/validators.py — ADR-006 frontmatter validation."""
import pytest
from pathlib import Path
from opsswarm.validators import (
    REQUIRED_FIELDS,
    _get_skills_dir,
    load_skill_frontmatter,
    validate_skill_artefact,
)


class TestGetSkillsDir:
    def test_returns_skills_path(self):
        result = _get_skills_dir()
        assert isinstance(result, Path)
        assert result.name == "skills"


class TestLoadSkillFrontmatter:
    def test_loads_existing_skill(self):
        frontmatter = load_skill_frontmatter("s1-intent-guard")
        assert frontmatter is not None
        assert "name" in frontmatter
        assert "description" in frontmatter

    def test_returns_none_for_missing_skill(self):
        assert load_skill_frontmatter("s99-nonexistent") is None

    def test_loads_s2_skill(self):
        frontmatter = load_skill_frontmatter("s2-task-graph")
        assert frontmatter is not None
        assert "name" in frontmatter

    def test_loads_all_eight_skills(self):
        for i in range(1, 9):
            skill_id = f"s{i}-" + {
                1: "intent-guard",
                2: "task-graph",
                3: "horizon-plan",
                4: "role-dispatch",
                5: "collab-exec",
                6: "resilience-guard",
                7: "observe-verify",
                8: "orchestration-hub",
            }[i]
            fm = load_skill_frontmatter(skill_id)
            assert fm is not None, f"Failed to load {skill_id}"
            assert "name" in fm
            assert "description" in fm


class TestValidateSkillArtefact:
    def test_valid_skill_s1(self):
        assert validate_skill_artefact("s1-intent-guard") is True

    def test_valid_skill_s2(self):
        assert validate_skill_artefact("s2-task-graph") is True

    def test_valid_all_eight_skills(self):
        skill_names = [
            "s1-intent-guard", "s2-task-graph", "s3-horizon-plan",
            "s4-role-dispatch", "s5-collab-exec", "s6-resilience-guard",
            "s7-observe-verify", "s8-orchestration-hub",
        ]
        for s in skill_names:
            assert validate_skill_artefact(s) is True, f"Failed: {s}"

    def test_invalid_nonexistent_skill(self):
        assert validate_skill_artefact("s99-nonexistent") is False

    def test_required_fields_defined(self):
        assert "name" in REQUIRED_FIELDS
        assert "description" in REQUIRED_FIELDS
        assert len(REQUIRED_FIELDS) == 2
