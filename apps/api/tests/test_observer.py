"""A repeated sale.completed starts one investigation and requires no prompt."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import retailtwin_api.agents.observer.consumer as observer_consumer

from retailtwin_api.agents.observer.consumer import (
    InvestigationStart,
    MemoryActivationLedger,
    ObservationError,
    consume_available,
    observe_message,
    sale_message,
)
from retailtwin_api.backbone import (
    DEFAULT_FIXTURE,
    MemoryPipe,
    MemoryQuarantine,
    PulledMessage,
    load_fixture,
    parse_event,
)
from retailtwin_api.demand_surge import reset_weekend_demand_surge
from retailtwin_api.schemas import StoreEvent


class RecordingStarter:
    def __init__(self) -> None:
        self.starts: list[InvestigationStart] = []

    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        self.starts.append(start)

    def start_investigation(self, start: InvestigationStart) -> None:
        self.starts.append(start)


class FailingStarter:
    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        raise RuntimeError("path /secret/key")

    def start_investigation(self, start: InvestigationStart) -> None:
        raise RuntimeError("path /secret/key")


class AckWatchingStarter:
    def __init__(self, pipe: MemoryPipe, ledger: MemoryActivationLedger) -> None:
        self.pipe = pipe
        self.ledger = ledger
        self.starts: list[InvestigationStart] = []

    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        assert start.event.event_id not in self.pipe.acked
        stored = self.ledger.get(start.event.event_id)
        assert stored is not None
        assert stored.status == "pending"
        self.starts.append(start)

    def start_investigation(self, start: InvestigationStart) -> None:
        self.start_investigation_for_event(start)


class FlakyAckPipe(MemoryPipe):
    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 1

    def ack(self, ack_id: str) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("ack failed")
        super().ack(ack_id)


class FailingQuarantine:
    def record(self, message: PulledMessage, reason: str) -> None:
        raise RuntimeError("quarantine unavailable")


def _world():
    return MemoryPipe(), MemoryActivationLedger(), RecordingStarter(), MemoryQuarantine()


def test_the_same_sale_fixture_starts_one_investigation() -> None:
    pipe, ledger, starter, quarantine = _world()
    event = load_fixture(DEFAULT_FIXTURE)
    pipe.publish(event)
    pipe.publish(event)
    outcomes = consume_available(pipe, ledger, starter, quarantine)
    assert [item.outcome for item in outcomes] == ["started", "duplicate"]
    assert len(starter.starts) == 1
    start = starter.starts[0]
    assert start.investigation_id == "inv-evt-sale-0001"
    assert start.event.event_id == "evt-sale-0001"
    assert start.event.correlation_id == "run-20261007-001"
    assert not hasattr(start, "prompt")
    assert pipe.acked == ["1", "2"]
    assert pipe.pending == []
    stored = ledger.get("evt-sale-0001")
    assert stored is not None
    assert stored.status == "started"
    assert outcomes[0].correlation_id == event.correlation_id
    assert outcomes[1].investigation_id == start.investigation_id


def test_ack_follows_the_handoff(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    pipe, ledger, _, quarantine = _world()
    watcher = AckWatchingStarter(pipe, ledger)
    event = load_fixture(DEFAULT_FIXTURE)
    outcome = observe_message(pipe, ledger, watcher, quarantine, sale_message(event, "7"))
    assert outcome.outcome == "started"
    assert pipe.acked == ["7"]
    assert len(watcher.starts) == 1
    assert "run-20261007-001" in caplog.text
    assert "evt-sale-0001" in caplog.text


def test_failed_handoff_is_not_acked_and_can_be_retried() -> None:
    pipe, ledger, _, quarantine = _world()
    event = load_fixture(DEFAULT_FIXTURE)
    message = sale_message(event, "1")
    with pytest.raises(ObservationError, match="evt-sale-0001") as raised:
        observe_message(pipe, ledger, FailingStarter(), quarantine, message)
    assert "secret" not in str(raised.value)
    assert pipe.acked == []
    assert ledger.get(event.event_id) is None
    starter = RecordingStarter()
    outcome = observe_message(pipe, ledger, starter, quarantine, sale_message(event, "2"))
    assert outcome.outcome == "started"
    assert len(starter.starts) == 1
    assert pipe.acked == ["2"]


def test_ack_failure_after_commit_does_not_start_again() -> None:
    pipe = FlakyAckPipe()
    ledger = MemoryActivationLedger()
    starter = RecordingStarter()
    quarantine = MemoryQuarantine()
    event = load_fixture(DEFAULT_FIXTURE)
    with pytest.raises(RuntimeError, match="ack failed"):
        observe_message(pipe, ledger, starter, quarantine, sale_message(event, "1"))
    assert len(starter.starts) == 1
    assert ledger.get(event.event_id) is not None
    assert ledger.get(event.event_id).status == "started"  # type: ignore[union-attr]
    duplicate = observe_message(pipe, ledger, starter, quarantine, sale_message(event, "2"))
    assert duplicate.outcome == "duplicate"
    assert len(starter.starts) == 1
    assert pipe.acked == ["2"]


def test_a_different_payload_does_not_replace_the_investigation() -> None:
    pipe, ledger, starter, quarantine = _world()
    event = load_fixture(DEFAULT_FIXTURE)
    observe_message(pipe, ledger, starter, quarantine, sale_message(event, "1"))
    changed = event.model_copy(update={"quantity": event.quantity + 1})
    outcome = observe_message(pipe, ledger, starter, quarantine, sale_message(changed, "2"))
    assert outcome.outcome == "conflict"
    assert len(starter.starts) == 1
    stored = ledger.get(event.event_id)
    assert stored is not None
    assert stored.event.quantity == event.quantity
    assert pipe.acked == ["1", "2"]


def test_unsupported_and_invalid_messages_do_not_start_work() -> None:
    pipe, ledger, starter, quarantine = _world()
    event = load_fixture(DEFAULT_FIXTURE)
    inventory = event.model_copy(update={"event_type": "inventory.adjusted"})
    ignored = observe_message(pipe, ledger, starter, quarantine, sale_message(inventory, "1"))
    assert ignored.outcome == "ignored"
    assert starter.starts == []
    assert quarantine.records == []

    invalid = PulledMessage(ack_id="2", body="{", attributes={}, publish_time="")
    rejected = observe_message(pipe, ledger, starter, quarantine, invalid)
    assert rejected.outcome == "rejected"
    assert rejected.reason == "invalid_event"
    assert quarantine.records[0][1] == "invalid_event"

    mismatched = sale_message(event, "3")
    mismatched.attributes["store_id"] = "store-999"
    mismatch = observe_message(pipe, ledger, starter, quarantine, mismatched)
    assert mismatch.outcome == "rejected"
    assert mismatch.reason == "attribute_mismatch"

    bad_id = event.model_copy(update={"event_id": ".."})
    bad = observe_message(pipe, ledger, starter, quarantine, sale_message(bad_id, "4"))
    assert bad.outcome == "rejected"
    assert bad.reason == "invalid_event_id"
    assert starter.starts == []
    assert pipe.acked == ["1", "2", "3", "4"]


def test_quarantine_failure_is_not_acked() -> None:
    pipe, ledger, starter, _quarantine = _world()
    message = PulledMessage(ack_id="1", body="{", attributes={}, publish_time="")
    with pytest.raises(RuntimeError, match="quarantine unavailable"):
        observe_message(pipe, ledger, starter, FailingQuarantine(), message)
    assert pipe.acked == []


def test_weekend_series_replay_starts_each_event_once() -> None:
    pipe, ledger, starter, quarantine = _world()
    series = reset_weekend_demand_surge()
    for event in series:
        pipe.publish(event)
    for event in series:
        pipe.publish(event)
    outcomes = consume_available(pipe, ledger, starter, quarantine)
    started = [item for item in outcomes if item.outcome == "started"]
    duplicates = [item for item in outcomes if item.outcome == "duplicate"]
    assert len(series) == 13
    assert len(started) == 13
    assert len(duplicates) == 13
    assert len(starter.starts) == 13
    assert {item.event.correlation_id for item in starter.starts} == {"run-weekend-demand-surge-1"}
    assert {item.event.event_id for item in starter.starts} == {event.event_id for event in series}


def test_pending_reservation_resumes_the_same_investigation() -> None:
    pipe, ledger, starter, quarantine = _world()
    event = load_fixture(DEFAULT_FIXTURE)
    message = sale_message(event, "1")
    reserved = ledger.reserve(parse_event(message.body))
    assert reserved.kind == "owner"
    outcome = observe_message(pipe, ledger, starter, quarantine, message)
    assert outcome.outcome == "started"
    assert outcome.investigation_id == reserved.investigation_id
    assert len(starter.starts) == 1


def test_ledger_commit_and_abort_rules() -> None:
    ledger = MemoryActivationLedger()
    event = load_fixture(DEFAULT_FIXTURE)
    with pytest.raises(ObservationError):
        ledger.commit(event.event_id)
    ledger.abort(event.event_id)
    ledger.reserve(event)
    ledger.commit(event.event_id)
    ledger.abort(event.event_id)
    assert ledger.get(event.event_id) is not None
    assert ledger.get(event.event_id).status == "started"  # type: ignore[union-attr]
    with pytest.raises(ObservationError):
        ledger.commit(event.event_id)


def test_empty_pipe_starts_nothing() -> None:
    pipe, ledger, starter, quarantine = _world()
    assert consume_available(pipe, ledger, starter, quarantine) == []
    assert starter.starts == []


def test_observer_source_does_not_import_a_model_sdk() -> None:
    source = Path(observer_consumer.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "vertex" not in lowered
    assert "firestore" not in lowered
    assert "google.cloud" not in lowered


def test_two_event_ids_start_two_investigations() -> None:
    pipe, ledger, starter, quarantine = _world()
    first = load_fixture(DEFAULT_FIXTURE)
    second = first.model_copy(update={"event_id": "evt-sale-0002"})
    observe_message(pipe, ledger, starter, quarantine, sale_message(first, "1"))
    observe_message(pipe, ledger, starter, quarantine, sale_message(second, "2"))
    assert [item.investigation_id for item in starter.starts] == [
        "inv-evt-sale-0001",
        "inv-evt-sale-0002",
    ]
