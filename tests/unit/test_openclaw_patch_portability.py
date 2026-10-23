"""Portability checks for the committed OpenClaw configuration template."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "openclaw" / "openclaw.patch.json5"
PLACEHOLDER = "REPLACE_WITH_ABSOLUTE_REPO_PATH"
EXPECTED_SUFFIXES = (
    "/openclaw/workspaces/opsswarm-incident-manager",
    "/openclaw/workspaces/opsswarm-observability-investigator",
    "/openclaw/workspaces/opsswarm-application-investigator",
    "/openclaw/workspaces/opsswarm-infrastructure-investigator",
    "/openclaw/workspaces/opsswarm-database-investigator",
    "/openclaw/workspaces/opsswarm-recovery-responder",
    "/openclaw/workspaces/opsswarm-communications-postmortem",
    "/skills",
)


def test_openclaw_patch_uses_documented_portable_placeholders() -> None:
    patch = PATCH.read_text(encoding="utf-8")

    assert patch.count(PLACEHOLDER) == len(EXPECTED_SUFFIXES)
    for suffix in EXPECTED_SUFFIXES:
        assert f'"{PLACEHOLDER}{suffix}"' in patch


def test_openclaw_patch_does_not_commit_a_developer_checkout() -> None:
    patch = PATCH.read_text(encoding="utf-8")

    assert "D:/competitions/" not in patch
    assert "C:/Users/" not in patch
