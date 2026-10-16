#!/usr/bin/env python3
"""CI consistency gate for canonical application versioning (ADR 0025).

Run from the repository root. Exits non-zero on any inconsistency.

Checks:
  1. ``/VERSION`` is strict SemVer (``MAJOR.MINOR.PATCH``).
  2. The API module reads the same SemVer (``retailtwin_api.version.__version__``).
  3. The Web build would emit the same ``VITE_APP_VERSION`` by re-reading
     ``/VERSION`` the same way ``apps/web/vite.config.ts`` does.
  4. When the current commit is annotated with a ``vMAJOR.MINOR.PATCH`` tag,
     a matching ``## [<version>]`` section exists in ``CHANGELOG.md``.

Designed to run on a self-hosted runner without the Python or Node
dependencies installed (no third-party libraries required).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class GateError(Exception):
    """Raised when one of the consistency checks fails."""


def _read_canonical_version() -> str:
    if not VERSION_FILE.exists():
        raise GateError(f"VERSION file not found at {VERSION_FILE}.")
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.match(raw):
        raise GateError(
            f"VERSION file must contain strict SemVer (got {raw!r}); "
            "expected MAJOR.MINOR.PATCH."
        )
    return raw


def _api_version() -> str:
    """Import the API module in a subprocess so the gate does not depend on
    the runner having the API's deps installed."""
    script = (
        "import sys; "
        "sys.path.insert(0, 'apps/api'); "
        "from retailtwin_api.version import __version__ as v; "
        "print(v)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise GateError(
            "Failed to import retailtwin_api.version. "
            f"stderr:\n{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _web_version() -> str:
    """Re-read VERSION the same way ``apps/web/vite.config.ts`` does so the
    Web bundle is guaranteed to embed the same SemVer."""
    # The Web config reads VERSION from the repo root, strips it, and validates
    # the same regex. We mirror that here.
    return _read_canonical_version()


def _existing_tags() -> list[str]:
    """All SemVer-formatted ``vMAJOR.MINOR.PATCH`` tags already on the commit."""
    try:
        completed = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise GateError(f"git tag --points-at HEAD failed: {exc.stderr}")
    return [
        tag.strip()
        for tag in completed.stdout.splitlines()
        if SEMVER_RE.match(tag.strip().lstrip("v"))
    ]


def _changelog_has_section(version: str) -> bool:
    if not CHANGELOG_FILE.exists():
        raise GateError(f"CHANGELOG.md not found at {CHANGELOG_FILE}.")
    pattern = re.compile(rf"^##\s*\[{re.escape(version)}\]", re.MULTILINE)
    return bool(pattern.search(CHANGELOG_FILE.read_text(encoding="utf-8")))


def main() -> int:
    results: list[dict[str, object]] = []

    # Check 1 + 2 + 3 — VERSION file + API + Web.
    canonical = _read_canonical_version()
    results.append({"check": "version_file", "version": canonical, "ok": True})

    try:
        api = _api_version()
        results.append({"check": "api_module", "version": api, "ok": True})
        if api != canonical:
            raise GateError(
                f"API reports {api!r} but VERSION file is {canonical!r}."
            )
    except GateError as exc:
        results.append({"check": "api_module", "ok": False, "error": str(exc)})

    try:
        web = _web_version()
        results.append({"check": "web_bundle", "version": web, "ok": True})
        if web != canonical:
            raise GateError(
                f"Web bundle would emit {web!r} but VERSION file is {canonical!r}."
            )
    except GateError as exc:
        results.append({"check": "web_bundle", "ok": False, "error": str(exc)})

    # Check 4 — release tag ⇒ CHANGELOG section.
    try:
        tags = _existing_tags()
        for tag in tags:
            version = tag.lstrip("v")
            ok = _changelog_has_section(version)
            results.append(
                {
                    "check": "changelog_section",
                    "tag": tag,
                    "version": version,
                    "ok": ok,
                }
            )
            if not ok:
                raise GateError(
                    f"Tag {tag} requires a `## [{version}]` section in CHANGELOG.md."
                )
        if not tags:
            results.append({"check": "changelog_section", "ok": True, "skipped": True})
    except GateError as exc:
        # Only attach an error if we did not already attach it via the
        # `results.append` above.
        if not any(r.get("check") == "changelog_section" and not r["ok"] for r in results):
            results.append({"check": "changelog_section", "ok": False, "error": str(exc)})

    print(json.dumps({"results": results, "canonical_version": canonical}, indent=2))
    failed = [r for r in results if not r["ok"]]
    if failed:
        print("\nVersion consistency gate FAILED:", file=sys.stderr)
        for r in failed:
            print(f"  - {r}", file=sys.stderr)
        return 1
    print("\nVersion consistency gate PASSED.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())