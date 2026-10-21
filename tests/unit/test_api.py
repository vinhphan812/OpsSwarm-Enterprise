"""Unit tests for opsswarm.api module.

These tests use dependency override to avoid module-level initialization.
They verify the API contract (status codes, error shapes) with mocked engines.
"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import opsswarm

# ---------------------------------------------------------------------------
# Shared reset fixture (avoids auth state pollution between test modules)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """Reset auth module state before each test to avoid cross-test pollution."""
    import opsswarm.auth as auth_module

    auth_module.reset_replay_store()
    auth_module._monitoring_limiter._hits.clear()
    auth_module.reload_auth_config()
    yield
    auth_module.reset_replay_store()
    auth_module._monitoring_limiter._hits.clear()


# ---------------------------------------------------------------------------
# Token helpers (same as security tests)
# ---------------------------------------------------------------------------


def _generate_bearer(scope: str, secret: str, method: str, path: str, **overrides) -> str:
    import hashlib
    import hmac

    timestamp = overrides.get("timestamp", int(time.time()))
    payload = f"{method}:{path}:{timestamp}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{scope}={mac}"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_secret():
    import opsswarm.auth as auth_module

    old = os.environ.get("OPSWARM_RUNTIME_SECRET")
    os.environ["OPSWARM_RUNTIME_SECRET"] = "test-secret"  # noqa: B105
    auth_module.reload_auth_config()
    yield
    if old is None:
        os.environ.pop("OPSWARM_RUNTIME_SECRET", None)
    else:
        os.environ["OPSWARM_RUNTIME_SECRET"] = old
    auth_module.reload_auth_config()


@pytest.fixture
def client():
    import opsswarm.api as api_module

    orig_engine = api_module.engine
    orig_gh = api_module.gh
    orig_oc = api_module.oc

    mock_gh = MagicMock()
    mock_gh.create_issue = AsyncMock(
        return_value={"number": "1", "html_url": "https://github.com/test/repo/issues/1"}
    )
    mock_gh.permission = AsyncMock(return_value="write")
    mock_gh.comment = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.runs = {}
    mock_engine.start_issue = AsyncMock()
    mock_engine.handle_comment = AsyncMock()

    mock_oc = MagicMock()

    try:
        api_module.gh = mock_gh
        api_module.engine = mock_engine
        api_module.oc = mock_oc
        api_module.app.dependency_overrides.clear()
        yield TestClient(api_module.app)
    finally:
        api_module.engine = orig_engine
        api_module.gh = orig_gh
        api_module.oc = orig_oc
        api_module.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["version"] == opsswarm.__version__
        assert data["architecture"] == "openclaw+github"


# ---------------------------------------------------------------------------
# /runs endpoints (require auth; 404 when not found)
# ---------------------------------------------------------------------------


class TestRunsEndpoints:
    def test_runs_empty(self, client):
        now = int(time.time())
        token = _generate_bearer("opsswarm:read", "test-secret", "GET", "/runs", timestamp=now)
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 200
        assert response.json() == []

    def test_runs_requires_auth(self, client):
        response = client.get("/runs")
        assert response.status_code == 401

    def test_run_not_found(self, client):
        now = int(time.time())
        token = _generate_bearer("opsswarm:read", "test-secret", "GET", "/runs/999", timestamp=now)
        response = client.get("/runs/999", headers=_auth_header(token))
        assert response.status_code == 404

    def test_run_wrong_scope(self, client):
        now = int(time.time())
        token = _generate_bearer("opsswarm:monitor", "test-secret", "GET", "/runs", timestamp=now)
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Evidence endpoint
# ---------------------------------------------------------------------------


class TestEvidenceEndpoint:
    def test_evidence_not_found(self, client):
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", "test-secret", "GET", "/runs/999/evidence", timestamp=now
        )
        response = client.get("/runs/999/evidence", headers=_auth_header(token))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Checkpoint endpoint
# ---------------------------------------------------------------------------


class TestCheckpointEndpoint:
    def test_checkpoint_not_found(self, client):
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", "test-secret", "GET", "/runs/999/checkpoint", timestamp=now
        )
        response = client.get("/runs/999/checkpoint", headers=_auth_header(token))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Resume endpoint
# ---------------------------------------------------------------------------


class TestResumeEndpoint:
    def test_resume_not_found(self, client):
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:write", "test-secret", "POST", "/runs/999/resume", timestamp=now
        )
        response = client.post("/runs/999/resume", headers=_auth_header(token))
        assert response.status_code == 404

    def test_resume_requires_auth(self, client):
        response = client.post("/runs/999/resume")
        assert response.status_code == 401

    def test_resume_wrong_scope(self, client):
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", "test-secret", "POST", "/runs/999/resume", timestamp=now
        )
        response = client.post("/runs/999/resume", headers=_auth_header(token))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


class TestWebhookEndpoint:
    def test_webhook_missing_signature(self, client):
        import opsswarm.api as api_module

        orig = api_module.verify_signature
        try:
            api_module.verify_signature = lambda *args, **kwargs: False
            response = client.post(
                "/webhooks/github",
                json={"action": "opened", "issue": {"number": "1"}},
                headers={"x-github-event": "issues"},
            )
            assert response.status_code == 401
        finally:
            api_module.verify_signature = orig

    def test_webhook_ignored_event(self, client):
        import opsswarm.api as api_module

        orig = api_module.verify_signature
        try:
            api_module.verify_signature = lambda *args, **kwargs: True
            response = client.post(
                "/webhooks/github",
                json={"action": "push", "ref": "refs/heads/main"},
                headers={
                    "x-github-event": "push",
                    "x-hub-signature-256": "sha256=abc",
                },
            )
            assert response.status_code == 200
            assert response.json()["ignored"] is True
        finally:
            api_module.verify_signature = orig

    def test_webhook_no_runtime_api_auth_required(self, client):
        """GitHub webhook endpoint does not require runtime API Authorization."""
        import opsswarm.api as api_module
        import opsswarm.webhook as webhook_module

        orig_api = api_module.verify_signature
        orig_webhook = webhook_module.verify_signature
        api_module.verify_signature = lambda *args, **kwargs: True
        webhook_module.verify_signature = lambda *args, **kwargs: True
        try:
            response = client.post(
                "/webhooks/github",
                json={"action": "opened", "issue": {"number": "1"}},
                headers={"x-github-event": "issues"},
            )
            # 200 because GitHub HMAC is accepted via patch; no runtime API auth required
            assert response.status_code == 200
        finally:
            api_module.verify_signature = orig_api
            webhook_module.verify_signature = orig_webhook


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_metrics_requires_auth(self, client):
        response = client.get("/metrics")
        assert response.status_code == 401

    def test_metrics_admin_token(self, client):
        now = int(time.time())
        token = _generate_bearer("opsswarm:admin", "test-secret", "GET", "/metrics", timestamp=now)
        response = client.get("/metrics", headers=_auth_header(token))
        assert response.status_code == 200

    def test_metrics_read_token_insufficient(self, client):
        now = int(time.time())
        token = _generate_bearer("opsswarm:read", "test-secret", "GET", "/metrics", timestamp=now)
        response = client.get("/metrics", headers=_auth_header(token))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# /ready endpoint — HA coordination readiness probe (ADR-030 § Readiness Probe)
# ---------------------------------------------------------------------------


class TestReadyEndpoint:
    """Tests for the /ready readiness probe.

    Phase 7 acceptance criteria: /ready returns 200 unconditionally when
    ha.enabled = false (backward-compatible). When ha.enabled = true, it
    returns 503 fail-closed until Postgres is reachable and this instance
    has verified its leases.
    """

    def test_ready_legacy_mode_ha_disabled(self, client):
        """When ha.enabled = false (default), /ready returns 200 with legacy mode.

        This is the backward-compatible default. No Postgres connection is needed.
        """
        # get_ha is imported inside the /ready function from opsswarm.config
        with patch("opsswarm.config.get_ha", return_value={"enabled": False}):
            response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["mode"] == "legacy"

    def _ha_ready(self, client, ha_cfg: dict, mock_ha_db: MagicMock | None = None) -> "TestClient.response":
        """Helper: inject mock ha_db into sys.modules and call /ready.

        Pass mock_ha_db=None to simulate the module not being importable
        (raises ImportError when ha.enabled=true).
        """
        import sys
        # Store real module if already loaded
        real_ha_db = sys.modules.get("opsswarm.ha_db")
        try:
            if mock_ha_db is None:
                # Simulate the module not being importable
                sys.modules["opsswarm.ha_db"] = None
            else:
                sys.modules["opsswarm.ha_db"] = mock_ha_db
            with patch("opsswarm.config.get_ha", return_value=ha_cfg):
                return client.get("/ready")
        finally:
            if real_ha_db is not None:
                sys.modules["opsswarm.ha_db"] = real_ha_db
            else:
                sys.modules.pop("opsswarm.ha_db", None)

    def test_ready_ha_mode_postgres_healthy_with_leases(self, client):
        """When ha.enabled = true and Postgres is reachable with leases, /ready returns 200."""
        mock_ha_db = MagicMock()
        mock_ha_db.check_postgres_health = AsyncMock(return_value=True)
        mock_ha_db.check_instance_leases = AsyncMock(return_value=(True, 3))

        response = self._ha_ready(client, {"enabled": True}, mock_ha_db)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["mode"] == "ha"
        assert data["active_leases"] == 3

    def test_ready_ha_mode_postgres_healthy_no_leases(self, client):
        """When ha.enabled = true and Postgres is reachable but no active leases, /ready returns 200."""
        mock_ha_db = MagicMock()
        mock_ha_db.check_postgres_health = AsyncMock(return_value=True)
        mock_ha_db.check_instance_leases = AsyncMock(return_value=(False, 0))

        response = self._ha_ready(client, {"enabled": True}, mock_ha_db)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["mode"] == "ha"
        assert data["active_leases"] == 0

    def test_ready_ha_mode_postgres_unreachable(self, client):
        """When ha.enabled = true but Postgres is unreachable, /ready returns 503 fail-closed."""
        mock_ha_db = MagicMock()
        mock_ha_db.check_postgres_health = AsyncMock(return_value=False)

        response = self._ha_ready(client, {"enabled": True}, mock_ha_db)

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "not ready"
        assert "postgres" in data["detail"]["reason"].lower()

    def test_ready_ha_mode_postgres_raises_exception(self, client):
        """When ha.enabled = true but Postgres health check raises, /ready returns 503."""
        mock_ha_db = MagicMock()
        mock_ha_db.check_postgres_health = AsyncMock(side_effect=RuntimeError("connection refused"))

        response = self._ha_ready(client, {"enabled": True}, mock_ha_db)

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "not ready"
        assert "postgres unavailable" in data["detail"]["reason"]

    def test_ready_ha_mode_lease_check_raises(self, client):
        """When ha.enabled = true but lease check raises, /ready returns 503."""
        mock_ha_db = MagicMock()
        mock_ha_db.check_postgres_health = AsyncMock(return_value=True)
        mock_ha_db.check_instance_leases = AsyncMock(side_effect=RuntimeError("deadlock detected"))

        response = self._ha_ready(client, {"enabled": True}, mock_ha_db)

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "not ready"
        assert "lease check failed" in data["detail"]["reason"]

    def test_ready_ha_mode_ha_db_module_unavailable(self, client):
        """When ha.enabled = true but ha_db module can't be imported, /ready returns 503.

        This covers the except ImportError branch in /ready (api.py lines 179-180).
        """
        response = self._ha_ready(client, {"enabled": True}, mock_ha_db=None)

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["status"] == "not ready"
        assert "ha_db module unavailable" in data["detail"]["reason"]
