"""End-to-end integration test for the autonomous event trigger.

The pipeline under test:

    publisher -> MemoryPipe -> observe_message (consumer)
                            -> FlagshipInvestigationStarter (adapter)
                            -> FlagshipController (fake)

We use the in-memory building blocks (MemoryPipe, MemoryActivationLedger,
MemoryQuarantine, FakeFlagshipController) so the test stays hermetic —
no real GCP project, no real LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from retailtwin_api.agents.observer.consumer import (
    InvestigationStart,
    MemoryActivationLedger,
    consume_available,
    observe_message,
)
from retailtwin_api.backbone import MemoryPipe, MemoryQuarantine, PulledMessage
from retailtwin_api.demand_surge import build_canonical_sale_event
from retailtwin_api.flagship.agent_starter import FlagshipInvestigationStarter
from retailtwin_api.flagship.controller import FlagshipRequest


class _FakeFlagshipController:
    """Stub FlagshipController that records ``start_for_event`` invocations.

    The autonomous event path (ADR 0023) does NOT reset the Live Twin — the
    controller is handed the real incoming ``StoreEvent`` directly. The
    demo /flagship/start path is exercised separately by the
    ``test_flagship_investigation_starter`` suite and remains reset-based
    for backwards compatibility.
    """

    def __init__(self) -> None:
        self.is_configured = True
        self.resets: list[int] = []
        self.starts: list[FlagshipRequest] = []
        self.event_starts: list[Any] = []

    def reset(self, *, seed: int = 1) -> dict[str, Any]:
        self.resets.append(seed)
        return {
            "run_id": "rid",
            "phase": "IDLE",
            "seed": seed,
            "context_version": "store-001:v1",
        }

    async def start(self, request: FlagshipRequest | None = None) -> dict[str, Any]:
        self.starts.append(request or FlagshipRequest())
        return {"phase": "COMPLETE"}

    async def start_for_event(
        self,
        event: Any,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self.event_starts.append(event)
        return {"phase": "COMPLETE"}


def _world():
    pipe = MemoryPipe()
    ledger = MemoryActivationLedger()
    quarantine = MemoryQuarantine()
    controller = _FakeFlagshipController()
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    return pipe, ledger, starter, quarantine, controller


# ---------------------------------------------------------------------------
# observe_message end-to-end
# ---------------------------------------------------------------------------


def test_publish_then_observe_runs_starter_once() -> None:
    pipe, ledger, starter, quarantine, controller = _world()
    event = _sale_event("evt-int-1")
    pipe.publish(event)
    outcomes = consume_available(pipe, ledger, starter, quarantine)
    assert [item.outcome for item in outcomes] == ["started"]
    # Autonomous event path: the Live Twin MUST NOT be reset.
    assert controller.resets == []
    assert len(controller.event_starts) == 1
    assert controller.event_starts[0].event_id == event.event_id
    assert controller.event_starts[0].correlation_id == event.correlation_id
    assert pipe.acked == ["1"]


def test_duplicate_event_does_not_start_a_second_investigation() -> None:
    pipe, ledger, starter, quarantine, controller = _world()
    event = _sale_event("evt-int-2")
    pipe.publish(event)
    pipe.publish(event)  # duplicate event_id
    outcomes = consume_available(pipe, ledger, starter, quarantine)
    assert [item.outcome for item in outcomes] == ["started", "duplicate"]
    assert len(controller.event_starts) == 1


def test_unconfigured_controller_raises_observation_error() -> None:
    """An unconfigured controller must surface ObservationError so the
    message is not acked and Pub/Sub re-delivers."""

    pipe = MemoryPipe()
    ledger = MemoryActivationLedger()
    quarantine = MemoryQuarantine()
    controller = _FakeFlagshipController()
    controller.is_configured = False
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    pipe.publish(_sale_event("evt-int-3"))
    with pytest.raises(Exception):
        # observe_message raises ObservationError, which consume_available
        # does not catch — verify the per-message path explicitly.
        for message in pipe.pull(limit=1):
            observe_message(pipe, ledger, starter, quarantine, message)
    assert controller.resets == []
    assert pipe.acked == []


def test_quarantine_records_invalid_event_with_no_starter_call() -> None:
    pipe, ledger, starter, quarantine, controller = _world()
    message = PulledMessage(
        ack_id="1",
        body="not-a-json-event",
        attributes={},
        publish_time="",
    )
    outcome = observe_message(pipe, ledger, starter, quarantine, message)
    assert outcome.outcome == "rejected"
    assert outcome.event_id is None
    assert quarantine.records == [(message, "invalid_event")]
    assert pipe.acked == ["1"]
    assert controller.event_starts == []


def test_scheduled_publisher_then_consumer_completes_chain() -> None:
    """The pipeline mirrors what main.py wires in production: a scheduler
    publishes one canonical event per tick, the consumer pulls, the starter
    hands the event to the controller via ``start_for_event``.
    """

    pipe, ledger, starter, quarantine, controller = _world()
    event = build_canonical_sale_event()
    pipe.publish(event)
    outcomes = consume_available(pipe, ledger, starter, quarantine)
    assert outcomes[0].outcome == "started"
    assert len(controller.event_starts) == 1
    assert controller.event_starts[0].event_id == event.event_id
    assert outcomes[0].investigation_id == f"inv-{event.event_id}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sale_event(event_id: str) -> Any:
    """A small StoreEvent for the test world.

    Avoids importing the pydantic model so the test reads cleanly.
    """

    from retailtwin_api.schemas import StoreEvent

    return StoreEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        event_type="sale.completed",
        store_id="store-001",
        sku="P017",
        quantity=1,
        occurred_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )