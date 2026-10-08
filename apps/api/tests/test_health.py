def test_health_reports_the_loaded_fixture(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "retailtwin-api",
        "environment": "test",
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
    assert "get" in paths["/store"]
    assert "get" in paths["/inventory/{sku}"]
    assert "post" in paths["/events"]
