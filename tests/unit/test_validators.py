"""Extended tests for opsswarm.validators module - covers uncovered branches."""

from opsswarm.validators import (
    load_skill_frontmatter,
    validate_skill_artefact,
)


class TestLoadSkillFrontmatterMalformed:
    """Tests for malformed frontmatter handling."""

    def test_loads_skill_without_frontmatter(self, tmp_path):
        """Returns empty dict when skill exists but has no frontmatter."""
        # Temporarily override _get_skills_dir
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-test"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("Just some markdown content.\n", encoding="utf-8")
            v._get_skills_dir = lambda: tmp_path
            result = load_skill_frontmatter("s99-test")
            assert result == {}
        finally:
            v._get_skills_dir = orig

    def test_malformed_yaml_in_frontmatter_returns_none(self, tmp_path):
        """Returns None when YAML frontmatter is malformed/unparseable."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-malformed"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: broken\n\tindent: broken\n---\n", encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = load_skill_frontmatter("s99-malformed")
            # Malformed YAML raises yaml.YAMLError, caught and returns None
            assert result is None
        finally:
            v._get_skills_dir = orig

    def test_missing_required_field_returns_false(self, tmp_path):
        """validate_skill_artefact returns False when required field is missing."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-missing-name"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: Has no name field\n---\n", encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-missing-name")
            assert result is False
        finally:
            v._get_skills_dir = orig

    def test_missing_required_description_returns_false(self, tmp_path):
        """validate_skill_artefact returns False when description field is missing."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-missing-desc"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test Skill\n---\n", encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-missing-desc")
            assert result is False
        finally:
            v._get_skills_dir = orig

    def test_parse_command_allow_all_six_commands(self):
        """All six allowed commands parse successfully."""
        from opsswarm.commands import parse_command

        for name in ["approve", "reject", "investigate", "provide", "abort", "resume"]:
            cmd = parse_command(f"/opsswarm {name}")
            assert cmd is not None, f"Failed to parse '{name}'"
            assert cmd.name == name

    def test_parse_command_with_argument(self):
        """parse_command extracts argument after command name."""
        from opsswarm.commands import parse_command

        cmd = parse_command("/opsswarm approve opt1")
        assert cmd is not None
        assert cmd.name == "approve"
        assert cmd.argument == "opt1"

    def test_parse_command_unknown_returns_none(self):
        """parse_command returns None for unknown command."""
        from opsswarm.commands import parse_command

        cmd = parse_command("/opsswarm hack")
        assert cmd is None

    def test_parse_command_empty_returns_none(self):
        """parse_command returns None for empty command."""
        from opsswarm.commands import parse_command

        cmd = parse_command("/opsswarm ")
        assert cmd is None

    def test_parse_command_no_args_returns_empty_string(self):
        """parse_command with just command name returns empty argument."""
        from opsswarm.commands import parse_command

        cmd = parse_command("/opsswarm investigate")
        assert cmd is not None
        assert cmd.name == "investigate"
        assert cmd.argument == ""

    def test_parse_command_non_opsswarm_returns_none(self):
        """parse_command returns None for non-opsswarm commands."""
        from opsswarm.commands import parse_command

        cmd = parse_command("/github approve opt1")
        assert cmd is None


class TestValidateSkillArtefactDependencies:
    """Tests for skill dependency validation."""

    def test_skill_with_missing_dependency_returns_false(self, tmp_path):
        """Returns False when a skill depends on a non-existent skill."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-missing-dep"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test Skill\ndescription: A skill that depends on nothing\ndepends_on:\n  - s99-nonexistent\n---\n",
                encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-missing-dep")
            assert result is False
        finally:
            v._get_skills_dir = orig

    def test_skill_with_valid_dependency_returns_true(self, tmp_path):
        """Returns True when all dependencies exist."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            # Create base skill (simulates s1-intent-guard)
            base_dir = tmp_path / "s1-intent-guard"
            base_dir.mkdir()
            (base_dir / "SKILL.md").write_text(
                "---\nname: Intent Guard\ndescription: Guard intent\n---\n", encoding="utf-8"
            )
            # Create dependent skill
            dep_dir = tmp_path / "s99-with-dep"
            dep_dir.mkdir()
            (dep_dir / "SKILL.md").write_text(
                "---\nname: Dependent Skill\ndescription: A skill that depends on s1\ndepends_on:\n  - s1-intent-guard\n---\n",
                encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-with-dep")
            assert result is True
        finally:
            v._get_skills_dir = orig

    def test_skill_with_empty_depends_on_returns_true(self, tmp_path):
        """Returns True when depends_on is present but empty."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            skill_dir = tmp_path / "s99-no-deps"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: No Deps Skill\ndescription: Has empty depends_on\ndepends_on: []\n---\n", encoding="utf-8"
            )
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-no-deps")
            assert result is True
        finally:
            v._get_skills_dir = orig

    def test_validate_skill_artefact_missing_skill_dir_returns_false(self, tmp_path):
        """validate_skill_artefact returns False when skill directory is missing."""
        import opsswarm.validators as v
        orig = v._get_skills_dir
        try:
            v._get_skills_dir = lambda: tmp_path
            result = validate_skill_artefact("s99-does-not-exist")
            assert result is False
        finally:
            v._get_skills_dir = orig
