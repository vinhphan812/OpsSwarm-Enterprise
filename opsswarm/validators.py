import yaml
from pathlib import Path
from typing import Any

def _get_skills_dir() -> Path:
    # opsswarm/ is in root/, therefore root is parent of opsswarm/
    return Path(__file__).parent.parent / "skills"

REQUIRED_FIELDS = {"name", "description"}

def load_skill_frontmatter(skill_id: str) -> dict[str, Any] | None:
    """Load and parse SKILL.md frontmatter."""
    skill_path = _get_skills_dir() / skill_id / "SKILL.md"
    if not skill_path.exists():
        return None

    content = skill_path.read_text(encoding="utf-8")

    # Check for YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1])
            except yaml.YAMLError:
                return None

    return {}

def validate_skill_artefact(skill_id: str) -> bool:
    """
    Validate Skill frontmatter against ADR-006 schema (name + description)
    and validate skill dependency references.
    """
    frontmatter = load_skill_frontmatter(skill_id)
    if frontmatter is None:
        return False
    
    # Check fields (ADR-006 schema requirement)
    if not REQUIRED_FIELDS.issubset(frontmatter.keys()):
        return False
    
    # Check dependencies
    depends_on = frontmatter.get("depends_on", [])
    for dep in depends_on:
        # Dependency must exist
        if not ( _get_skills_dir() / dep / "SKILL.md").exists():
            return False
            
    return True
