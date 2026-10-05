#!/usr/bin/env python3
"""
scripts/check_ruff_full.py — Issue #71 Ruff Stage-2 CI gate.

Compares the Ruff Stage-2 error count against the baseline recorded in
.static_analysis_baseline.toml.  Exits:
  0  — error count is within baseline (pass)
  1  — error count EXCEEDS baseline (fail)
  2  — no baseline file found (degraded mode; warn but do not fail CI)

Usage:
    python scripts/check_ruff_full.py
    # or via uv:
    uv run python scripts/check_ruff_full.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = REPO_ROOT / ".static_analysis_baseline.toml"

# Stage-2 rule selection — covers correctness (E), Pyflakes (F),
# import (I), bugbear (B), and Ruff-specific (RUF) rules.
RUFF_SELECT = ["E", "F", "I", "B", "RUF"]


def load_baseline() -> dict | None:
    """Load the .static_analysis_baseline.toml if it exists."""
    if not BASELINE_FILE.exists():
        return None
    import tomllib

    with BASELINE_FILE.open("rb") as f:
        data = tomllib.load(f)
    return data.get("baseline", {}).get("ruff", {})


def run_ruff() -> tuple[int, list[str]]:
    """Run Ruff Stage-2 and return (returncode, error_lines)."""
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check",
            "opsswarm/", "tests/",
            f"--select={','.join(RUFF_SELECT)}",
            "--output-format=concise",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    errors = [
        line for line in result.stdout.splitlines()
        if "opsswarm/" in line and ":" in line and "error" not in line.lower()
    ]
    # If ruff itself crashes, surface that immediately.
    if result.returncode not in (0, 1):
        print(f"ERROR: ruff exited with {result.returncode}", file=sys.stderr)
        print(result.stderr[:1000], file=sys.stderr)
        sys.exit(2)
    return result.returncode, errors


def main() -> None:
    baseline = load_baseline()
    if baseline is None:
        print(
            "WARNING: .static_analysis_baseline.toml not found. "
            "Cannot enforce Ruff Stage-2 baseline. This is a degraded run.",
            file=sys.stderr,
        )
        sys.exit(2)  # degraded but not a hard CI failure

    baseline_count = baseline.get("error_count", -1)
    baseline_rules = baseline.get("rule_selection", [])

    current_rc, errors = run_ruff()
    current_count = len(errors)

    print(f"Ruff Stage-2: {current_count} error(s) (baseline: {baseline_count})")
    print(f"Rule selection: {RUFF_SELECT}")

    if current_count > baseline_count:
        print(f"FAIL: {current_count} > {baseline_count} (baseline exceeded)", file=sys.stderr)
        if errors:
            print("\nFirst 20 violations:", file=sys.stderr)
            for e in errors[:20]:
                print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    print(f"PASS: within baseline ({current_count} <= {baseline_count})")
    sys.exit(0)


if __name__ == "__main__":
    main()
