def test_inventory_returns_p001(client) -> None:
    response = client.get("/inventory/P001")

    assert response.status_code == 200
    assert response.json()["sku"] == "P001"
    assert response.json()["shelf_quantity"] == 8
    assert response.json()["backroom_quantity"] == 42


def test_unknown_sku_is_a_controlled_not_found(client) -> None:
    response = client.get("/inventory/P017")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "sku_not_found",
            "message": "SKU 'P017' is not in store store-001.",
        }
    }


def test_sku_match_is_case_sensitive(client) -> None:
    response = client.get("/inventory/p001")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "sku_not_found"
