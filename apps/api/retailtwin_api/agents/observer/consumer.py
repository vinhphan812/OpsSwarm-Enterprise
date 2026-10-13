"""Start one investigation for a new sale.completed event.

The analytics lander is a different consumer. This one pulls from an event
pipe, records the event id, hands that event to an injected orchestrator, and
acknowledges the message only after that record is committed. A second
delivery of the same payload does not start a second investigation.

No model SDK is imported. The orchestrator receives the store event and an
investigation id. It does not receive a user prompt.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Literal, Protocol

from retailtwin_api.backbone import (
    SALE_COMPLETED,
    BackboneError,
    EventPipe,
    PulledMessage,
    Quarantine,
    attribute_problem,
    canonical_body,
    claim_id_ok,
    message_attributes,
    parse_event,
)
from retailtwin_api.schemas import StoreEvent

log = logging.getLogger(__name__)

OutcomeName = Literal["started", "duplicate", "conflict", "ignored", "rejected"]


class ObservationError(Exception):
    """The investigation handoff failed. The message was not acknowledged."""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"Investigation handoff failed for {event_id}.")


@dataclass(frozen=True)
class InvestigationStart:
    """One autonomous handoff. There is no prompt on this value."""

    investigation_id: str
    event: StoreEvent


class InvestigationStarter(Protocol):
    """Orchestration boundary. Implementations must not call a model SDK."""

    def start_investigation(self, start: InvestigationStart) -> None: ...


@dataclass(frozen=True)
class Observation:
    outcome: OutcomeName
    event_id: str | None
    correlation_id: str | None
    investigation_id: str | None
    reason: str | None = None


@dataclass(frozen=True)
class Activation:
    investigation_id: str
    event: StoreEvent
    status: Literal["pending", "started"]


@dataclass(frozen=True)
class _Reservation:
    kind: Literal["owner", "duplicate", "conflict"]
    investigation_id: str
    event: StoreEvent


class MemoryActivationLedger:
    """Process-local activation record.

    The record is committed before the message is acknowledged. It is not the
    Live Twin and it is not the analytics claim in ``store_event_claims``.
    """

    def __init__(self) -> None:
        self._records: dict[str, Activation] = {}
        self._lock = threading.Lock()

    def reserve(self, event: StoreEvent) -> _Reservation:
        with self._lock:
            return self._reserve(event)

    def _reserve(self, event: StoreEvent) -> _Reservation:
        current = self._records.get(event.event_id)
        if current is None:
            investigation_id = f"inv-{event.event_id}"
            stored = Activation(investigation_id, event.model_copy(deep=True), "pending")
            self._records[event.event_id] = stored
            return _Reservation("owner", investigation_id, stored.event.model_copy(deep=True))
        if current.event != event:
            return _Reservation(
                "conflict",
                current.investigation_id,
                current.event.model_copy(deep=True),
            )
        if current.status == "started":
            return _Reservation(
                "duplicate",
                current.investigation_id,
                current.event.model_copy(deep=True),
            )
        return _Reservation(
            "owner",
            current.investigation_id,
            current.event.model_copy(deep=True),
        )

    def commit(self, event_id: str) -> None:
        with self._lock:
            current = self._records.get(event_id)
            if current is None or current.status != "pending":
                raise ObservationError(event_id)
            self._records[event_id] = Activation(
                current.investigation_id,
                current.event.model_copy(deep=True),
                "started",
            )

    def abort(self, event_id: str) -> None:
        with self._lock:
            current = self._records.get(event_id)
            if current is None or current.status != "pending":
                return
            del self._records[event_id]

    def get(self, event_id: str) -> Activation | None:
        with self._lock:
            current = self._records.get(event_id)
            if current is None:
                return None
            return Activation(
                current.investigation_id,
                current.event.model_copy(deep=True),
                current.status,
            )


def observe_message(
    pipe: EventPipe,
    ledger: MemoryActivationLedger,
    starter: InvestigationStarter,
    quarantine: Quarantine,
    message: PulledMessage,
) -> Observation:
    """Handle one pulled message. Acknowledge only a terminal outcome."""

    try:
        event = parse_event(message.body)
    except BackboneError:
        _reject(pipe, quarantine, message, "invalid_event")
        return _finish("rejected", None, None, None, "invalid_event")

    problem = attribute_problem(event, message.attributes)
    if problem is not None:
        _reject(pipe, quarantine, message, problem)
        return _finish("rejected", event.event_id, event.correlation_id, None, problem)
    if not claim_id_ok(event.event_id):
        _reject(pipe, quarantine, message, "invalid_event_id")
        return _finish("rejected", event.event_id, event.correlation_id, None, "invalid_event_id")
    if event.event_type != SALE_COMPLETED:
        pipe.ack(message.ack_id)
        return _finish("ignored", event.event_id, event.correlation_id, None, None)

    reservation = ledger.reserve(event)
    if reservation.kind == "owner":
        try:
            starter.start_investigation(
                InvestigationStart(reservation.investigation_id, reservation.event)
            )
        except Exception:
            ledger.abort(event.event_id)
            log.exception(
                "observer handoff failed event_id=%s correlation_id=%s",
                event.event_id,
                event.correlation_id,
            )
            raise ObservationError(event.event_id) from None
        ledger.commit(event.event_id)
        pipe.ack(message.ack_id)
        return _finish(
            "started",
            event.event_id,
            event.correlation_id,
            reservation.investigation_id,
            None,
        )

    pipe.ack(message.ack_id)
    return _finish(
        reservation.kind,
        event.event_id,
        event.correlation_id,
        reservation.investigation_id,
        None,
    )


def consume_available(
    pipe: EventPipe,
    ledger: MemoryActivationLedger,
    starter: InvestigationStarter,
    quarantine: Quarantine,
) -> list[Observation]:
    """Pull and observe until the pipe is empty. Stop before a failed handoff is acked."""

    outcomes: list[Observation] = []
    while True:
        batch = pipe.pull(limit=1)
        if not batch:
            return outcomes
        outcomes.append(observe_message(pipe, ledger, starter, quarantine, batch[0]))


def sale_message(event: StoreEvent, ack_id: str) -> PulledMessage:
    """Build the canonical Pub/Sub body and attributes for one store event."""

    return PulledMessage(
        ack_id=ack_id,
        body=canonical_body(event),
        attributes=message_attributes(event),
        publish_time="",
    )


def _reject(
    pipe: EventPipe,
    quarantine: Quarantine,
    message: PulledMessage,
    reason: str,
) -> None:
    quarantine.record(message, reason)
    pipe.ack(message.ack_id)


def _finish(
    outcome: OutcomeName,
    event_id: str | None,
    correlation_id: str | None,
    investigation_id: str | None,
    reason: str | None,
) -> Observation:
    log.info(
        "observer event_id=%s correlation_id=%s outcome=%s investigation_id=%s reason=%s",
        event_id,
        correlation_id,
        outcome,
        investigation_id,
        reason,
    )
    return Observation(outcome, event_id, correlation_id, investigation_id, reason)
