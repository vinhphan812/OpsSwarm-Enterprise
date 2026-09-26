"""Focused regression tests for the dependency-lock verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_dependency_lock.py"
SPEC = importlib.util.spec_from_file_location("verify_dependency_lock", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify_dependency_lock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_dependency_lock)


def test_locked_requirements_rejects_hash_borrowed_from_next_package() -> None:
    lock_text = """\
annotated-doc==0.0.5 \\
    # via fastapi
annotated-types==0.8.0 \\
    --hash=sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7
    # via pydantic
"""

    with pytest.raises(ValueError, match="locked package has no SHA-256 hash: annotated-doc"):
        verify_dependency_lock.locked_requirements(lock_text)


def test_locked_requirements_accepts_hash_anywhere_in_own_long_block() -> None:
    comments = "\n".join(f"    # metadata {index}" for index in range(25))
    lock_text = (
        "long-package==1.0.0 \\\n"
        f"{comments}\n"
        "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "next-package==2.0.0 \\\n"
        "    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    )

    assert verify_dependency_lock.locked_requirements(lock_text) == {
        "long-package": "1.0.0",
        "next-package": "2.0.0",
    }


def test_verify_reports_source_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_dependency_lock, "direct_requirements", lambda: ["fastapi>=0.115,<1"])
    monkeypatch.setattr(verify_dependency_lock, "project_requirements", lambda: ["httpx>=0.27,<1"])
    monkeypatch.setattr(
        verify_dependency_lock,
        "locked_requirements",
        lambda _lock_text: {"fastapi": "0.141.1"},
    )

    errors = verify_dependency_lock.verify()


    assert any("must exactly match" in error for error in errors)


def test_locked_requirements_handles_spaces_around_equals() -> None:
    # A has no hash. B has spaces around ==, which was previously causing it
    # to not be detected as a pin, leading to A borrowing B's hash.
    # The parser should now correctly detect B as a pin and reject A.
    lock_text = """A==1.0
B == 2.0
    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
"""

    with pytest.raises(ValueError, match="locked package has no SHA-256 hash: a"):
        verify_dependency_lock.locked_requirements(lock_text)
