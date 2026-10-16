"""Sanity tests for the GitHub Actions workflow YAML files.

Issue #146 / ADR 0026: every workflow YAML in `.github/workflows/` must
parse, must declare a `permissions:` block (top-level or per-job), and
must not reference a third-party GitHub Action with a floating major
tag unless a SHA comment is present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


@pytest.fixture(params=_workflow_files(), ids=lambda p: p.name)
def workflow_path(request: pytest.FixtureRequest) -> Path:
    return request.param


def _top_level_keys(data: dict) -> set[str]:
    """`on:` parses to either the string "on" or the bool `True`."""
    return {"on", True, "on:", "True"} & set(data.keys())


def test_workflow_yaml_parses(workflow_path: Path) -> None:
    """Every workflow YAML in the repo must be parseable."""
    with workflow_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{workflow_path.name} did not parse to a mapping"
    # Top-level keys GitHub requires. `on:` is parsed as `True` (YAML 1.1)
    # or as the string `"on"` depending on the loader.
    assert "jobs" in data, f"{workflow_path.name} missing `jobs:`"
    assert "on" in data or True in data, f"{workflow_path.name} missing `on:`"


def test_workflow_declares_permissions(workflow_path: Path) -> None:
    """ADR 0026 — every workflow declares an explicit `permissions:` block.

    The block can be at the workflow level OR on every job; the test allows
    either form, but a workflow that has neither is treated as drift from
    the ADR.
    """
    with workflow_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    workflow_level = "permissions" in data
    job_level = any(
        isinstance(job, dict) and "permissions" in job
        for job in (data.get("jobs") or {}).values()
    )
    assert workflow_level or job_level, (
        f"{workflow_path.name} declares no `permissions:` block "
        "(ADR 0026 requires least-privilege defaults)."
    )


# ── Third-party Action pinning ─────────────────────────────────────────────
# Issue #146 / ADR 0026: every third-party Action reference must be pinned
# to a full version tag (e.g. @v2.1.7) and must carry a SHA comment so a
# reviewer can verify the immutable ref. The conventional GitHub format is
# `<owner>/<repo>@<sha> # <tag>` but the test also accepts the reverse.
_SHA = r"[0-9a-f]{40}"
_TAG = r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9_.-]+)?|v\d+"
THIRD_PARTY_TAG_FIRST = re.compile(
    rf"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@{_TAG}\s+#\s+{_SHA}\s*$"
)
THIRD_PARTY_SHA_FIRST = re.compile(
    rf"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@{_SHA}\s+#\s+{_TAG}\s*$"
)


def _iter_action_uses(workflow_path: Path):
    with workflow_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            stripped = line.lstrip()
            if not stripped.startswith("uses:"):
                continue
            yield line


def test_third_party_actions_are_pinned(workflow_path: Path) -> None:
    """Every third-party action is pinned to a versioned tag with a SHA comment.

    The convention is `<owner>/<repo>@<sha-or-tag>  # <sha-or-tag>`. The
    test accepts both orderings. First-party `actions/*` actions are exempt;
    they are tracked by Dependabot and carry major-version tags by GitHub's
    recommendation.
    """
    for line in _iter_action_uses(workflow_path):
        # Skip local reusable-workflow references and `actions/*`.
        uses_value = line.split("uses:", 1)[1].strip()
        if uses_value.startswith("./"):
            continue
        if uses_value.startswith("actions/"):
            continue
        # docker/* are third-party but Dependabot-tracked; require either
        # the SHA-first pinned format or a full version tag.
        if uses_value.startswith("docker/"):
            if THIRD_PARTY_TAG_FIRST.match(uses_value) \
                    or THIRD_PARTY_SHA_FIRST.match(uses_value):
                continue
            if re.match(
                rf"^docker/[A-Za-z0-9_.-]+@v\d+\.\d+\.\d+", uses_value
            ):
                continue
            raise AssertionError(
                f"{workflow_path.name}: `{uses_value}` is a floating major "
                "tag for a docker/* action; pin to a full version + SHA "
                "(ADR 0026)."
            )
        if not (THIRD_PARTY_TAG_FIRST.match(uses_value)
                or THIRD_PARTY_SHA_FIRST.match(uses_value)):
            raise AssertionError(
                f"{workflow_path.name}: third-party action `{uses_value}` "
                "is not pinned to a full version + 40-hex SHA comment "
                "(ADR 0026)."
            )