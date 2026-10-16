"""Canonical application version helpers (ADR 0025).

The single source of truth for the SemVer release is the ``VERSION`` file at the
repository root. Both the API process and the Web build derive their reported
version from that file (the Web build copies ``VERSION`` into a generated
constant at build time). This module exposes:

- ``__version__``     : the SemVer string (``MAJOR.MINOR.PATCH``).
- ``git_sha``         : short commit SHA at build time (``GIT_SHA`` env var or
                        ``git rev-parse --short HEAD`` at startup; falls back to
                        ``"unknown"`` in environments without git).
- ``build_time``      : ISO-8601 UTC timestamp captured when the module loads.
- ``full_version``    : ``__version__`` + ``+<git_sha>`` build metadata.
- ``read_version``    : parses the ``VERSION`` file and validates the SemVer
                        shape. Raises ``InvalidVersion`` on malformed input.

CI runs ``scripts/check_version_consistency.py`` to ensure this module and the
Web bundle read the same SemVer and that any release-tag commit has a matching
``CHANGELOG.md`` section.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = REPO_ROOT / "VERSION"

# Strict SemVer 2.0.0 core expression: MAJOR.MINOR.PATCH with no pre-release
# or build metadata. The PEP 440 superset would also accept "0.8.0a1" but the
# issue scope is plain SemVer.
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class InvalidVersion(ValueError):
    """Raised when the ``VERSION`` file does not contain a SemVer string."""


def _validate(raw: str) -> str:
    candidate = raw.strip()
    if not _SEMVER_RE.match(candidate):
        raise InvalidVersion(
            f"VERSION file must contain 'MAJOR.MINOR.PATCH' SemVer (got {raw!r})."
        )
    return candidate


def read_version(path: Path | None = None) -> str:
    """Read and validate the canonical SemVer from the VERSION file."""
    target = path or VERSION_FILE
    if not target.exists():
        raise InvalidVersion(f"VERSION file not found at {target}.")
    return _validate(target.read_text(encoding="utf-8"))


def _resolve_git_sha() -> str:
    """Best-effort short SHA at build/startup time.

    CI injects ``GIT_SHA`` (7+ hex chars) so the running process reports the
    commit it was built from even when ``.git`` is not present (for example in
    a Docker image or a Cloud Run revision). Locally and in CI checkouts that
    have a ``.git`` directory, ``git rev-parse --short HEAD`` is used as the
    fallback. When neither is available, return ``"unknown"`` so the runtime
    payload still parses.
    """
    env_sha = os.environ.get("GIT_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = (result.stdout or "").strip()
    return sha or "unknown"


__version__ = read_version()
git_sha = _resolve_git_sha()
build_time = datetime.now(timezone.utc).isoformat(timespec="seconds")


def full_version() -> str:
    """``MAJOR.MINOR.PATCH+<git_sha>`` — SemVer build metadata is informational."""
    return f"{__version__}+{git_sha}"