import logging

import pytest

VALID_EVENT = {
    "event_id": "evt-000123",
    "correlation_id": "run-20261007-001",
    "event_type": "sale.completed",
    "store_id": "store-001",
    "sku": "P001",
    "quantity": 3,
    "occurred_at": "2026-10-07T08:01:00Z",
    "source": "synthetic-pos",
}


def test_event_is_accepted_and_does_not_change_inventory(client) -> None:
    before = client.get("/inventory/P001").json()

    response = client.post("/events", json=VALID_EVENT)

    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] is True
    assert body["duplicate"] is False
    assert body["event"]["event_id"] == "evt-000123"
    assert body["event"]["correlation_id"] == "run-20261007-001"
    assert body["event"]["quantity"] == 3
    assert body["event"]["occurred_at"].startswith("2026-10-07T08:01:00")
    assert client.get("/inventory/P001").json() == before


def test_exact_duplicate_is_idempotent(client) -> None:
    first = client.post("/events", json=VALID_EVENT)
    second = client.post("/events", json=dict(VALID_EVENT))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["event"]["quantity"] == 3
    assert second.json()["event"]["correlation_id"] == "run-20261007-001"
    assert client.get("/inventory/P001").json()["shelf_quantity"] == 8


def test_same_instant_with_an_explicit_offset_is_a_duplicate(client) -> None:
    client.post("/events", json=VALID_EVENT)
    replay = dict(VALID_EVENT)
    replay["occurred_at"] = "2026-10-07T08:01:00+00:00"

    response = client.post("/events", json=replay)

    assert response.status_code == 200
    assert response.json()["duplicate"] is True


@pytest.mark.parametrize(
    "patch",
    [
        {"quantity": 9},
        {"sku": "P017"},
        {"correlation_id": "run-other"},
        {"occurred_at": "2026-10-07T09:00:00Z"},
        {"source": "other-pos"},
    ],
)
def test_same_event_id_with_a_different_payload_conflicts(client, patch: dict[str, object]) -> None:
    assert client.post("/events", json=VALID_EVENT).status_code == 201
    payload = dict(VALID_EVENT)
    payload.update(patch)

    response = client.post("/events", json=payload)

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "event_id_conflict",
            "message": "Event 'evt-000123' already exists with a different payload.",
        }
    }
    assert client.get("/inventory/P001").json()["shelf_quantity"] == 8
    replay = client.post("/events", json=VALID_EVENT)
    assert replay.status_code == 200
    assert replay.json()["event"]["quantity"] == 3


def test_unknown_sku_event_is_rejected(client) -> None:
    payload = dict(VALID_EVENT)
    payload["sku"] = "P017"

    response = client.post("/events", json=payload)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "sku_not_found"


def test_unknown_store_event_is_rejected(client) -> None:
    payload = dict(VALID_EVENT)
    payload["store_id"] = "store-999"

    response = client.post("/events", json=payload)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "store_not_found"


def test_invalid_event_does_not_echo_the_payload(client) -> None:
    payload = dict(VALID_EVENT)
    del payload["sku"]
    payload["note"] = "SECRET-SENTINEL"
    payload["quantity"] = 0

    response = client.post("/events", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    fields = {item["field"] for item in body["error"]["details"]}
    assert "sku" in fields
    assert "SECRET-SENTINEL" not in response.text


def test_malformed_json_is_a_validation_error(client) -> None:
    response = client.post(
        "/events",
        content=b"{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_blank_event_id_is_rejected(client) -> None:
    payload = dict(VALID_EVENT)
    payload["event_id"] = "   "

    response = client.post("/events", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_naive_timestamp_is_rejected(client) -> None:
    payload = dict(VALID_EVENT)
    payload["occurred_at"] = "2026-10-07T08:01:00"

    response = client.post("/events", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_accepted_event_logs_the_correlation_id(client, caplog) -> None:
    with caplog.at_level(logging.INFO):
        response = client.post("/events", json=VALID_EVENT)

    assert response.status_code == 201
    assert "run-20261007-001" in caplog.text
    assert "evt-000123" in caplog.text
