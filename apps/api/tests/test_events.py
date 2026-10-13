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
    with caplog.at_level(logging.INFO, logger="retailtwin_api"):
        response = client.post("/events", json=VALID_EVENT)

    assert response.status_code == 201

    # Structured logging: correlation_id and event_id are in the extra dict and message string.
    event_log_records = [
        r for r in caplog.records if r.message.startswith("event.accepted")
    ]
    assert len(event_log_records) == 1, f"Expected exactly one 'event.accepted' record, got {len(event_log_records)}"
    record = event_log_records[0]
    # The event's correlation_id is stored in correlation_id_header extra field
    assert hasattr(record, "correlation_id_header"), "correlation_id_header missing from log record"
    assert record.correlation_id_header == "run-20261007-001"
    assert hasattr(record, "event_id"), "event_id missing from log record"
    assert record.event_id == "evt-000123"


# ---------------------------------------------------------------------------
# Direct EventLog unit tests — raise branch coverage to 85%+
# ---------------------------------------------------------------------------
from retailtwin_api.events import EventLog, EventConflict  # noqa: E402
from retailtwin_api.schemas import StoreEvent  # noqa: E402


def _make_event(event_id: str, **overrides) -> StoreEvent:
    base = {
        "event_id": event_id,
        "correlation_id": "run-test",
        "event_type": "sale.completed",
        "store_id": "store-001",
        "sku": "P001",
        "quantity": 3,
        "occurred_at": "2026-10-07T08:00:00Z",
        "source": "test",
    }
    base.update(overrides)
    return StoreEvent(**base)


class TestEventLogGet:
    def test_get_missing_returns_none(self) -> None:
        log = EventLog()
        result = log.get("nonexistent")
        assert result is None

    def test_get_existing_returns_copy(self) -> None:
        log = EventLog()
        stored, _ = log.accept(_make_event("evt-001"))
        retrieved = log.get("evt-001")
        assert retrieved is not None
        assert retrieved.event_id == "evt-001"
        # Mutation of retrieved must not affect stored
        retrieved.quantity = 999
        _, is_dup = log.accept(_make_event("evt-001"))
        assert is_dup is True  # original stored unchanged


class TestEventLogAccept:
    def test_accept_new_event(self) -> None:
        log = EventLog()
        stored, is_dup = log.accept(_make_event("evt-new"))
        assert is_dup is False
        assert stored.event_id == "evt-new"
        assert stored.quantity == 3

    def test_accept_exact_duplicate_returns_stored_copy(self) -> None:
        log = EventLog()
        first, _ = log.accept(_make_event("evt-dup"))
        second, is_dup = log.accept(_make_event("evt-dup"))
        assert is_dup is True
        assert second.event_id == "evt-dup"
        # Returns existing stored event
        assert second.quantity == 3

    def test_accept_conflict_on_different_payload(self) -> None:
        log = EventLog()
        log.accept(_make_event("evt-c1", quantity=5))
        with pytest.raises(EventConflict) as exc_info:
            log.accept(_make_event("evt-c1", quantity=99))
        assert exc_info.value.event_id == "evt-c1"

    def test_accept_multiple_distinct_events(self) -> None:
        log = EventLog()
        e1, d1 = log.accept(_make_event("evt-a"))
        e2, d2 = log.accept(_make_event("evt-b"))
        e3, d3 = log.accept(_make_event("evt-c"))
        assert (d1, d2, d3) == (False, False, False)
        assert (e1.event_id, e2.event_id, e3.event_id) == ("evt-a", "evt-b", "evt-c")
        assert log.get("evt-a") is not None
        assert log.get("evt-b") is not None
        assert log.get("evt-c") is not None
