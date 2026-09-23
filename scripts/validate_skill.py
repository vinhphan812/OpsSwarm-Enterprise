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

# Minimum test threshold per skill (per Issue #3)
MIN_TESTS_PER_SKILL = 24

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

    # Check required fields
    missing = REQUIRED_FIELDS - set(frontmatter.keys())
    if missing:
        errors.append(f"Missing required fields: {missing}")

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

    # Note: tests/ and scripts/ are optional per current architecture
    # They may exist in the main project, not duplicated in skills/

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


def count_tests_for_skill(skill_id: str) -> int:
    """Count tests for a specific skill using pytest --collect-only."""
    skill_num = skill_id.split("-")[0].replace("s", "")  # s1-intent-guard -> 1
    test_dir = TESTS_DIR / f"skill_s{skill_num}"

    if not test_dir.exists():
        return 0

    try:
        result = subprocess.run(
            ["pytest", str(test_dir), "--collect-only", "-q"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Parse test count from output
        # pytest output: "X tests collected" or "no tests collected"
        output = result.stdout + result.stderr
        if "no tests collected" in output.lower():
            return 0
        # Try to extract number
        for line in output.splitlines():
            if "test" in line.lower() and "collected" in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if part.isdigit():
                        return int(part)
        return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


def validate_test_threshold(skill_id: str) -> tuple[bool, list[str]]:
    """Validate skill has minimum test count."""
    errors = []
    test_count = count_tests_for_skill(skill_id)

    if test_count < MIN_TESTS_PER_SKILL:
        errors.append(
            f"Test count {test_count} below threshold {MIN_TESTS_PER_SKILL} for {skill_id}"
        )
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

    # Validate test threshold
    test_pass, test_errors = validate_test_threshold(skill_id)
    all_errors.extend(test_errors)

    return dep_pass and test_pass, all_errors


def collect_test_category_counts(skill_id: str) -> dict[str, int]:
    """Collect test counts by category marker."""
    skill_num = skill_id.split("-")[0].replace("s", "")
    test_dir = TESTS_DIR / f"skill_s{skill_num}"

    if not test_dir.exists():
        return {"normal": 0, "boundary": 0, "fault": 0, "cross_skill": 0, "other": 0}

    counts = {"normal": 0, "boundary": 0, "fault": 0, "cross_skill": 0, "other": 0}

    try:
        result = subprocess.run(
            ["pytest", str(test_dir), "--collect-only", "-q", "-v"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr

        # Count by marker
        for marker in TEST_MARKERS:
            if f"<Module [{marker}]" in output or f"<Function [{marker}]" in output:
                # This is a rough approximation; pytest doesn't easily expose markers in collect-only
                pass

        # For now, just return total count
        # In production, would parse pytest-json-report or use pytest --markers
        return counts

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return counts


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

    if not static_only:
        static_pass, static_errors = validate_static(skill_id)

    if not runnable_only and static_pass:
        runnable_pass, runnable_errors = validate_runnable(skill_id)
        tests_collected = count_tests_for_skill(skill_id)

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
