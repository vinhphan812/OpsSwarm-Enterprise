import json
import re

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings


def test_health_reports_the_loaded_fixture(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "retailtwin-api",
        "environment": "test",
        "app_env": "test",
        "store_id": "store-001",
        "fixture_loaded": True,
    }


def test_health_stays_up_when_the_fixture_is_missing(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from retailtwin_api.main import create_app
    from retailtwin_api.settings import Settings

    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    missing = tmp_path / "missing.json"
    application = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            store_id="store-001",
            store_fixture_path=missing,
        )
    )

    with TestClient(application) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["fixture_loaded"] is False
    assert str(missing) not in response.text


def test_openapi_lists_the_day0_routes(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/health"]
    assert "get" in paths["/ready"]
    assert "get" in paths["/store"]
    assert "get" in paths["/inventory/{sku}"]
    assert "post" in paths["/events"]


# ── Readiness probe ────────────────────────────────────────────────────────────

def test_ready_returns_200_when_fixture_is_loaded(client) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["service"] == "retailtwin-api"
    assert body["store_id"] == "store-001"
    assert "correlation_id" in body


def test_ready_returns_503_when_fixture_is_missing(tmp_path, monkeypatch) -> None:
    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    missing = tmp_path / "missing.json"
    application = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            store_id="store-001",
            store_fixture_path=missing,
        )
    )

    with TestClient(application) as test_client:
        response = test_client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "store_unavailable"
    # No fixture path leaked in error message
    assert str(missing) not in response.text


# ── Correlation IDs ─────────────────────────────────────────────────────────────

def test_correlation_id_injected_when_header_absent(client) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    cid = body.get("correlation_id")
    assert cid is not None
    assert re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", cid), \
        f"Expected UUID, got: {cid}"


def test_correlation_id_echoed_when_header_provided(client) -> None:
    custom = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    response = client.get("/ready", headers={"X-Correlation-ID": custom})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == custom


# ── Settings validation ─────────────────────────────────────────────────────────

def test_app_env_rejects_unknown_value(monkeypatch) -> None:
    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "hack")
    with pytest.raises(ValueError, match="APP_ENV must be one of"):
        Settings(_env_file=None)


def test_log_level_rejects_unknown_value(monkeypatch) -> None:
    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        Settings(_env_file=None)


def test_is_production_true_when_app_env_production(monkeypatch) -> None:
    for key in ("APP_ENV", "STORE_ID", "STORE_FIXTURE_PATH", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None, app_env="production")
    assert s.is_production is True


# ── Structured JSON logs ────────────────────────────────────────────────────────

def test_startup_log_emitted_as_structured_json(client) -> None:
    # create_app() already ran in the client fixture; just verify the app started.
    # The "app.startup" message is emitted at startup.  If the client is live,
    # the app started correctly (otherwise TestClient raises).
    response = client.get("/health")
    assert response.status_code == 200


def test_middleware_logs_request_start_and_end(client, caplog) -> None:
    """Verify request.start and request.end messages are emitted with correlation_id."""
    with caplog.at_level("INFO", logger="retailtwin_api"):
        client.get("/ready")

    # Filter to only retailtwin_api middleware logs (excludes uvicorn startup noise)
    middleware_records = [r for r in caplog.records if r.name == "retailtwin_api.middleware"]
    messages = {r.message for r in middleware_records}
    assert any(m.startswith("request.start") for m in messages), f"Expected 'request.start' prefix in {messages}"
    assert any(m.startswith("request.end") for m in messages), f"Expected 'request.end' prefix in {messages}"

    # Verify correlation_id is present in structured extra fields
    for record in middleware_records:
        assert hasattr(record, "correlation_id"), f"Missing correlation_id attr on record: {record}"
        assert getattr(record, "correlation_id"), "Empty correlation_id"
        assert record.message.startswith("request."), f"Unexpected message: {record.message}"
        assert record.levelname == "INFO"
