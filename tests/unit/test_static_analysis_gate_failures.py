"""Gate failure-mode tests for the static-analysis baselines (Issue #124).

These tests prove that the Stage-2 gates actually fail. A gate that only
documents the intended configuration is not a gate, so every case below runs
the real script against an isolated copy of the repository and asserts on the
exit code.

The isolated copy keeps the production pyproject.toml so that the per-module
mypy waivers and the Ruff rule selection are the ones CI will enforce.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _copy_gate_repo(tmp_path: Path) -> Path:
    """Copy the gate scripts, configuration and sources into an isolated tree."""
    destination = tmp_path / "repo"
    destination.mkdir()
    for name in ("scripts", "opsswarm", "tests"):
        shutil.copytree(REPO_ROOT / name, destination / name)
    shutil.copy2(REPO_ROOT / "pyproject.toml", destination / "pyproject.toml")
    return destination


def _write_baseline(repo: Path, ruff_count: int = 884, mypy_count: int = 0) -> None:
    """Write a baseline that matches the copied tree, so only the fixture fails."""
    (repo / ".static_analysis_baseline.toml").write_text(
        "[baseline.ruff]\n"
        f"error_count = {ruff_count}\n"
        'rule_selection = ["E", "F", "I", "B", "RUF"]\n\n'
        "[baseline.mypy]\n"
        f"error_count = {mypy_count}\n\n"
        "[baseline.bandit]\n"
        "high_severity_count = 0\n",
        encoding="utf-8",
    )


def _run_gate(repo: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, f"scripts/{script}"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.mark.unit
def test_missing_baseline_fails_both_gates(tmp_path: Path) -> None:
    """A missing baseline must fail the build, not degrade to advisory mode."""
    repo = _copy_gate_repo(tmp_path)
    (repo / ".static_analysis_baseline.toml").unlink(missing_ok=True)
    for script in ("check_ruff_full.py", "check_mypy_strict.py"):
        result = _run_gate(repo, script)
        assert result.returncode == 1, (
            f"{script} must exit 1 when the baseline is missing, "
            f"got {result.returncode}\nSTDOUT:\n{result.stdout}"
        )
        assert "Required baseline not found" in result.stderr


@pytest.mark.unit
def test_ruff_gate_detects_f401_in_test_scope(tmp_path: Path) -> None:
    """One deliberate unused import must push the Ruff gate over its baseline."""
    repo = _copy_gate_repo(tmp_path)
    _write_baseline(repo)
    (repo / "tests" / "fixture_unused_import.py").write_text(
        "import pathlib\n", encoding="utf-8"
    )
    result = _run_gate(repo, "check_ruff_full.py")
    assert result.returncode == 1, (
        f"expected exit 1, got {result.returncode}\nSTDOUT:\n{result.stdout}"
    )
    assert "baseline exceeded" in result.stderr
    assert "F401" in result.stderr


@pytest.mark.unit
def test_mypy_gate_detects_arg_type_in_models(tmp_path: Path) -> None:
    """One deliberate arg-type violation must push the mypy gate over baseline."""
    repo = _copy_gate_repo(tmp_path)
    _write_baseline(repo)
    models = repo / "opsswarm" / "models.py"
    models.write_text(
        models.read_text(encoding="utf-8")
        + "\n\ndef _fixture_requires_int(value: int) -> int:\n"
        + "    return value\n\n"
        + '_fixture_requires_int("not an int")\n',
        encoding="utf-8",
    )
    result = _run_gate(repo, "check_mypy_strict.py")
    assert result.returncode == 1, (
        f"expected exit 1, got {result.returncode}\nSTDOUT:\n{result.stdout}"
    )
    assert "models.py" in result.stderr
    assert "arg-type" in result.stderr
