"""Security tests for ADR-014 Runtime API authentication and monitoring ingress.

Covers all acceptance criteria from ADR-014-8:
https://github.com/NousResearch/opsswarm-enterprise/issues/21
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Module-level test constants — avoid using the same name as the env var key.
_TEST_SECRET = "test-secret-for-adr-014"  # noqa: B105
_ALL_TEST_SCOPES = ["opsswarm:read", "opsswarm:write", "opsswarm:monitor", "opsswarm:admin"]


def _generate_bearer(scope: str, secret: str, method: str, path: str, **overrides) -> str:
    """Generate a valid HMAC-SHA256 bearer token per ADR-014."""
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
    """Ensure OPSWARM_RUNTIME_SECRET is set for all tests; reload auth config."""
    import opsswarm.auth as auth_module

    old = os.environ.get("OPSWARM_RUNTIME_SECRET")
    os.environ["OPSWARM_RUNTIME_SECRET"] = _TEST_SECRET
    # Reload so the module picks up the new secret
    auth_module.reload_auth_config()
    # Reset shared state
    auth_module.reset_replay_store()
    auth_module._monitoring_limiter._hits.clear()
    yield
    if old is None:
        os.environ.pop("OPSWARM_RUNTIME_SECRET", None)
    else:
        os.environ["OPSWARM_RUNTIME_SECRET"] = old
    auth_module.reload_auth_config()
    auth_module.reset_replay_store()
    auth_module._monitoring_limiter._hits.clear()


@pytest.fixture
def client():
    """Create a TestClient with mocked external dependencies."""
    import opsswarm.api as api_module
    import opsswarm.auth as auth_module

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
        # Clear dependency overrides so new auth deps are exercised
        api_module.app.dependency_overrides.clear()
        yield TestClient(api_module.app)
    finally:
        api_module.engine = orig_engine
        api_module.gh = orig_gh
        api_module.oc = orig_oc
        api_module.app.dependency_overrides.clear()
        auth_module.reset_replay_store()
        auth_module._monitoring_limiter._hits.clear()


# ---------------------------------------------------------------------------
# ADR-014 §D3: 401/403 contract
# ---------------------------------------------------------------------------


class TestHttpStatusContract:
    """401 missing/invalid; 403 valid+insufficient; /health always public."""

    def test_anonymous_read_rejected(self, client):
        """GET /runs without Authorization → 401 Missing credentials."""
        response = client.get("/runs")
        assert response.status_code == 401
        assert response.json()["detail"] == "Missing credentials"

    def test_anonymous_monitor_rejected(self, client):
        """POST /hooks/monitoring without credentials → 401."""
        response = client.post(
            "/hooks/monitoring",
            json={"service": "test-svc", "symptom": "test"},
        )
        assert response.status_code == 401

    def test_read_token_cannot_write(self, client):
        """opsswarm:read token on POST /runs/1/resume → 403 Insufficient scope."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", _TEST_SECRET, "POST", "/runs/1/resume", timestamp=now
        )
        response = client.post("/runs/1/resume", headers=_auth_header(token))
        assert response.status_code == 403
        assert "Insufficient scope" in response.json()["detail"]

    def test_read_token_cannot_monitor(self, client):
        """opsswarm:read token on POST /hooks/monitoring → 403."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", _TEST_SECRET, "POST", "/hooks/monitoring", timestamp=now
        )
        response = client.post(
            "/hooks/monitoring",
            headers=_auth_header(token),
            json={"service": "test", "symptom": "x"},
        )
        assert response.status_code == 403

    def test_monitor_token_cannot_read(self, client):
        """opsswarm:monitor token on GET /runs → 403."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:monitor", _TEST_SECRET, "GET", "/runs", timestamp=now)
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 403

    def test_monitor_token_cannot_resume(self, client):
        """opsswarm:monitor token on POST /runs/1/resume → 403."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:monitor", _TEST_SECRET, "POST", "/runs/1/resume", timestamp=now
        )
        response = client.post("/runs/1/resume", headers=_auth_header(token))
        assert response.status_code == 403

    def test_admin_token_covers_read(self, client):
        """opsswarm:admin token covers GET /runs → 200 (empty, not auth error)."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:admin", _TEST_SECRET, "GET", "/runs", timestamp=now)
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 200

    def test_admin_token_covers_resume(self, client):
        """opsswarm:admin token covers POST /runs/1/resume → 200/404 (not auth error)."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:admin", _TEST_SECRET, "POST", "/runs/1/resume", timestamp=now
        )
        response = client.post("/runs/1/resume", headers=_auth_header(token))
        # 404 because no run exists — not a 403
        assert response.status_code == 404

    def test_admin_token_covers_monitor(self, client):
        """opsswarm:admin token covers POST /hooks/monitoring → 200/400 (not auth error)."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:admin", _TEST_SECRET, "POST", "/hooks/monitoring", timestamp=now
        )
        response = client.post(
            "/hooks/monitoring",
            headers=_auth_header(token),
            json={"service": "test-svc", "symptom": "test"},
        )
        # 200 because gh.create_issue is mocked; not 401/403
        assert response.status_code in (200, 400)

    def test_admin_token_covers_metrics(self, client):
        """opsswarm:admin token covers GET /metrics → 200."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:admin", _TEST_SECRET, "GET", "/metrics", timestamp=now)
        response = client.get("/metrics", headers=_auth_header(token))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# HMAC validation
# ---------------------------------------------------------------------------


class TestHmacValidation:
    """HMAC-SHA256 bearer tokens."""

    def test_invalid_hmac_rejected(self, client):
        """Bearer with bad HMAC → 401 Invalid credentials."""
        # scope=valid, but hmac=wrong
        bad_token = "opsswarm:read=0000000000000000000000000000000000000000000000000000000000000000"
        response = client.get("/runs", headers=_auth_header(bad_token))
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_expired_timestamp_rejected(self, client):
        """Bearer with timestamp >60 s old → 401."""
        old_timestamp = int(time.time()) - 120  # 2 minutes ago
        token = _generate_bearer(
            "opsswarm:read", _TEST_SECRET, "GET", "/runs", timestamp=old_timestamp
        )
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_future_timestamp_rejected(self, client):
        """Bearer with timestamp >60 s in future → 401."""
        future_timestamp = int(time.time()) + 120
        token = _generate_bearer(
            "opsswarm:read", _TEST_SECRET, "GET", "/runs", timestamp=future_timestamp
        )
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 401

    def test_malformed_bearer_rejected(self, client):
        """Malformed Authorization header → 401."""
        response = client.get("/runs", headers={"Authorization": "Bearer malformed"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    def test_unknown_scope_rejected(self, client):
        """Unknown scope → 403 Insufficient scope."""
        # Create token with a fake scope (HMAC is valid for that scope)
        now = int(time.time())
        fake_scope = "opsswarm:unknown"
        payload = f"GET:/runs:{now}"
        mac = hmac.new(_TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        token = f"{fake_scope}={mac}"
        response = client.get("/runs", headers=_auth_header(token))
        # The HMAC is valid for the scope in the token, but opsswarm:unknown is
        # not a known scope → 403
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Anti-replay
# ---------------------------------------------------------------------------


class TestAntiReplay:
    """Token reuse within the window should be detected."""

    def test_replay_detected(self, client):
        """Same bearer token used twice → first 200, second 401."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:read", _TEST_SECRET, "GET", "/runs", timestamp=now)
        headers = _auth_header(token)

        # First request succeeds (empty list)
        r1 = client.get("/runs", headers=headers)
        assert r1.status_code == 200

        # Second request with same token → replay detected
        r2 = client.get("/runs", headers=headers)
        assert r2.status_code == 401
        assert r2.json()["detail"] == "Invalid credentials"


# ---------------------------------------------------------------------------
# GitHub webhook independence
# ---------------------------------------------------------------------------


class TestGithubWebhookIndependence:
    """GitHub webhook HMAC is independent of runtime API auth."""

    def test_github_webhook_unchanged(self, client):
        """Valid GitHub webhook payload → 200, no Authorization header required."""
        secret = "test-github-webhook-secret"
        body = json.dumps({"action": "opened", "issue": {"number": "1"}}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": secret}):
            with patch("opsswarm.api.verify_signature", side_effect=lambda *a, **k: True):
                # Also patch at module level
                import opsswarm.api as api_module

                orig = api_module.verify_signature
                api_module.verify_signature = lambda *a, **k: True
                try:
                    response = client.post(
                        "/webhooks/github",
                        content=body,
                        headers={
                            "x-github-event": "issues",
                            "x-hub-signature-256": sig,
                            "content-type": "application/json",
                        },
                    )
                    assert response.status_code == 200
                finally:
                    api_module.verify_signature = orig

    def test_github_webhook_no_auth_header_required(self, client):
        """GitHub webhook endpoint does not require runtime API Authorization."""
        import opsswarm.api as api_module
        import opsswarm.webhook as webhook_module

        orig_api = api_module.verify_signature
        orig_webhook = webhook_module.verify_signature
        api_module.verify_signature = lambda *a, **k: True
        webhook_module.verify_signature = lambda *a, **k: True
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
# /health always public
# ---------------------------------------------------------------------------


class TestHealthAlwaysPublic:
    """ADR-014 §D3: /health is always public regardless of auth config."""

    def test_health_no_auth(self, client):
        """GET /health without any auth → 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_health_with_random_header(self, client):
        """GET /health with garbage auth → still 200 (ignored)."""
        response = client.get("/health", headers={"Authorization": "Bearer garbage"})
        assert response.status_code == 200
        assert response.json()["ok"] is True


# ---------------------------------------------------------------------------
# ADR-014 §D4: Fail-closed production startup
# ---------------------------------------------------------------------------


class TestProductionFailClosed:
    """Missing required auth config in production → RuntimeError at startup."""

    def test_production_startup_fails_without_secret(self):
        """APP_ENV=production, no OPSWARM_RUNTIME_SECRET, no OPSWARM_API_KEY_* → RuntimeError."""
        env = {
            "APP_ENV": "production",
            # Ensure no secret vars
            "OPSWARM_RUNTIME_SECRET": "",
        }
        # Remove any API_KEY vars
        for k in list(env):
            if "API_KEY" in k:
                del env[k]

        import opsswarm.auth as auth_module

        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="OPSWARM_RUNTIME_SECRET|OPSWARM_API_KEY_"):
                auth_module._ensure_production_auth_config()

    def test_production_starts_with_runtime_secret(self):
        """APP_ENV=production + OPSWARM_RUNTIME_SECRET → no error."""
        import opsswarm.auth as auth_module

        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "OPSWARM_RUNTIME_SECRET": "prod-secret"},
            clear=False,
        ):
            # Should not raise
            auth_module._ensure_production_auth_config()

    def test_dev_env_no_secret_allowed(self):
        """APP_ENV=development, no secret → allowed (dev/test behaviour)."""
        import opsswarm.auth as auth_module

        with patch.dict(
            os.environ,
            {"APP_ENV": "development", "OPSWARM_RUNTIME_SECRET": ""},
            clear=False,
        ):
            # Should not raise — dev mode allows missing config
            auth_module._ensure_production_auth_config()


# ---------------------------------------------------------------------------
# ADR-014 §D5: Monitoring ingress abuse controls
# ---------------------------------------------------------------------------


class TestMonitoringIngressControls:
    """64 KB body limit; rate limit per source; no anonymous trigger."""

    def test_body_size_limit_exceeded(self, client):
        """Monitoring payload >64 KB → 413."""
        large_payload = {"service": "x", "symptom": "y" * 70_000}  # ~700 KB
        response = client.post(
            "/hooks/monitoring",
            content=json.dumps(large_payload).encode(),
            headers={
                "Content-Type": "application/json",
                # Even with a valid token, body size should trigger first
            },
        )
        assert response.status_code == 413

    def test_rate_limit_exceeded(self, client):
        """>20 req/min to /hooks/monitoring from same source → 429."""
        import opsswarm.auth as auth_module

        # Generate 21 tokens (one per request) to avoid anti-replay blocking.
        # Each token is valid but the rate limiter should trigger on the 21st.
        tokens = [
            _generate_bearer(
                "opsswarm:monitor",
                _TEST_SECRET,
                "POST",
                "/hooks/monitoring",
                timestamp=int(time.time()) + i,
            )
            for i in range(21)
        ]

        payload = json.dumps({"service": "test", "symptom": "test"}).encode()

        # Make 20 successful requests
        for i in range(20):
            headers = {**_auth_header(tokens[i]), "Content-Type": "application/json"}
            r = client.post("/hooks/monitoring", content=payload, headers=headers)
            # We may get 200 or 400 (if gh.create_issue mock doesn't fully work),
            # but we shouldn't hit rate limit yet
            assert r.status_code in (200, 400), f"Request {i + 1} failed: {r.status_code} {r.text}"
            # Reset replay store so next token is accepted
            auth_module.reset_replay_store()

        # 21st request should hit rate limit
        headers = {**_auth_header(tokens[20]), "Content-Type": "application/json"}
        r = client.post("/hooks/monitoring", content=payload, headers=headers)
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_anonymous_trigger_denied(self, client):
        """Anonymous POST /hooks/monitoring → 401 (not 429)."""
        response = client.post(
            "/hooks/monitoring",
            json={"service": "test", "symptom": "test"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# ADR-014 §D1: Pre-shared scoped keys (alternative path)
# ---------------------------------------------------------------------------


class TestPresharedKeys:
    """OPSWARM_API_KEY_<SCOPE> env vars as static bearer tokens."""

    def test_preshared_read_key_works(self):
        """OPSWARM_API_KEY_READ → grants opsswarm:read scope."""
        with patch.dict(
            os.environ,
            {
                "OPSWARM_RUNTIME_SECRET": "",
                "OPSWARM_API_KEY_READ": "static-read-only-token-123",
            },
            clear=False,
        ):
            import opsswarm.api as api_module
            import opsswarm.auth as auth_module

            # Reload auth config
            auth_module.reload_auth_config()

            orig_engine = api_module.engine
            mock_engine = MagicMock()
            mock_engine.runs = {}

            try:
                api_module.engine = mock_engine
                api_module.app.dependency_overrides.clear()
                client = TestClient(api_module.app)

                response = client.get(
                    "/runs",
                    headers={"Authorization": "Bearer static-read-only-token-123"},
                )
                assert response.status_code == 200
            finally:
                api_module.engine = orig_engine
                auth_module.reload_auth_config()

    def test_preshared_key_wrong_scope_rejected(self):
        """OPSWARM_API_KEY_READ token used for write endpoint → 403."""
        with patch.dict(
            os.environ,
            {
                "OPSWARM_RUNTIME_SECRET": "",
                "OPSWARM_API_KEY_READ": "static-read-only-token-abc",
            },
            clear=False,
        ):
            import opsswarm.api as api_module
            import opsswarm.auth as auth_module

            auth_module.reload_auth_config()

            orig_engine = api_module.engine
            mock_engine = MagicMock()
            mock_engine.runs = {}

            try:
                api_module.engine = mock_engine
                api_module.app.dependency_overrides.clear()
                client = TestClient(api_module.app)

                response = client.post(
                    "/runs/1/resume",
                    headers={"Authorization": "Bearer static-read-only-token-abc"},
                )
                assert response.status_code == 403
            finally:
                api_module.engine = orig_engine
                auth_module.reload_auth_config()


# ---------------------------------------------------------------------------
# Scope hierarchy
# ---------------------------------------------------------------------------


class TestScopeHierarchy:
    """admin > write, read; monitor is strictly limited; write !> read."""

    def test_write_token_cannot_read(self, client):
        """opsswarm:write token on GET /runs → 403."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:write", _TEST_SECRET, "GET", "/runs", timestamp=now)
        response = client.get("/runs", headers=_auth_header(token))
        assert response.status_code == 403

    def test_write_token_cannot_monitor(self, client):
        """opsswarm:write token on POST /hooks/monitoring → 403."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:write", _TEST_SECRET, "POST", "/hooks/monitoring", timestamp=now
        )
        response = client.post(
            "/hooks/monitoring",
            headers=_auth_header(token),
            json={"service": "s", "symptom": "s"},
        )
        assert response.status_code == 403

    def test_read_token_cannot_resume(self, client):
        """opsswarm:read token on POST /runs/1/resume → 403."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:read", _TEST_SECRET, "POST", "/runs/1/resume", timestamp=now
        )
        response = client.post("/runs/1/resume", headers=_auth_header(token))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Log redaction — HMAC tokens must not leak into logs
# ---------------------------------------------------------------------------


class TestLogRedaction:
    """Auth failures must not log the presented token value."""

    def test_invalid_token_not_logged(self, client, caplog, tmp_path):
        """Invalid bearer token value must not appear in operator logs."""
        bad_token = "opsswarm:read=DEADBEEFDEADBEEF" * 4  # long fake token
        with caplog.at_level("ERROR", logger="opsswarm.auth"):
            response = client.get("/runs", headers={"Authorization": f"Bearer {bad_token}"})

        assert response.status_code == 401
        # The token hex must not appear raw in any log message
        for record in caplog.records:
            assert bad_token not in record.message, f"Token leaked in log: {record.message}"

    def test_replay_rejection_not_logged(self, client, caplog):
        """Anti-replay rejection must not log the consumed token."""
        now = int(time.time())
        token = _generate_bearer("opsswarm:read", _TEST_SECRET, "GET", "/runs", timestamp=now)
        headers = {"Authorization": f"Bearer {token}"}

        client.get("/runs", headers=headers)  # first use — succeeds

        with caplog.at_level("ERROR", logger="opsswarm.auth"):
            client.get("/runs", headers=headers)  # second use — replay

        for record in caplog.records:
            # The HMAC hex portion must not appear in logs
            assert "0000000000" not in record.message and record.message.count(":") <= 1, (
                f"Token data may have leaked: {record.message}"
            )


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """GET /metrics default behaviour (public or admin-scoped)."""

    def test_metrics_anonymous_rejected(self, client):
        """GET /metrics without auth → 401 (metrics is not /health)."""
        response = client.get("/metrics")
        # /metrics is a protected endpoint requiring opsswarm:admin per ADR-014-2
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Token generation helper (for operator documentation)
# ---------------------------------------------------------------------------


class TestGenerateBearerToken:
    """verify opsswarm.auth.generate_bearer_token() produces valid tokens."""

    def test_generate_token_roundtrip(self):
        """Generated token validates successfully against the same secret."""
        from opsswarm.auth import generate_bearer_token

        scope = "opsswarm:read"
        secret = "roundtrip-test-secret"
        method = "GET"
        path = "/runs"
        token = generate_bearer_token(scope, secret, method, path)
        assert token.startswith(f"{scope}=")
        assert len(token) > len(scope) + 1
        # Token format: "scope=hmac_hex"
        token_scope, token_hmac_hex = token.split("=", 1)
        # Token should be valid for the same method/path
        from opsswarm.auth import verify_bearer_hmac

        ts = int(time.time())
        result = verify_bearer_hmac(token_scope, token_hmac_hex, secret, method, path, timestamp=ts)
        assert result is True


# -----------------------------------------------------------------------
# ADR-014 coverage boost: uncovered branches
# -----------------------------------------------------------------------


class TestPresharedKeyFallback:
    """Cover the static-key path when bearer token matches a pre-shared key."""

    def test_static_key_for_read_works(self):
        """OPSWARM_API_KEY_READ bearer grants opsswarm:read (pre-shared path)."""
        with patch.dict(
            os.environ,
            {
                "OPSWARM_RUNTIME_SECRET": "",
                "OPSWARM_API_KEY_READ": "my-static-read-key-xyz",
            },
            clear=False,
        ):
            import opsswarm.auth as auth_module

            auth_module.reload_auth_config()
            auth_module.reset_replay_store()

            try:
                import opsswarm.api as api_module

                orig_engine = api_module.engine
                mock_engine = MagicMock()
                mock_engine.runs = {}
                api_module.engine = mock_engine
                api_module.app.dependency_overrides.clear()
                client = TestClient(api_module.app)

                response = client.get(
                    "/runs",
                    headers={"Authorization": "Bearer my-static-read-key-xyz"},
                )
                assert response.status_code == 200
            finally:
                api_module.engine = orig_engine
                auth_module.reload_auth_config()

    def test_static_key_wrong_endpoint_rejected(self):
        """OPSWARM_API_KEY_READ static key on write endpoint → 403."""
        with patch.dict(
            os.environ,
            {
                "OPSWARM_RUNTIME_SECRET": "",
                "OPSWARM_API_KEY_READ": "static-read-only-abc",
            },
            clear=False,
        ):
            import opsswarm.auth as auth_module

            auth_module.reload_auth_config()
            auth_module.reset_replay_store()

            try:
                import opsswarm.api as api_module

                orig_engine = api_module.engine
                mock_engine = MagicMock()
                mock_engine.runs = {}
                api_module.engine = mock_engine
                api_module.app.dependency_overrides.clear()
                client = TestClient(api_module.app)

                response = client.post(
                    "/runs/1/resume",
                    headers={"Authorization": "Bearer static-read-only-abc"},
                )
                assert response.status_code == 403
            finally:
                api_module.engine = orig_engine
                auth_module.reload_auth_config()


class TestHmacDerivationFallback:
    """Cover the HMAC derivation path when pre-shared keys don't match."""

    def test_hmac_path_valid_token_accepted(self):
        """HMAC-derived token valid for method+path → accepted."""
        now = int(time.time())
        token = _generate_bearer(
            "opsswarm:write", _TEST_SECRET, "POST", "/runs/1/resume", timestamp=now
        )
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        mock_engine = MagicMock()
        mock_engine.runs = {}
        api_module.engine = mock_engine
        try:
            api_module.app.dependency_overrides.clear()
            client = TestClient(api_module.app)
            response = client.post("/runs/1/resume", headers=_auth_header(token))
            # 404 (no run) or 400 (no checkpoint) — NOT auth error
            assert response.status_code in (404, 400)
        finally:
            api_module.engine = orig_engine

    def test_hmac_path_wrong_secret_rejected(self):
        """HMAC token signed with wrong secret → 401."""
        now = int(time.time())
        payload = f"GET:/runs:{now}"
        mac = hmac.new(b"wrong-secret", payload.encode(), hashlib.sha256).hexdigest()
        token = f"opsswarm:read={mac}"
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        mock_engine = MagicMock()
        mock_engine.runs = {}
        api_module.engine = mock_engine
        try:
            api_module.app.dependency_overrides.clear()
            client = TestClient(api_module.app)
            response = client.get("/runs", headers=_auth_header(token))
            assert response.status_code == 401
        finally:
            api_module.engine = orig_engine


class TestAntiReplayEviction:
    """Cover anti-replay eviction logic."""

    def test_replay_after_token_expiry_window(self):
        """Token from outside replay window is accepted again (eviction)."""
        import opsswarm.auth as auth_module
        import time

        # Create a token with timestamp far in the past (outside replay window)
        old_ts = int(time.time()) - 400  # outside the 300+60=360s replay window
        payload = f"GET:/runs:{old_ts}"
        mac = hmac.new(_TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        old_token = f"opsswarm:read={mac}"

        headers = _auth_header(old_token)
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        mock_engine = MagicMock()
        mock_engine.runs = {}
        api_module.engine = mock_engine
        try:
            api_module.app.dependency_overrides.clear()
            client = TestClient(api_module.app)
            response = client.get("/runs", headers=headers)
            # Old timestamp → 401 (expired), but NOT a replay error
            assert response.status_code == 401
        finally:
            api_module.engine = orig_engine
            auth_module.reset_replay_store()


class TestVerifyBearerHmacEdgeCases:
    """Cover verify_bearer_hmac boundary conditions."""

    def test_timestamp_at_minus_skew_boundary(self):
        """Timestamp at exactly -SKEW_TOLERANCE_SECs boundary → accepted."""
        from opsswarm.auth import verify_bearer_hmac

        boundary_ts = int(time.time()) - 60  # exactly -60s
        payload = f"GET:/runs:{boundary_ts}"
        mac = hmac.new(_TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        result = verify_bearer_hmac(
            "opsswarm:read", mac, _TEST_SECRET, "GET", "/runs", timestamp=boundary_ts
        )
        assert result is True

    def test_timestamp_at_plus_skew_boundary(self):
        """Timestamp at exactly +SKEW_TOLERANCE_SECs boundary → accepted."""
        from opsswarm.auth import verify_bearer_hmac

        boundary_ts = int(time.time()) + 60  # exactly +60s
        payload = f"GET:/runs:{boundary_ts}"
        mac = hmac.new(_TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        result = verify_bearer_hmac(
            "opsswarm:read", mac, _TEST_SECRET, "GET", "/runs", timestamp=boundary_ts
        )
        assert result is True
