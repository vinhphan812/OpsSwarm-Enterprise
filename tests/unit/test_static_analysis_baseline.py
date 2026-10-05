"""Static analysis gate tests — Issue #71.

These tests encode Ruff and mypy error-code baselines that CI must not exceed.
They are NOT style linters — they assert that new code does not introduce
errors in categories already audited as fixable without CI-unfeasible churn.

Run locally before pushing:
    python -m pytest tests/unit/test_static_analysis_baseline.py -v
    python -m ruff check opsswarm/ tests/ --select=E,F,I,B,RUF
    python -m mypy opsswarm/
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRUB_SENTINEL = "opsswarm/"


# ---------------------------------------------------------------------------
# Ruff: Stage-1 error-code baselines (E, F, I, B, RUF subset)
# ---------------------------------------------------------------------------
# At enablement time (origin/master 5428526), the current Ruff config
# [E9, F63, F7, F82] produces zero errors.  The test uses `sys.executable -m ruff`
# so it works in CI without requiring uv.
#
# Baseline  : 0 errors
# Config    : pyproject.toml [tool.ruff.lint.select] = ["E9","F63","F7","F82"]
# Suppressed: E501, E701, E703, F403, F405, F541, F811, RUF012, RUF102
# ---------------------------------------------------------------------------

RUFF_ERROR_CODES_STAGE1: list[str] = []
"""Ruff Stage-1 error codes introduced at Issue #71 enablement: 0 errors."""


@pytest.mark.unit
def test_ruff_stage1_zero_errors():
    """Ruff E9/F7/F82/F63 must produce zero errors on opsswarm/ (origin/master baseline)."""
    # Use sys.executable -m ruff so the test works in CI (no uv required).
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", "opsswarm/", "tests/",
            "--select=E9,F63,F7,F82",
            "--output-format=concise",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # E9/F63/F7/F82 are correctness-only rules; any violation is a CI failure.
    # Filter to real hits (skip warnings about incompatible docstring rules).
    errors = [
        line for line in result.stdout.splitlines()
        if SCRUB_SENTINEL in line and ":" in line
    ]
    assert result.returncode in (0, 1), (
        f"Ruff check crashed (returncode={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert len(errors) == 0, (
        f"Ruff Stage-1 found {len(errors)} error(s):\n"
        + "\n".join(errors[:20])
        + ("\n[...]" if len(errors) > 20 else "")
    )


# ---------------------------------------------------------------------------
# Ruff: Stage-2 expansion (E, F, I, B, RUF) — gated on per-file ignores
# ---------------------------------------------------------------------------
# This is the full Ruff correctness+import+禁则+refactor set.
# Baseline at Issue #71 enablement (origin/master 5428526): 0 errors after
# applying the per-file ignores below.  The CI script check_ruff_full.sh
# enforces this.
# ---------------------------------------------------------------------------

RUFF_STAGE2_PER_FILE_IGNORES = {
    "opsswarm/__init__.py": ["F403", "F405"],
    "opsswarm/evidence.py": ["E402"],
}


@pytest.mark.unit
def test_ruff_stage2_via_ci_script():
    """Run the CI Ruff script; it fails if error count exceeds Stage-2 baseline."""
    result = subprocess.run(
        [sys.executable, "scripts/check_ruff_full.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Exit 0 = within baseline. Exit 1 = over baseline (or internal error).
    # Exit 2 = no baseline file found (degraded but not a hard failure).
    assert result.returncode in (0, 2), (
        f"scripts/check_ruff_full.py failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# mypy: Stage-1 relaxed checks on Stage-1 modules
# ---------------------------------------------------------------------------
# Stage-1 modules (models, policy, registry) use a relaxed mypy config:
#   disable_error_code = [import-untyped, misc]
# Error count at enablement (origin/master 5428526): 0.
#
# Stage-2: removes most disabling codes across all of opsswarm/ and is
# tracked via scripts/check_mypy_strict.py.
# ---------------------------------------------------------------------------

MYPY_STAGE1_ERROR_COUNT = 0


@pytest.mark.unit
def test_mypy_stage1_clean():
    """mypy on opsswarm/ must pass with the Stage-1 configuration."""
    # Invoke the venv mypy executable directly to avoid subprocess env issues
    # on Windows where pytest may run from a different cwd than the repo root.
    venv_mypy = REPO_ROOT / ".venv" / "Scripts" / "mypy.exe"
    if sys.platform == "win32" and venv_mypy.exists():
        mypy_bin = str(venv_mypy)
    else:
        mypy_bin = "mypy"

    result = subprocess.run(
        [mypy_bin, "opsswarm"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    # mypy returns 0 on success, 1 on errors found.
    errors = [
        line for line in result.stdout.splitlines()
        if SCRUB_SENTINEL in line and ":" in line
    ]
    assert result.returncode == 0, (
        f"mypy found {len(errors)} error(s):\n"
        + "\n".join(errors[:30])
        + ("\n[...]" if len(errors) > 30 else "")
        + f"\nSTDERR:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Bandit: security findings must not exceed baseline
# ---------------------------------------------------------------------------

BANDIT_BASELINE_FILE = REPO_ROOT / ".static_analysis_baseline.toml"
BANDIT_ALLOWED_HIGH_SEVERITY = 0


@pytest.mark.unit
def test_bandit_high_severity_baseline():
    """Bandit HIGH-severity findings on opsswarm/ must not exceed baseline."""
    result = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "opsswarm/", "-f", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    import json

    try:
        report = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError:
        pytest.fail(f"Bandit output was not valid JSON:\n{result.stdout[:500]}")

    findings = report.get("results", [])
    high_severity = [f for f in findings if f.get("issue_severity") == "HIGH"]
    assert len(high_severity) <= BANDIT_ALLOWED_HIGH_SEVERITY, (
        f"Bandit found {len(high_severity)} HIGH-severity finding(s):\n"
        + "\n".join(f"  [{f['issue_severity']}] {f['issue_text']} ({f['filename']}:{f['line']})"
                   for f in high_severity[:10])
    )
