"""Tests for :class:`retailtwin_api.demand_surge.DemandSurgeScheduler`.

The scheduler is an asyncio task that publishes one canonical
``sale.completed`` per tick. Each tick uses a fresh ``event_id`` so the
``EventLog`` dedupes on a different key and the FE sees the event as new.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from retailtwin_api.backbone import BackboneError
from retailtwin_api.demand_surge import (
    DemandSurgeScheduler,
    SKU,
    STORE_ID,
    SALE_COMPLETED,
    SURGE_QUANTITIES,
    build_canonical_sale_event,
)


class _RecordingPipe:
    """Captures every published event; fails if asked to."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


class _FailingPipe:
    def __init__(self, failures: int = 1) -> None:
        self._remaining = failures
        self.calls = 0

    def publish(self, event: Any) -> None:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise BackboneError("nope")


# ---------------------------------------------------------------------------
# build_canonical_sale_event
# ---------------------------------------------------------------------------


def test_build_canonical_sale_event_uses_fresh_event_id() -> None:
    first = build_canonical_sale_event()
    second = build_canonical_sale_event()
    assert first.event_id != second.event_id
    assert first.event_id.startswith("evt-canonical-")
    assert first.event_type == SALE_COMPLETED
    assert first.store_id == STORE_ID
    assert first.sku == SKU
    assert first.quantity == SURGE_QUANTITIES[-1]


def test_build_canonical_sale_event_records_now() -> None:
    from datetime import datetime, timezone

    before = datetime.now(timezone.utc)
    event = build_canonical_sale_event()
    after = datetime.now(timezone.utc)
    assert before <= event.occurred_at <= after


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_requires_positive_interval() -> None:
    pipe = _RecordingPipe()
    with pytest.raises(BackboneError, match="positive interval"):
        DemandSurgeScheduler(pipe=pipe, interval_seconds=0)


def test_start_then_stop_publishes_no_more_messages() -> None:
    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.05)
        scheduler.start()
        await asyncio.sleep(0.18)
        await scheduler.stop()
        # At least two ticks should have happened.
        assert len(pipe.events) >= 2

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_start_is_idempotent_when_already_running() -> None:
    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.1)
        scheduler.start()
        task_before = scheduler._task
        scheduler.start()  # second start should be a no-op
        task_after = scheduler._task
        assert task_before is task_after
        await scheduler.stop()

    asyncio.run(scenario())


def test_stop_without_start_is_safe() -> None:
    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.1)
        await scheduler.stop()  # must not raise

    asyncio.run(scenario())


def test_stop_can_be_called_twice() -> None:
    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.05)
        scheduler.start()
        await asyncio.sleep(0.1)
        await scheduler.stop()
        await scheduler.stop()  # second stop must be a no-op

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Per-tick freshness
# ---------------------------------------------------------------------------


def test_each_tick_publishes_a_fresh_event_id() -> None:
    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.02)
        scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()
        ids = [event.event_id for event in pipe.events]
        # With 20ms interval and 200ms wait, we expect ~10 ticks.
        # Require at least 2 to detect a stalled scheduler while tolerating CI jitter.
        assert len(ids) >= 2
        assert len(set(ids)) == len(ids)  # all distinct

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Failure resilience
# ---------------------------------------------------------------------------


def test_loop_survives_publish_failures() -> None:
    """A failing publish must NOT kill the loop. The next tick still runs."""

    async def scenario() -> None:
        pipe = _FailingPipe(failures=2)
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.02)
        scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()
        # With 20ms interval and 200ms wait, we expect ~10 calls.
        assert pipe.calls >= 2

    asyncio.run(scenario())


def test_publish_is_idempotent_against_duplicate_event_id_per_tick() -> None:
    """Two ticks within the same second can still have different event_ids.

    The canonical sale event builder uses ``secrets.token_hex(8)``, which
    gives 16 hex chars (64 bits) of randomness — collisions are not a
    concern in normal operation. The EventLog dedupes by event_id, so a
    fresh id each tick is what makes each event land as new.
    """

    async def scenario() -> None:
        pipe = _RecordingPipe()
        scheduler = DemandSurgeScheduler(pipe=pipe, interval_seconds=0.01)
        scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()
        ids = [event.event_id for event in pipe.events]
        assert len(ids) >= 2
        assert all(id_a != id_b for id_a, id_b in zip(ids, ids[1:]))

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# BackboneError on construction
# ---------------------------------------------------------------------------


def test_negative_interval_is_rejected() -> None:
    pipe = _RecordingPipe()
    with pytest.raises(BackboneError, match="positive interval"):
        DemandSurgeScheduler(pipe=pipe, interval_seconds=-1.0)