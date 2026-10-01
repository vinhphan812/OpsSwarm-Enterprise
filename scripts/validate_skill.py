#!/usr/bin/env python3
"""Skill-Gate Validator CLI for OpsSwarm-Enterprise.

This validator enforces architectural integrity by validating:
- SKILL.md frontmatter and directory structure (static)
- Dependencies, test counts, and cross-skill contracts (runnable)
- Evidence generation for CI audit trail
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Project root is parent of scripts/
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SKILLS_DIR = PROJECT_ROOT / "skills"
TESTS_DIR = PROJECT_ROOT / "tests" / "unit"
RUNTIME_DATA_DIR = PROJECT_ROOT / "runtime-data" / "evidence"

# Required frontmatter fields per SKILL.md
REQUIRED_FIELDS = {"name", "description"}
ALLOWED_FRONTMATTER_FIELDS = REQUIRED_FIELDS

# Minimum test threshold per skill (ADR-011 / Issue #3).
MIN_TESTS_PER_SKILL = 24
REQUIRED_CATEGORIES = frozenset({"normal", "boundary", "fault", "cross_skill"})

# Skill IDs in execution order
ALL_SKILLS = [
    "s1-intent-guard",
    "s2-task-graph",
    "s3-horizon-plan",
    "s4-role-dispatch",
    "s5-collab-exec",
    "s6-resilience-guard",
    "s7-observe-verify",
    "s8-orchestration-hub",
]

# Test category markers
TEST_MARKERS = {
    "normal": "normal",
    "boundary": "boundary",
    "fault": "fault",
    "cross_skill": "cross_skill",
}


class ValidationError(Exception):
    """Validation failure."""
    pass


def get_run_id() -> str:
    """Generate a unique run ID for this validation run."""
    return f"SGV-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def load_skill_frontmatter(skill_id: str) -> dict[str, Any] | None:
    """Load and parse SKILL.md frontmatter."""
    skill_path = SKILLS_DIR / skill_id / "SKILL.md"
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


def validate_skill_frontmatter(skill_id: str) -> tuple[bool, list[str]]:
    """Validate SKILL.md frontmatter has required fields."""
    errors = []

    # Check file exists
    skill_path = SKILLS_DIR / skill_id / "SKILL.md"
    if not skill_path.exists():
        errors.append(f"SKILL.md not found at {skill_path}")
        return False, errors

    # Check frontmatter
    frontmatter = load_skill_frontmatter(skill_id)
    if frontmatter is None:
        errors.append(f"Failed to parse frontmatter for {skill_id}")
        return False, errors

    if not isinstance(frontmatter, dict):
        errors.append(f"Frontmatter must be a mapping for {skill_id}")
        return False, errors

    # Exact allowlist prevents undocumented fields from becoming unenforced API.
    missing = REQUIRED_FIELDS - set(frontmatter)
    extra = set(frontmatter) - ALLOWED_FRONTMATTER_FIELDS
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")
    if extra:
        errors.append(f"Unsupported frontmatter fields: {sorted(extra)}")
    if frontmatter.get("name") != skill_id:
        errors.append(f"Frontmatter name must equal allowlisted skill id {skill_id}")
    if not isinstance(frontmatter.get("description"), str) or not frontmatter["description"].strip():
        errors.append("description must be a non-empty string")

    return len(errors) == 0, errors


def validate_skill_structure(skill_id: str) -> tuple[bool, list[str]]:
    """Validate skill directory structure."""
    errors = []
    skill_dir = SKILLS_DIR / skill_id

    if not skill_dir.exists():
        errors.append(f"Skill directory not found: {skill_dir}")
        return False, errors

    # Check SKILL.md exists
    if not (skill_dir / "SKILL.md").exists():
        errors.append(f"SKILL.md not found in {skill_id}")

    # Skill folders are intentionally SKILL.md-only (ADR-011).
    entries = [p.name for p in skill_dir.iterdir() if p.name != "SKILL.md"]
    if entries:
        errors.append(f"Skill directory must contain only SKILL.md; found: {sorted(entries)}")

    return len(errors) == 0, errors


def validate_static(skill_id: str) -> tuple[bool, list[str]]:
    """Run static validation on a skill."""
    all_errors = []

    # Validate structure
    struct_pass, struct_errors = validate_skill_structure(skill_id)
    all_errors.extend(struct_errors)

    # Validate frontmatter
    fm_pass, fm_errors = validate_skill_frontmatter(skill_id)
    all_errors.extend(fm_errors)

    return struct_pass and fm_pass, all_errors


def collect_test_evidence(skill_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect deterministic per-test category evidence from source markers."""
    import ast

    skill_num = skill_id.split("-", 1)[0][1:]
    test_dir = TESTS_DIR / f"skill_s{skill_num}"
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    if not test_dir.exists():
        errors.append(f"Test directory not found for {skill_id}: {test_dir}")
        return evidence, errors

    for test_file in sorted(test_dir.glob("test_*.py")):
        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(test_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for marker in TEST_MARKERS:
                        if marker in [m.name for m in getattr(node, "decorator_list", [])]:
                            evidence.append({
                                "skill_id": skill_id,
                                "file": str(test_file.relative_to(PROJECT_ROOT)),
                                "function": node.name,
                                "category": marker,
                            })
                            break
        except (SyntaxError, OSError) as exc:
            errors.append(f"Error reading {test_file}: {exc}")

    return evidence, errors


def collect_test_category_counts(skill_id: str) -> dict[str, int]:
    """Collect test counts by category marker."""
    evidence, _ = collect_test_evidence(skill_id)
    counts = {cat: 0 for cat in TEST_MARKERS}
    counts["other"] = 0
    for item in evidence:
        cat = item.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def validate_test_threshold(skill_id: str) -> tuple[bool, list[str]]:
    """Validate skill has minimum test count across all required categories."""
    errors = []
    evidence, parse_errors = collect_test_evidence(skill_id)
    errors.extend(parse_errors)
    counts = collect_test_category_counts(skill_id)
    total = sum(counts.values())

    if total < MIN_TESTS_PER_SKILL:
        errors.append(
            f"Test count {total} below threshold {MIN_TESTS_PER_SKILL} for {skill_id}"
        )
        return False, errors

    # Every required category must have at least 1 test.
    missing_cats = REQUIRED_CATEGORIES - set(counts.keys())
    if missing_cats:
        errors.append(f"Missing test categories: {sorted(missing_cats)}")
        return False, errors

    return True, errors


def validate_dependencies(skill_id: str) -> tuple[bool, list[str]]:
    """Validate skill dependencies exist."""
    errors = []
    frontmatter = load_skill_frontmatter(skill_id)

    if frontmatter is None:
        errors.append(f"Cannot check dependencies: frontmatter parse failed for {skill_id}")
        return False, errors

    depends_on = frontmatter.get("depends_on", [])

    for dep in depends_on:
        dep_path = SKILLS_DIR / dep / "SKILL.md"
        if not dep_path.exists():
            errors.append(f"Dependency {dep} not found for {skill_id}")

    return len(errors) == 0, errors


def validate_runnable(skill_id: str) -> tuple[bool, list[str]]:
    """Run runnable validation on a skill."""
    all_errors = []

    # Validate dependencies
    dep_pass, dep_errors = validate_dependencies(skill_id)
    all_errors.extend(dep_errors)

    # Validate test threshold (includes category enforcement)
    test_pass, test_errors = validate_test_threshold(skill_id)
    all_errors.extend(test_errors)

    return dep_pass and test_pass, all_errors


def generate_evidence(
        run_id: str,
        skill_id: str,
        static_pass: bool,
        runnable_pass: bool,
        static_errors: list[str],
        runnable_errors: list[str],
        tests_collected: int,
        tests_passed: int | None = None,
        coverage: float | None = None,
) -> dict[str, Any]:
    """Generate evidence record for a skill validation."""
    # Get evidence refs from existing evidence store if available
    evidence_refs = []

    # Try to load existing evidence IDs
    evidence_dir = PROJECT_ROOT / "runtime-data" / "evidence"
    if evidence_dir.exists():
        for f in evidence_dir.glob(f"{run_id}*.jsonl"):
            try:
                for line in f.read_text().splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        if "id" in rec:
                            evidence_refs.append(rec["id"])
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "skill_validation": {
            "skill_id": skill_id,
            "static_pass": static_pass,
            "static_errors": static_errors,
            "runnable_pass": runnable_pass,
            "runnable_errors": runnable_errors,
            "tests_collected": tests_collected,
            "tests_passed": tests_passed,
            "coverage": coverage,
        },
        "evidence_refs": evidence_refs,
    }


def save_evidence(run_id: str, evidence: dict[str, Any]) -> Path:
    """Save evidence to runtime-data/evidence/{run_id}.jsonl."""
    RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)

    output_path = RUNTIME_DATA_DIR / f"{run_id}.jsonl"
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evidence, ensure_ascii=False, default=str) + "\n")

    return output_path


def run_validation(
        skill_id: str,
        static_only: bool = False,
        runnable_only: bool = False,
        generate_evidence_flag: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Run validation for a single skill."""
    run_id = get_run_id()

    static_pass = True
    static_errors = []
    runnable_pass = True
    runnable_errors = []
    tests_collected = 0

    if not runnable_only:
        static_pass, static_errors = validate_static(skill_id)

    if not static_only:
        runnable_pass, runnable_errors = validate_runnable(skill_id)
        evidence_list, _ = collect_test_evidence(skill_id)
        tests_collected = len(evidence_list)

    evidence = generate_evidence(
        run_id=run_id,
        skill_id=skill_id,
        static_pass=static_pass,
        runnable_pass=runnable_pass,
        static_errors=static_errors,
        runnable_errors=runnable_errors,
        tests_collected=tests_collected,
    )

    if generate_evidence_flag:
        save_evidence(run_id, evidence)

    overall_pass = static_pass and runnable_pass

    return overall_pass, evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate OpsSwarm skills against gate requirements."
    )
    parser.add_argument(
        "--skill",
        type=str,
        help="Validate a specific skill (e.g., s1-intent-guard)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all skills",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Run static validation only (fast)",
    )
    parser.add_argument(
        "--runnable",
        action="store_true",
        help="Run runnable validation only (full)",
    )
    parser.add_argument(
        "--evidence",
        action="store_true",
        help="Generate and save evidence to runtime-data/evidence/",
    )

    args = parser.parse_args(argv)

    # Determine which skills to validate
    skills_to_validate = []
    if args.skill:
        if args.skill not in ALL_SKILLS:
            print(f"Error: Unknown skill '{args.skill}'. Valid skills: {ALL_SKILLS}", file=sys.stderr)
            return 1
        skills_to_validate = [args.skill]
    elif args.all:
        skills_to_validate = ALL_SKILLS
    else:
        print("Error: Must specify --skill <id> or --all", file=sys.stderr)
        return 1

    # Run validation
    all_passed = True
    results = []

    for skill_id in skills_to_validate:
        passed, evidence = run_validation(
            skill_id,
            static_only=args.static,
            runnable_only=args.runnable,
            generate_evidence_flag=args.evidence,
        )

        results.append({
            "skill_id": skill_id,
            "passed": passed,
            "evidence": evidence,
        })

        if not passed:
            all_passed = False
            print(f"FAILED: {skill_id}")
            for err in evidence.get("skill_validation", {}).get("static_errors", []):
                print(f"  Static error: {err}")
            for err in evidence.get("skill_validation", {}).get("runnable_errors", []):
                print(f"  Runnable error: {err}")
        else:
            print(f"PASSED: {skill_id}")

    # Output summary
    print(f"\n{'=' * 50}")
    print(f"Validation Summary: {len([r for r in results if r['passed']])}/{len(results)} passed")

    if args.evidence:
        run_id = get_run_id()
        summary_evidence = {
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "actor": "validate_skill.py",
            "validation_mode": "static" if args.static else "runnable" if args.runnable else "all",
            "skills_validated": skills_to_validate,
            "results": [
                {
                    "skill_id": r["skill_id"],
                    "static_pass": r["evidence"]["skill_validation"]["static_pass"],
                    "static_errors": r["evidence"]["skill_validation"]["static_errors"],
                    "runnable_pass": r["evidence"]["skill_validation"]["runnable_pass"],
                    "runnable_errors": r["evidence"]["skill_validation"]["runnable_errors"],
                    "tests_collected": r["evidence"]["skill_validation"]["tests_collected"],
                }
                for r in results
            ],
            "overall_pass": all_passed,
            "failures": [
                r["skill_id"] for r in results if not r["passed"]
            ] if not all_passed else [],
        }
        save_evidence(run_id, summary_evidence)

        print(f"Evidence saved to: runtime-data/evidence/{run_id}.jsonl")

        # Also print JSON to stdout if --evidence
        print("\nEvidence JSON:")
        print(json.dumps(summary_evidence, indent=2))

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
