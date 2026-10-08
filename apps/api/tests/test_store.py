def test_store_returns_the_committed_fixture(client) -> None:
    response = client.get("/store")

    assert response.status_code == 200
    assert response.json() == {
        "store_id": "store-001",
        "context_version": "store-001:v1",
        "version": "v1",
        "products": [
            {
                "store_id": "store-001",
                "sku": "P001",
                "shelf_id": "A01",
                "slot_id": "A01-S01",
                "facings": 3,
                "shelf_quantity": 8,
                "backroom_quantity": 42,
                "version": 1,
            }
        ],
    }


def test_store_is_unavailable_without_a_fixture(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from retailtwin_api.main import create_app
    from retailtwin_api.settings import Settings

    monkeypatch.delenv("STORE_FIXTURE_PATH", raising=False)
    application = create_app(
        Settings(
            _env_file=None,
            store_id="store-001",
            store_fixture_path=tmp_path / "missing.json",
        )
    )

    with TestClient(application) as test_client:
        response = test_client.get("/store")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "store_unavailable",
            "message": "Store fixture is not available.",
        }
    }


def test_duplicate_sku_keeps_the_fixture_unloaded(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from retailtwin_api.main import create_app
    from retailtwin_api.settings import Settings

    fixture = tmp_path / "store.json"
    fixture.write_text(
        """
        {
          "store_id": "store-001",
          "version": "v1",
          "products": [
            {"sku": "P001", "shelf_id": "A01", "slot_id": "A01-S01", "facings": 1, "shelf_quantity": 1, "backroom_quantity": 1},
            {"sku": "P001", "shelf_id": "A02", "slot_id": "A02-S01", "facings": 1, "shelf_quantity": 1, "backroom_quantity": 1}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("STORE_FIXTURE_PATH", raising=False)
    application = create_app(
        Settings(_env_file=None, store_id="store-001", store_fixture_path=fixture)
    )

    with TestClient(application) as test_client:
        response = test_client.get("/health")

    assert response.json()["fixture_loaded"] is False
