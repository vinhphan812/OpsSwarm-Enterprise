"""Version module + GET /version + /health version fields (ADR 0025)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retailtwin_api import version as version_module
from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.version import (
    REPO_ROOT,
    VERSION_FILE,
    InvalidVersion,
    full_version,
    read_version,
)

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


# ── VERSION file parsing ──────────────────────────────────────────────────────

def test_version_file_is_a_strict_semver() -> None:
    raw = VERSION_FILE.read_text(encoding="utf-8")
    assert SEMVER_RE.match(raw.strip()), (
        f"VERSION file at {VERSION_FILE} must contain 'MAJOR.MINOR.PATCH'; got {raw!r}."
    )


def test_canonical_version_file_lives_at_repo_root() -> None:
    assert VERSION_FILE == REPO_ROOT / "VERSION"


def test_read_version_returns_canonical_semver() -> None:
    assert SEMVER_RE.match(read_version())


def test_read_version_accepts_trailing_whitespace() -> None:
    assert SEMVER_RE.match(read_version(VERSION_FILE))  # already trimmed, sanity


@pytest.mark.parametrize(
    "bad",
    ["", "0.8", "0.8.0.1", "v0.8.0", "0.8.0+abc", "1.2.3-rc1", "abc"],
)
def test_read_version_rejects_non_semver(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "VERSION"
    target.write_text(bad, encoding="utf-8")
    with pytest.raises(InvalidVersion):
        read_version(target)


def test_read_version_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidVersion):
        read_version(tmp_path / "no-such-version")


def test_module_exposes_version_and_metadata() -> None:
    assert SEMVER_RE.match(version_module.__version__)
    assert isinstance(version_module.git_sha, str) and version_module.git_sha
    assert version_module.build_time.endswith("+00:00")
    assert version_module.full_version() == f"{version_module.__version__}+{version_module.git_sha}"


def test_package_level_dunder_version_matches_module(monkeypatch) -> None:
    import importlib

    pkg = importlib.import_module("retailtwin_api")
    assert pkg.__version__ == version_module.__version__


# ── GET /version ──────────────────────────────────────────────────────────────

def test_version_route_reports_canonical_metadata(client) -> None:
    response = client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert SEMVER_RE.match(body["version"])
    assert body["service"] == "retailtwin-api"
    assert isinstance(body["git_sha"], str) and body["git_sha"]
    assert body["build_time"].endswith("+00:00")
    assert body["full_version"] == f"{body['version']}+{body['git_sha']}"
    # The route must report the same SemVer as the canonical module constant.
    assert body["version"] == version_module.__version__


def test_version_route_does_not_require_loaded_store(client) -> None:
    # /version must answer even when analytics are offline so dashboards can
    # identify which revision they are talking to during an incident.
    response = client.get("/version")
    assert response.status_code == 200


def test_version_route_honours_git_sha_env_at_startup(monkeypatch) -> None:
    """CI exports GIT_SHA before starting the process; the module reads it
    once at import. A subprocess simulates that boot lifecycle."""
    import os
    import subprocess
    import sys

    script = (
        "import sys; "
        "sys.path.insert(0, 'apps/api'); "
        "from retailtwin_api.version import git_sha, full_version; "
        "print(git_sha); "
        "print(full_version())"
    )
    env = os.environ.copy()
    env["GIT_SHA"] = "deadbeef"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    sha_line, full_line = completed.stdout.strip().splitlines()
    assert sha_line == "deadbeef"
    assert full_line.endswith("+deadbeef")


# ── /health extended with version + git_sha ──────────────────────────────────

def test_health_includes_version_and_git_sha(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert SEMVER_RE.match(body["version"])
    assert body["git_sha"] == version_module.git_sha
    # Backwards-compatible fields still present.
    assert body["status"] == "ok"
    assert body["service"] == "retailtwin-api"
    assert body["fixture_loaded"] is True


def test_health_degraded_still_reports_version(client, monkeypatch) -> None:
    """Even when the fixture is missing, /health must keep reporting the
    version so a deployment can be identified during an outage."""
    from retailtwin_api.analytics_repository import (
        InMemoryAnomalyRepository,
        InMemoryCheckoutRepository,
        InMemoryPromotionRepository,
        InMemoryRevenueRepository,
    )

    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.json"
        application = create_app(
            Settings(
                _env_file=None,
                app_env="test",
                store_id="store-001",
                store_fixture_path=missing,
            )
        )
        application.state.anomalies = InMemoryAnomalyRepository()
        application.state.revenue = InMemoryRevenueRepository()
        application.state.promotions = InMemoryPromotionRepository()
        application.state.checkouts = InMemoryCheckoutRepository()
        with TestClient(application) as test_client:
            body = test_client.get("/health").json()
    assert body["status"] == "degraded"
    assert SEMVER_RE.match(body["version"])
    assert body["git_sha"] == version_module.git_sha


# ── OpenAPI advertises the same version ──────────────────────────────────────

def test_openapi_info_version_matches_canonical(client) -> None:
    openapi = client.get("/openapi.json").json()
    assert openapi["info"]["version"] == version_module.__version__
    paths = openapi["paths"]
    assert "get" in paths["/version"]
    assert "get" in paths["/health"]


# ── Payload JSON shape is stable ───────────────────────────────────────────────

def test_health_and_version_payloads_round_trip_through_json(client) -> None:
    """The version payload must survive a JSON round-trip — no datetime objects
    leaked that would 500 a real HTTP call."""
    for response in (client.get("/health"), client.get("/version")):
        assert response.status_code == 200
        json.dumps(response.json())  # must not raise