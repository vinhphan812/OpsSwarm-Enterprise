"""Tests for :class:`FlagshipInvestigationStarter`.

The starter bridges the sync ``observe_message`` consumer to the async
``FlagshipController.start`` chain. We test it with a fake controller so
no real Live Twin or LLM is wired.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from retailtwin_api.agents.observer.consumer import (
    InvestigationStart,
    ObservationError,
)
from retailtwin_api.flagship.agent_starter import FlagshipInvestigationStarter
from retailtwin_api.flagship.controller import FlagshipRequest
from retailtwin_api.schemas import StoreEvent


class _FakeFlagshipController:
    """Stub that records ``reset``, ``start`` and ``start_for_event`` calls.

    Production autonomous events (ADR 0023) flow through
    ``start_for_event`` — the legacy ``reset`` + ``start`` path is only
    used by the demo /flagship/start flow and by the legacy
    ``start_investigation`` alias kept for unit tests.
    """

    def __init__(self, *, configured: bool = True) -> None:
        self.is_configured = configured
        self.resets: list[dict[str, int]] = []
        self.starts: list[FlagshipRequest] = []
        self.event_starts: list[Any] = []
        self.start_should_raise: BaseException | None = None
        self.event_should_raise: BaseException | None = None

    def reset(self, *, seed: int = 1) -> dict[str, Any]:
        self.resets.append({"seed": seed})
        return {
            "run_id": "rid",
            "phase": "IDLE",
            "seed": seed,
            "context_version": "store-001:v1",
        }

    async def start(self, request: FlagshipRequest | None = None) -> dict[str, Any]:
        self.starts.append(request or FlagshipRequest())
        if self.start_should_raise is not None:
            raise self.start_should_raise
        return {"phase": "COMPLETE"}

    async def start_for_event(
        self,
        event: Any,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self.event_starts.append((event, correlation_id))
        if self.event_should_raise is not None:
            raise self.event_should_raise
        return {"phase": "COMPLETE"}


def _event() -> StoreEvent:
    return StoreEvent(
        event_id="evt-1",
        correlation_id="corr-x",
        event_type="sale.completed",
        store_id="store-001",
        sku="P017",
        quantity=1,
        occurred_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )


def test_starter_resets_then_starts_with_correlation_id() -> None:
    controller = _FakeFlagshipController()
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))
    assert len(controller.resets) == 1
    assert len(controller.starts) == 1
    assert controller.starts[0].correlation_id == "corr-x"


def test_starter_raises_observation_error_when_controller_is_missing() -> None:
    starter = FlagshipInvestigationStarter(controller_getter=lambda: None)
    with pytest.raises(ObservationError, match="evt-1"):
        starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))


def test_starter_raises_observation_error_when_controller_is_unconfigured() -> None:
    controller = _FakeFlagshipController(configured=False)
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    with pytest.raises(ObservationError, match="evt-1"):
        starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))
    assert controller.resets == [] and controller.starts == []


def test_starter_propagates_controller_exceptions() -> None:
    controller = _FakeFlagshipController()
    controller.start_should_raise = RuntimeError("boom")
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    with pytest.raises(RuntimeError, match="boom"):
        starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))


def test_starter_does_not_swallow_controller_exception() -> None:
    """The starter must NOT wrap controller exceptions in ObservationError.

    The consumer wraps anything raised by ``start_investigation`` in
    ``ObservationError`` itself; double-wrapping would mask the real cause.
    """
    controller = _FakeFlagshipController()
    controller.start_should_raise = ValueError("bad input")
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    try:
        starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))
    except ObservationError as exc:
        pytest.fail(f"starter should not raise ObservationError; got {exc}")
    except ValueError:
        pass


def test_starter_re_reads_controller_on_each_invocation() -> None:
    """Late wiring of the controller must be picked up by the next handoff."""

    controller: _FakeFlagshipController | None = None

    def getter() -> _FakeFlagshipController | None:
        return controller

    starter = FlagshipInvestigationStarter(controller_getter=getter)
    with pytest.raises(ObservationError, match="evt-1"):
        starter.start_investigation(InvestigationStart(investigation_id="inv-1", event=_event()))

    controller = _FakeFlagshipController()
    starter.start_investigation(InvestigationStart(investigation_id="inv-2", event=_event()))
    assert len(controller.starts) == 1


# ---------------------------------------------------------------------------
# Production event path (ADR 0023)
# ---------------------------------------------------------------------------


def test_starter_for_event_does_not_reset_live_and_passes_event() -> None:
    """``start_investigation_for_event`` must NOT reset Live and must hand
    the real event to ``controller.start_for_event`` (P0-1, P0-2)."""

    controller = _FakeFlagshipController()
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    event = _event()
    starter.start_investigation_for_event(InvestigationStart(investigation_id="inv-p1", event=event))

    assert controller.resets == []
    assert controller.starts == []
    assert len(controller.event_starts) == 1
    passed_event, passed_correlation_id = controller.event_starts[0]
    assert passed_event is event
    # The correlation_id is propagated as a string when the event carries one.
    assert passed_correlation_id == event.correlation_id


def test_starter_for_event_propagates_controller_exceptions() -> None:
    """``start_investigation_for_event`` lets controller exceptions propagate
    so the consumer can convert them into ``ObservationError``."""

    controller = _FakeFlagshipController()
    controller.event_should_raise = RuntimeError("boom")
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    with pytest.raises(RuntimeError, match="boom"):
        starter.start_investigation_for_event(InvestigationStart(investigation_id="inv-p1", event=_event()))


def test_starter_for_event_raises_when_controller_unconfigured() -> None:
    """An unconfigured controller must raise ``ObservationError`` so the
    message is not acked."""

    controller = _FakeFlagshipController(configured=False)
    starter = FlagshipInvestigationStarter(controller_getter=lambda: controller)
    with pytest.raises(ObservationError, match="evt-1"):
        starter.start_investigation_for_event(InvestigationStart(investigation_id="inv-p1", event=_event()))
    assert controller.event_starts == []


def test_starter_for_event_raises_when_controller_missing() -> None:
    starter = FlagshipInvestigationStarter(controller_getter=lambda: None)
    with pytest.raises(ObservationError, match="evt-1"):
        starter.start_investigation_for_event(InvestigationStart(investigation_id="inv-p1", event=_event()))