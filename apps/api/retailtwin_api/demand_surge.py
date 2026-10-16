"""Weekend Demand Surge fixture for SKU P017.

Seed 1 rebuilds one series of sale.completed events. The series publishes on
the existing store-events path. Detecting the velocity spike does not start
the Observer and does not change the Live Twin.

The :class:`DemandSurgeScheduler` publishes a canonical ``sale.completed``
event on a fixed cadence so the FE sees new data continuously (ADR 0023).
Each tick uses a fresh ``event_id``; the ``EventLog`` dedupes by
``event_id``, so every tick lands as a new event in the read model.
"""

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from retailtwin_api.backbone import (
    SALE_COMPLETED,
    BackboneError,
    ClaimLedger,
    EventPipe,
    EventSink,
    Landing,
    Quarantine,
    config_from_env,
    deliver,
    format_occurred_at,
    require_sale,
)
from retailtwin_api.backbone_gcp import GcloudPipe, SubprocessRunner
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import REPO_ROOT

CANONICAL_SEED = 1
STORE_ID = "store-001"
SKU = "P017"
SOURCE = "synthetic-pos"
WINDOW_HOURS = 4
INCREASE_MIN = Decimal("0.46")
BASELINE_START = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
SURGE_START = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
BASELINE_QUANTITIES = (10, 10, 10, 10, 10)
SURGE_QUANTITIES = (9, 9, 9, 9, 9, 9, 9, 10)
FIXTURE_PATH = REPO_ROOT / "data" / "synthetic" / "weekend-demand-surge.json"


class DemandSurgeObserver(Protocol):
    """Handoff for a later Observer. Issue #12 owns that agent."""

    def receive_demand_surge(self, notice: "DemandSurgeNotice") -> None: ...


@dataclass(frozen=True)
class DemandSurgeNotice:
    """One detected velocity spike. Rates are decimal strings, not floats."""

    seed: int
    store_id: str
    sku: str
    correlation_id: str
    baseline_units_per_hour: str
    surge_units_per_hour: str
    increase: str
    event_ids: tuple[str, ...]


def reset_weekend_demand_surge(seed: int = CANONICAL_SEED) -> tuple[StoreEvent, ...]:
    """Rebuild the same event ids and timestamps for this seed."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed != CANONICAL_SEED:
        raise BackboneError("Weekend demand surge only resets from seed 1.")
    correlation_id = f"run-weekend-demand-surge-{seed}"
    baseline = _series("base", BASELINE_START, BASELINE_QUANTITIES, correlation_id)
    surge = _series("surge", SURGE_START, SURGE_QUANTITIES, correlation_id)
    return tuple(baseline + surge)


def detect_demand_surge(events: Sequence[StoreEvent]) -> DemandSurgeNotice | None:
    """Return the spike when weekend units per hour clear the baseline by 46%."""

    sales = _scenario_sales(events)
    baseline_units = _units(sales, BASELINE_START)
    surge_units = _units(sales, SURGE_START)
    if baseline_units <= 0 or surge_units <= 0:
        return None
    increase = (Decimal(surge_units) - Decimal(baseline_units)) / Decimal(baseline_units)
    if increase < INCREASE_MIN:
        return None
    return DemandSurgeNotice(
        seed=CANONICAL_SEED,
        store_id=STORE_ID,
        sku=SKU,
        correlation_id=sales[0].correlation_id,
        baseline_units_per_hour=str(Decimal(baseline_units) / Decimal(WINDOW_HOURS)),
        surge_units_per_hour=str(Decimal(surge_units) / Decimal(WINDOW_HOURS)),
        increase=str(increase),
        event_ids=tuple(event.event_id for event in sales),
    )


def publish_demand_surge(
    pipe: EventPipe,
    events: Sequence[StoreEvent] | None = None,
) -> tuple[StoreEvent, ...]:
    """Publish each sale on the caller's store-events pipe."""

    series = tuple(events) if events is not None else reset_weekend_demand_surge()
    for event in series:
        require_sale(event)
        pipe.publish(event)
    return series


def deliver_published(
    pipe: EventPipe,
    sink: EventSink,
    ledger: ClaimLedger,
    quarantine: Quarantine,
) -> list[Landing]:
    """Land every message already queued on the pipe."""

    outcomes: list[Landing] = []
    while True:
        batch = pipe.pull()
        if not batch:
            return outcomes
        for message in batch:
            outcomes.append(deliver(pipe, sink, ledger, quarantine, message))


def replay_demand_surge(
    pipe: EventPipe,
    sink: EventSink,
    ledger: ClaimLedger,
    quarantine: Quarantine,
    observer: DemandSurgeObserver,
) -> DemandSurgeNotice:
    """Reset the fixture, publish it, and hand the same spike to the observer."""

    events = reset_weekend_demand_surge()
    publish_demand_surge(pipe, events)
    outcomes = deliver_published(pipe, sink, ledger, quarantine)
    if any(item.outcome in ("rejected", "conflict") for item in outcomes):
        raise BackboneError("Demand surge event was not accepted.")
    notice = detect_demand_surge(events)
    if notice is None:
        raise BackboneError("Weekend demand surge was not detected.")
    observer.receive_demand_surge(notice)
    return notice


def scenario_document(events: Sequence[StoreEvent] | None = None) -> dict[str, object]:
    series = tuple(events) if events is not None else reset_weekend_demand_surge()
    return {
        "seed": CANONICAL_SEED,
        "store_id": STORE_ID,
        "sku": SKU,
        "baseline_start": format_occurred_at(BASELINE_START),
        "baseline_hours": WINDOW_HOURS,
        "surge_start": format_occurred_at(SURGE_START),
        "surge_hours": WINDOW_HOURS,
        "increase_min": str(INCREASE_MIN),
        "events": [_event_payload(event) for event in series],
    }


def load_committed_surge(path: Path = FIXTURE_PATH) -> tuple[StoreEvent, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackboneError(f"Cannot read fixture {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise BackboneError(f"Fixture {path} has no events.")
    try:
        return tuple(StoreEvent.model_validate(item) for item in payload["events"])
    except ValueError as exc:
        raise BackboneError(f"Cannot read fixture {path}") from exc


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the Weekend Demand Surge sales on store-events."
    )
    parser.add_argument("command", choices=("publish",))
    parser.parse_args(argv)
    try:
        load_env_file(REPO_ROOT / ".env")
        events = publish_demand_surge(GcloudPipe(config_from_env(), SubprocessRunner()))
    except BackboneError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "published": [event.event_id for event in events],
                "correlation_id": events[0].correlation_id,
                "sku": SKU,
            }
        )
    )
    return 0


def _series(
    label: str,
    start: datetime,
    quantities: tuple[int, ...],
    correlation_id: str,
) -> list[StoreEvent]:
    step = timedelta(hours=WINDOW_HOURS) / len(quantities)
    events: list[StoreEvent] = []
    for index, quantity in enumerate(quantities, start=1):
        events.append(
            StoreEvent(
                event_id=f"evt-p017-{label}-{index:04d}",
                correlation_id=correlation_id,
                event_type=SALE_COMPLETED,
                store_id=STORE_ID,
                sku=SKU,
                quantity=quantity,
                occurred_at=start + step * (index - 1),
                source=SOURCE,
            )
        )
    return events


def _scenario_sales(events: Sequence[StoreEvent]) -> tuple[StoreEvent, ...]:
    seen: dict[str, StoreEvent] = {}
    for event in events:
        require_sale(event)
        if event.store_id != STORE_ID or event.sku != SKU:
            continue
        previous = seen.get(event.event_id)
        if previous is None:
            seen[event.event_id] = event
            continue
        if previous != event:
            raise BackboneError(f"event_id {event.event_id} has two payloads.")
    sales = tuple(sorted(seen.values(), key=lambda item: (item.occurred_at, item.event_id)))
    correlation_ids = {event.correlation_id for event in sales}
    if len(correlation_ids) > 1:
        raise BackboneError("Demand surge sales must share one correlation_id.")
    return sales


def _units(events: Sequence[StoreEvent], start: datetime) -> int:
    end = start + timedelta(hours=WINDOW_HOURS)
    return sum(event.quantity for event in events if start <= event.occurred_at < end)


def _event_payload(event: StoreEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "correlation_id": event.correlation_id,
        "event_type": event.event_type,
        "store_id": event.store_id,
        "sku": event.sku,
        "quantity": event.quantity,
        "occurred_at": format_occurred_at(event.occurred_at),
        "source": event.source,
    }


# ─── Autonomous scheduled publisher (ADR 0023) ───────────────────────────────

log = logging.getLogger(__name__)


def build_canonical_sale_event(
    *,
    quantity: int = SURGE_QUANTITIES[-1],
    store_id: str = STORE_ID,
    sku: str = SKU,
    source: str = SOURCE,
    now: datetime | None = None,
) -> StoreEvent:
    """Build one canonical ``sale.completed`` event with a fresh ``event_id``.

    The EventLog dedupes by ``event_id`` (see :class:`EventLog`), so each
    call produces a brand-new event. The store id, sku, quantity, and source
    match the demand-surge shape so the Live Twin and the analytics landers
    see the same payload the manual replay would have produced.
    """

    moment = now if now is not None else datetime.now(timezone.utc)
    return StoreEvent(
        event_id=f"evt-canonical-{secrets.token_hex(8)}",
        correlation_id=f"run-canonical-scheduler-{moment.strftime('%Y%m%d%H%M%S')}",
        event_type=SALE_COMPLETED,
        store_id=store_id,
        sku=sku,
        quantity=quantity,
        occurred_at=moment,
        source=source,
    )


class DemandSurgeScheduler:
    """Publishes a canonical ``sale.completed`` event on a fixed cadence (ADR 0023).

    Boundary: this class owns the publish cadence. It calls
    :func:`build_canonical_sale_event` per tick so the canonical ``store_id``
    and ``sku`` are reused. A failed publish is logged and the next tick
    still runs; the loop never raises out.

    ``start`` and ``stop`` are idempotent. ``stop`` awaits the running task
    with a short bounded timeout before cancelling, so the lifespan teardown
    never blocks the Cloud Run instance longer than the configurable grace
    period.
    """

    def __init__(self, pipe: EventPipe, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise BackboneError("DemandSurgeScheduler requires a positive interval.")
        self._pipe = pipe
        self._interval_seconds = float(interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Begin the publish loop. No-op when already running."""

        with self._lock:
            if self._task is not None and not self._task.done():
                return
            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(
                self._run(), name="retailtwin-demand-surge-scheduler"
            )

    async def stop(self) -> None:
        """Signal the loop to exit and wait for the task to drain."""

        with self._lock:
            stop_event = self._stop_event
            task = self._task
        if stop_event is not None:
            stop_event.set()
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
        except asyncio.CancelledError:
            pass
        finally:
            with self._lock:
                self._task = None
                self._stop_event = None

    async def _run(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                self._publish_one()
            except BackboneError as exc:
                log.warning(
                    "demand_surge.publish_failed reason=%s",
                    str(exc),
                )
            except Exception:  # noqa: BLE001 — keep the loop alive
                log.exception("demand_surge.publish_failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    def _publish_one(self) -> StoreEvent:
        event = build_canonical_sale_event()
        self._pipe.publish(event)
        log.info(
            "demand_surge.published event_id=%s correlation_id=%s sku=%s",
            event.event_id,
            event.correlation_id,
            event.sku,
        )
        return event


if __name__ == "__main__":
    raise SystemExit(main())
