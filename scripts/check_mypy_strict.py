#!/usr/bin/env python3
"""Enforce the mypy Stage-2 error-count baseline; a missing baseline fails.

Issue #71 shipped this script in "advisory" mode: when the baseline artefact
was absent the script exited 2 and CI carried on. Issue #124 makes the gate
fail closed, because a gate that can silently degrade is not a gate.

Exits:
  0 - error count is within the recorded baseline (pass)
  1 - error count exceeds the baseline, or the baseline is missing (fail)
  2 - mypy itself could not be run, or the baseline is malformed (fail)

Usage:
  python scripts/check_mypy_strict.py
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = REPO_ROOT / ".static_analysis_baseline.toml"


class BaselineError(RuntimeError):
    """The baseline artefact is missing or does not carry the expected keys."""


def load_baseline() -> dict:
    """Load the required baseline; absence or corruption is a hard failure."""
    if not BASELINE_FILE.is_file():
        raise BaselineError(f"Required baseline not found: {BASELINE_FILE}")
    with BASELINE_FILE.open("rb") as handle:
        data = tomllib.load(handle)
    baseline = data.get("baseline", {}).get("mypy", {})
    if not isinstance(baseline, dict) or "error_count" not in baseline:
        raise BaselineError("Baseline must define [baseline.mypy].error_count")
    return baseline


def run_mypy() -> list[str]:
    """Run mypy over the package and return the error lines it reported."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental", "opsswarm/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"mypy exited with {result.returncode}: {result.stderr[:1000]}")
    return [line for line in result.stdout.splitlines() if ": error:" in line]


def main() -> None:
    try:
        baseline = load_baseline()
    except BaselineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: baseline could not be read: {exc}", file=sys.stderr)
        sys.exit(1)

    baseline_count = baseline["error_count"]

    try:
        errors = run_mypy()
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    current_count = len(errors)

    print(f"mypy Stage-2: {current_count} error(s) (baseline: {baseline_count})")

    if current_count > baseline_count:
        print(f"FAIL: {current_count} > {baseline_count}", file=sys.stderr)
        for error in errors[:20]:
            print(f"  {error}", file=sys.stderr)
        sys.exit(1)

    print(f"PASS: within baseline ({current_count} <= {baseline_count})")
    sys.exit(0)


if __name__ == "__main__":
    main()
