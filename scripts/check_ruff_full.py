#!/usr/bin/env python3
"""Enforce the Ruff Stage-2 error-count baseline; a missing baseline fails.

Issue #71 shipped this script in "advisory" mode: when the baseline artefact
was absent the script exited 2 and CI carried on. Issue #124 makes the gate
fail closed, because a gate that can silently degrade is not a gate.

Exits:
  0 - violation count is within the recorded baseline (pass)
  1 - violation count exceeds the baseline, or the baseline is missing (fail)
  2 - Ruff itself could not be run, or the baseline is malformed (fail)

Usage:
  python scripts/check_ruff_full.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = REPO_ROOT / ".static_analysis_baseline.toml"

# Stage-2 rule selection - correctness (E), Pyflakes (F), import hygiene (I),
# bugbear (B) and Ruff-specific rules (RUF). The recorded baseline in
# .static_analysis_baseline.toml must name exactly this selection.
RUFF_SELECT = ["E", "F", "I", "B", "RUF"]


class BaselineError(RuntimeError):
    """The baseline artefact is missing or does not carry the expected keys."""


def load_baseline() -> dict:
    """Load the required baseline; absence or corruption is a hard failure."""
    if not BASELINE_FILE.is_file():
        raise BaselineError(f"Required baseline not found: {BASELINE_FILE}")
    with BASELINE_FILE.open("rb") as handle:
        data = tomllib.load(handle)
    baseline = data.get("baseline", {}).get("ruff", {})
    if not isinstance(baseline, dict) or "error_count" not in baseline:
        raise BaselineError("Baseline must define [baseline.ruff].error_count")
    return baseline


def run_ruff() -> list[dict]:
    """Run Ruff over the Stage-2 scope and return the JSON diagnostics."""
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            "opsswarm/", "tests/",
            f"--select={','.join(RUFF_SELECT)}",
            "--output-format=json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"ruff exited with {result.returncode}: {result.stderr[:1000]}")
    try:
        violations = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("ruff produced invalid JSON output") from exc
    return violations


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
    baseline_rules = baseline.get("rule_selection", [])
    if baseline_rules != RUFF_SELECT:
        print(
            f"ERROR: baseline rule selection mismatch: {baseline_rules} "
            f"(expected {RUFF_SELECT})",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        violations = run_ruff()
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    current_count = len(violations)

    print(f"Ruff Stage-2: {current_count} error(s) (baseline: {baseline_count})")
    print(f"Rule selection: {RUFF_SELECT}")

    if current_count > baseline_count:
        print(f"FAIL: {current_count} > {baseline_count} (baseline exceeded)", file=sys.stderr)
        if violations:
            print("\nFirst 20 violations:", file=sys.stderr)
            for item in violations[:20]:
                location = item.get("location", {})
                print(
                    f"  {item.get('filename')}:{location.get('row')}: {item.get('code')}",
                    file=sys.stderr,
                )
        sys.exit(1)

    print(f"PASS: within baseline ({current_count} <= {baseline_count})")
    sys.exit(0)


if __name__ == "__main__":
    main()
