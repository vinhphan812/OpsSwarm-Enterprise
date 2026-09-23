"""Unit tests for opsswarm.api module.

These tests use dependency override to avoid module-level initialization.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self):
        """Health endpoint returns ok status."""
        # Import the app module and mock the module-level globals
        # by patching them BEFORE the FastAPI app is used
        import opsswarm.api as api_module

        # Store original values
        orig_engine = api_module.engine

        try:
            # Create mock engine
            mock_engine = MagicMock()
            mock_engine.runs = {}

            # Patch the module globals
            api_module.engine = mock_engine

            # Create test client
            client = TestClient(api_module.app)
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True
            assert data["version"] == "2.1.0"
            assert data["architecture"] == "openclaw+github"
        finally:
            # Restore original
            api_module.engine = orig_engine


class TestRunsEndpoints:
    """Tests for /runs endpoints."""

    def test_runs_empty(self):
        """GET /runs returns empty list."""
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        try:
            mock_engine = MagicMock()
            mock_engine.runs = {}

            api_module.engine = mock_engine
            client = TestClient(api_module.app)
            response = client.get("/runs")

            assert response.status_code == 200
            assert response.json() == []
        finally:
            api_module.engine = orig_engine

    def test_run_not_found(self):
        """GET /runs/{id} returns 404 for missing run."""
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        try:
            mock_engine = MagicMock()
            mock_engine.runs = {}

            api_module.engine = mock_engine
            client = TestClient(api_module.app)
            response = client.get("/runs/999")

            assert response.status_code == 404
        finally:
            api_module.engine = orig_engine


class TestEvidenceEndpoint:
    """Tests for evidence endpoints."""

    def test_evidence_not_found(self):
        """Returns 404 when run not found."""
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        try:
            mock_engine = MagicMock()
            mock_engine.runs = {}

            api_module.engine = mock_engine
            client = TestClient(api_module.app)
            response = client.get("/runs/999/evidence")

            assert response.status_code == 404
        finally:
            api_module.engine = orig_engine


class TestCheckpointEndpoint:
    """Tests for checkpoint endpoints."""

    def test_checkpoint_not_found(self):
        """Returns 404 when run not found."""
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        try:
            mock_engine = MagicMock()
            mock_engine.runs = {}

            api_module.engine = mock_engine
            client = TestClient(api_module.app)
            response = client.get("/runs/999/checkpoint")

            assert response.status_code == 404
        finally:
            api_module.engine = orig_engine


class TestResumeEndpoint:
    """Tests for resume endpoint."""

    def test_resume_not_found(self):
        """Returns 404 when run not found."""
        import opsswarm.api as api_module

        orig_engine = api_module.engine
        try:
            mock_engine = MagicMock()
            mock_engine.runs = {}

            api_module.engine = mock_engine
            client = TestClient(api_module.app)
            response = client.post("/runs/999/resume")

            assert response.status_code == 404
        finally:
            api_module.engine = orig_engine


class TestWebhookEndpoint:
    """Tests for webhook endpoints."""

    def test_webhook_missing_signature(self):
        """Rejects webhook without signature."""
        import opsswarm.api as api_module

        orig_verify = api_module.verify_signature
        try:
            # Mock verify_signature to return False
            api_module.verify_signature = lambda *args: False

            client = TestClient(api_module.app)
            response = client.post(
                "/webhooks/github",
                json={"action": "opened", "issue": {"number": "1"}},
                headers={"x-github-event": "issues"}
            )

            assert response.status_code == 401
        finally:
            api_module.verify_signature = orig_verify

    def test_webhook_ignored_event(self):
        """Ignores non-issue events."""
        import opsswarm.api as api_module

        orig_verify = api_module.verify_signature
        try:
            api_module.verify_signature = lambda *args: True

            client = TestClient(api_module.app)
            response = client.post(
                "/webhooks/github",
                json={"action": "push", "ref": "refs/heads/main"},
                headers={"x-github-event": "push", "x-hub-signature-256": "sha256=abc"}
            )

            assert response.status_code == 200
            assert response.json()["ignored"] is True
        finally:
            api_module.verify_signature = orig_verify
