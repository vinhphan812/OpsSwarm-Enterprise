"""Unit tests for opsswarm.api module.

These tests use dependency override to avoid module-level initialization.
They verify the API contract (status codes, error shapes) with mocked engines.
"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock

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
# /ready (Issue #73)
# ---------------------------------------------------------------------------


class TestReadyEndpoint:
    def test_ready_returns_200_when_ready(self, client):
        """When lifecycle state is READY, /ready returns 200."""
        import opsswarm.api as api_module

        # Set the lifecycle to READY
        api_module.lifecycle.set_ready()

        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["state"] == "ready"
        assert data["accepting_work"] is True

    def test_ready_returns_503_when_starting(self, client):
        """When lifecycle state is STARTING, /ready returns 503."""
        import opsswarm.api as api_module

        # Reset to STARTING state (use the singleton's lock for thread safety)
        api_module.lifecycle._state = api_module.AppState.STARTING

        response = client.get("/ready")
        assert response.status_code == 503
        # HTTPException detail is in response.json()["detail"]
        data = response.json()
        detail = data.get("detail", data)  # Handle both direct and HTTPException format
        assert detail["ready"] is False
        assert detail["state"] == "starting"
        assert detail["accepting_work"] is False

    def test_ready_returns_503_when_draining(self, client):
        """When lifecycle state is DRAINING, /ready returns 503."""
        import opsswarm.api as api_module

        # Set the lifecycle to READY first, then to DRAINING
        # (set_draining only transitions from READY -> DRAINING)
        api_module.lifecycle.set_ready()
        api_module.lifecycle.set_draining()

        response = client.get("/ready")
        assert response.status_code == 503
        # HTTPException detail is in response.json()["detail"]
        data = response.json()
        detail = data.get("detail", data)  # Handle both direct and HTTPException format
        assert detail["ready"] is False
        assert detail["state"] == "draining"
        assert detail["accepting_work"] is False

    def test_ready_returns_503_when_failed(self, client):
        """When lifecycle state is FAILED, /ready returns 503."""
        import opsswarm.api as api_module

        # Set the lifecycle to FAILED
        api_module.lifecycle.set_failed("Startup error")

        response = client.get("/ready")
        assert response.status_code == 503
        # HTTPException detail is in response.json()["detail"]
        data = response.json()
        detail = data.get("detail", data)  # Handle both direct and HTTPException format
        assert detail["ready"] is False
        assert detail["state"] == "failed"
        assert detail["accepting_work"] is False

    def test_ready_no_sensitive_info_leak(self, client):
        """Ensure /ready response does not leak sensitive information."""
        import opsswarm.api as api_module

        # Set to FAILED with a message that could contain sensitive info
        api_module.lifecycle.set_failed("Auth token expired: secret_abc123")

        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()

        # The detail should NOT contain the sensitive error message
        # (It should be a clean response with state info)
        # HTTPException wraps detail in a nested "detail" key
        detail = data.get("detail", data)
        assert "secret" not in str(detail).lower()
        assert "token" not in str(detail).lower()
        # Ensure we return clean state information
        assert detail["state"] == "failed"


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
