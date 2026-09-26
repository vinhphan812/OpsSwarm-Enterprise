#!/usr/bin/env python3
"""Verify that the runtime dependency input and hash lock remain aligned."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock"
NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^]]+\])?")
PIN_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s\\;]+)")
FORBIDDEN_LOCK_OPTIONS = ("--index-url", "--extra-index-url", "--trusted-host")


def normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_name(requirement: str) -> str:
    match = NAME_PATTERN.match(requirement)
    if match is None:
        raise ValueError(f"unsupported requirement: {requirement!r}")
    return normalise_name(match.group(1))


def direct_requirements() -> list[str]:
    return [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def project_requirements() -> list[str]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    return list(project["dependencies"])


def locked_requirements(lock_text: str) -> dict[str, str]:
    locked: dict[str, str] = {}
    lines = lock_text.splitlines()
    pinned_lines = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := PIN_PATTERN.match(line)) is not None
    ]
    for position, (index, match) in enumerate(pinned_lines):
        name = normalise_name(match.group(1))
        if name in locked:
            raise ValueError(f"duplicate locked package: {name}")

        # Determine the end of the current requirement block
        next_index = pinned_lines[position + 1][0] if position + 1 < len(pinned_lines) else len(lines)
        block = lines[index:next_index]

        # Check if the current block contains a hash
        if not any("--hash=sha256:" in line for line in block):
            raise ValueError(f"locked package has no SHA-256 hash: {name}")

        locked[name] = match.group(2)
    return locked


def verify() -> list[str]:
    errors: list[str] = []
    direct = direct_requirements()
    project = project_requirements()
    if direct != project:
        errors.append(
            "requirements.txt must exactly match pyproject.toml [project.dependencies] "
            "in content and order"
        )

    lock_text = LOCK.read_text(encoding="utf-8")
    for option in FORBIDDEN_LOCK_OPTIONS:
        if any(line.startswith(option) for line in lock_text.splitlines()):
            errors.append(f"requirements.lock must not embed environment-specific {option}")

    if "requirements.txt" not in "\n".join(lock_text.splitlines()[:8]):
        errors.append("requirements.lock generator header must name requirements.txt")

    try:
        locked = locked_requirements(lock_text)
    except ValueError as exc:
        errors.append(str(exc))
        locked = {}

    missing = sorted({dependency_name(requirement) for requirement in direct} - locked.keys())
    if missing:
        errors.append("direct dependencies missing from requirements.lock: " + ", ".join(missing))
    if not locked:
        errors.append("requirements.lock contains no pinned packages")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "Dependency lock verified: pyproject.toml and requirements.txt align; "
        "all direct dependencies are present in the portable hash-locked graph."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
