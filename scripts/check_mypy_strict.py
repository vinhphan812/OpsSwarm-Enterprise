#!/usr/bin/env python3
"""
scripts/check_mypy_strict.py — Issue #71 mypy Stage-2 CI gate.

Compares mypy strict-mode error count against the baseline recorded in
.static_analysis_baseline.toml.  This script demonstrates the target config;
it is advisory in Stage 1 (exits 2) and becomes a hard gate in Stage 2.

Stage-2 config (planned):
  disable_error_code = [import-untyped, misc]
  on: models, policy, registry — 0 errors

Full rollout (Stage-3):
  Remove most disables; fix remaining errors across all of opsswarm/.

Exits:
  0  — error count is within baseline (pass)
  1  — error count EXCEEDS baseline (fail)
  2  — baseline not reached / advisory mode (degraded)

Usage:
    python scripts/check_mypy_strict.py
    uv run python scripts/check_mypy_strict.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = REPO_ROOT / ".static_analysis_baseline.toml"


def load_baseline() -> dict | None:
    if not BASELINE_FILE.exists():
        return None
    import tomllib

    with BASELINE_FILE.open("rb") as f:
        return tomllib.load(f).get("baseline", {}).get("mypy", {})


def run_mypy_stage1() -> tuple[int, list[str]]:
    """Run mypy with Stage-1 config (current pyproject.toml)."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "opsswarm/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    errors = [
        line for line in result.stdout.splitlines()
        if "opsswarm/" in line and ":" in line and "error:" in line
    ]
    return result.returncode, errors


def main() -> None:
    baseline = load_baseline()
    if baseline is None:
        print(
            "INFO: .static_analysis_baseline.toml not found. "
            "Running in advisory mode.",
            file=sys.stderr,
        )
        sys.exit(2)

    baseline_count = baseline.get("error_count", -1)

    rc, errors = run_mypy_stage1()
    current_count = len(errors)

    print(f"mypy Stage-1: {current_count} error(s) (baseline: {baseline_count})")

    if current_count > baseline_count:
        print(f"FAIL: {current_count} > {baseline_count}", file=sys.stderr)
        for e in errors[:20]:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    print(f"PASS: within baseline ({current_count} <= {baseline_count})")
    sys.exit(0)


if __name__ == "__main__":
    main()
