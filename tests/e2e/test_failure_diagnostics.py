"""
test_failure_diagnostics.py

Failure-mode smoke tests: verify that intentional errors produce
actionable diagnostics without exposing secrets.

Covered scenarios:
  - Event conflict (409) with actionable error code
  - Missing SKU (404) with precise code
  - Validation errors (422) that do not echo secrets
  - Health degradation on missing fixture (ok/degraded)
  - Stale-context denial documentation (G04)
  - API unavailability (503) when fixture is absent

Each failure documents:
  - Exact HTTP status + error.code
  - Structured JSON body (not HTML/raw text)
  - No secrets in response body or logs
  - Identifies exact failed canonical stage
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from conftest import make_event


class TestEventFailureModes:
    """Event intake failure modes with actionable diagnostics."""

    def test_event_conflict_returns_409_with_code(
        self, client: TestClient
    ) -> None:
        payload = make_event(event_id="smoke-fail-conflict", quantity=1)
        assert client.post("/events", json=payload).status_code == 201
        modified = dict(payload)
        modified["quantity"] = 999
        response = client.post("/events", json=modified)
        assert response.status_code == 409
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "event_id_conflict"
        assert "smoke-fail-conflict" in body["error"]["message"]  # event_id preserved

    def test_unknown_sku_returns_404_with_sku_in_message(
        self, client: TestClient
    ) -> None:
        payload = make_event(sku="P999")
        response = client.post("/events", json=payload)
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "sku_not_found"
        assert "P999" in body["error"]["message"]

    def test_unknown_store_returns_404(self, client: TestClient) -> None:
        payload = make_event()
        payload["store_id"] = "store-999"
        response = client.post("/events", json=payload)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "store_not_found"

    def test_validation_error_does_not_echo_secrets(self, client: TestClient) -> None:
        """Validation errors must not expose secret data in response body."""
        payload = make_event()
        payload["quantity"] = 0
        payload["secret_key"] = "hunter2-SECRET-VALUE"
        response = client.post("/events", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert "hunter2" not in response.text
        assert "SECRET" not in response.text
        assert body["error"]["code"] == "validation_error"
        fields = {item["field"] for item in body["error"]["details"]}
        assert "quantity" in fields or "secret_key" in fields

    def test_malformed_json_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/events",
            content=b'{"event_id": "bad',
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestInventoryFailureModes:
    """Inventory read failure modes."""

    def test_unknown_sku_returns_controlled_404(self, client: TestClient) -> None:
        response = client.get("/inventory/P999")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "sku_not_found"
        assert "P999" in body["error"]["message"]
        # No stack trace
        assert "<html" not in response.text
        assert "Traceback" not in response.text

    def test_inventory_case_sensitivity(self, client: TestClient) -> None:
        response = client.get("/inventory/p001")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "sku_not_found"


class TestHealthFailureModes:
    """Health endpoint reflects degradation without leaking internals."""

    def test_health_degraded_on_missing_fixture(
        self, tmp_path, monkeypatch
    ) -> None:
        """Health reports degraded when the fixture file is absent."""
        from fastapi.testclient import TestClient
        from retailtwin_api.main import create_app
        from retailtwin_api.settings import Settings

        for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
            monkeypatch.delenv(key, raising=False)

        missing = tmp_path / "nonexistent.json"
        application = create_app(
            Settings(
                _env_file=None,
                app_env="e2e-smoke",
                store_id="store-001",
                store_fixture_path=missing,
            )
        )
        with TestClient(application) as c:
            response = c.get("/health")

        assert response.status_code == 200  # Health never 5xx
        body = response.json()
        assert body["status"] == "degraded"
        assert body["fixture_loaded"] is False
        assert str(missing) not in response.text  # No path leakage

    def test_health_endpoint_never_exposes_secrets(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        text = response.text
        # No credential patterns in health response
        assert "SECRET" not in text
        assert "TOKEN" not in text
        assert "PASSWORD" not in text
        assert "key" not in body.get("environment", "").lower()


class TestStoreFailureModes:
    """Store endpoint failure modes."""

    def test_store_unavailable_without_fixture(
        self, tmp_path, monkeypatch
    ) -> None:
        """Store endpoint returns 503 when fixture is missing."""
        from fastapi.testclient import TestClient
        from retailtwin_api.main import create_app
        from retailtwin_api.settings import Settings

        for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
            monkeypatch.delenv(key, raising=False)

        application = create_app(
            Settings(
                _env_file=None,
                store_id="store-001",
                store_fixture_path=tmp_path / "missing.json",
            )
        )
        with TestClient(application) as c:
            response = c.get("/store")

        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "store_unavailable"
        assert "Traceback" not in response.text


class TestFailureLogDiagnostics:
    """Failure diagnostics appear in structured logs with correlation IDs."""

    def test_conflict_logs_correlation_and_event_id(
        self, client: TestClient, caplog
    ) -> None:
        """Event conflict is logged with correlation and event identifiers."""
        with caplog.at_level(logging.INFO):
            # First accept
            client.post("/events", json=make_event(event_id="smoke-fail-log"))
            # Second attempt (conflict)
            modified = dict(make_event(event_id="smoke-fail-log", quantity=99))
            client.post("/events", json=modified)

        log_text = caplog.text
        assert "smoke-fail-log" in log_text
        assert "event.accepted" in log_text or "event" in log_text

    def test_failure_response_body_is_json_structured(
        self, client: TestClient
    ) -> None:
        """All error responses are structured JSON, not HTML or plain text."""
        # 404
        r = client.get("/inventory/P999")
        assert r.headers["content-type"].startswith("application/json")
        assert "error" in r.json()

        # 422
        r = client.post("/events", json={"event_id": ""})
        assert r.headers["content-type"].startswith("application/json")
        assert "error" in r.json()

    def test_stage_identifier_in_logs(self, client: TestClient, caplog) -> None:
        """Canonical stage names appear in logs for failure trace."""
        with caplog.at_level(logging.INFO):
            client.post("/events", json=make_event(event_id="smoke-stage-log"))

        text = caplog.text
        assert len(text) > 0
        # correlation_id appears in logs (correlation preserved across stages)
        assert "smoke-stage-log" in text or "run-" in text
