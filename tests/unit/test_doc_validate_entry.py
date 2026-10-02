"""Integration smoke tests for the docs/validate.py entry point.

These tests are separated from test_doc_examples.py so that running
`pytest tests/unit/test_doc_examples.py` from within docs/validate.py
does not cause infinite recursion.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DOCS_DIR = PROJECT_ROOT / "docs"
VALIDATE_PY = DOCS_DIR / "validate.py"


class TestValidateEntryPoint:
    def test_validate_py_runs_successfully(self):
        """docs/validate.py must run and return 0 when all docs are clean."""
        assert VALIDATE_PY.exists(), "docs/validate.py must exist"

        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"docs/validate.py failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_validate_py_verbose_flag(self):
        """docs/validate.py --verbose must not crash."""
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), "--verbose"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        # Should succeed or fail gracefully (not crash with traceback)
        assert "Traceback" not in result.stderr, f"Crash in verbose mode:\n{result.stderr}"

    def test_validate_py_skip_examples(self):
        """docs/validate.py --skip-examples must run without running doc example tests."""
        result = subprocess.run(
            [sys.executable, str(VALIDATE_PY), "--skip-examples"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=60,
        )
        assert result.returncode == 0, (
            f"docs/validate.py --skip-examples failed:\n{result.stdout}\n{result.stderr}"
        )
