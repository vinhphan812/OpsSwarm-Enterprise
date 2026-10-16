"""Deterministic customer-traffic simulator and zone heatmap aggregator.

Issue #36. The simulator produces a list of ``TrafficEvent`` records over a
fixed window for the zones derived from a ``StoreResponse`` snapshot. A
seeded ``random.Random`` keeps the same ``seed`` mapping to the same event
sequence, so the heatmap is replayable. The aggregator rolls the per-sample
``customer_count * dwell_seconds`` into ``dict[zone_id, customer_seconds]``,
which is the heatmap the API surfaces.

The wire contract is intentionally separate from ``sales_events``: a sale
represents one SKU at a point in time, while a traffic sample aggregates
many shoppers over a zone at one minute. Mixing the two would over-fit
``sale.completed`` semantics to a continuous quantity. A future
``traffic_events`` BigQuery table (issue #36 follow-up) keeps the
distinct shape; this module writes only the deterministic stream, so the
wire shape is locked before any table is provisioned.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from retailtwin_api.schemas import StoreResponse
from retailtwin_api.settings import REPO_ROOT

CANONICAL_SEED = 20261015
DEFAULT_STARTED_AT = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
MIN_DWELL_SECONDS = 30.0
DWELL_RANGE_SECONDS = 270.0


@dataclass(frozen=True)
class TrafficEvent:
    """One customer-traffic sample for a zone at a sample timestamp.

    ``customer_count`` is the count of shoppers observed in the zone at
    ``timestamp``; ``dwell_seconds`` is the average time each shopper spent
    there for that minute. Aggregating ``customer_count * dwell_seconds`` per
    zone gives the heatmap intensity.
    """

    timestamp: datetime
    zone_id: str
    customer_count: int
    dwell_seconds: float


class TrafficHeatmapResponse(BaseModel):
    """Wire shape for the public heatmap route.

    ``started_at`` is the **stable time anchor** the simulator used to start
    the window — either the explicit ``started_at`` query parameter the
    caller supplied, or :data:`DEFAULT_STARTED_AT` when omitted. It is never
    read from the wall clock, so the response is fully deterministic for a
    given ``seed``, ``window_minutes``, ``customer_count``, and anchor.
    """

    model_config = ConfigDict(extra="forbid")

    store_id: str = Field(min_length=1)
    window_minutes: int = Field(ge=1)
    started_at: datetime
    zone_customer_seconds: dict[str, float]
    total_customer_seconds: float
    simulator_seed: int = Field(ge=0)


def derive_zone_ids(snapshot: StoreResponse) -> tuple[str, ...]:
    """Unique zone ids from the snapshot's shelf ids, sorted for stability."""
    seen: set[str] = set()
    for product in snapshot.products:
        if product.shelf_id:
            seen.add(product.shelf_id)
    return tuple(sorted(seen))


class TrafficSimulator:
    """Deterministic customer-traffic simulator.

    Same ``seed`` maps to the same event sequence for any snapshot, window,
    and customer count, so the heatmap is replayable in tests and demos.
    """

    def __init__(self, seed: int = CANONICAL_SEED) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    def simulate(
        self,
        snapshot: StoreResponse,
        duration_minutes: int = 60,
        customer_count: int = 42,
        started_at: datetime | None = None,
    ) -> list[TrafficEvent]:
        """Return a list of ``TrafficEvent`` samples over ``duration_minutes``.

        The window starts at ``started_at`` (or ``DEFAULT_STARTED_AT``) and
        runs for ``duration_minutes`` whole minutes. One sample per
        ``(minute, zone)`` tuple is emitted when the seeded per-zone count
        is non-zero, so the heatmap stays compact for empty minutes.
        """
        if duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if customer_count < 0:
            raise ValueError("customer_count must be non-negative")

        rng = random.Random(self._seed)
        zone_ids = derive_zone_ids(snapshot)
        if not zone_ids:
            return []

        per_zone_target = customer_count / len(zone_ids)
        # Per-minute ceiling: even when customer_count is 0 we still sample
        # so the heatmap covers the full window without dropping minutes.
        ceiling = max(1, int(2 * per_zone_target)) if per_zone_target > 0 else 0
        base = started_at or DEFAULT_STARTED_AT
        if base.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")

        events: list[TrafficEvent] = []
        for minute in range(duration_minutes):
            timestamp = base + timedelta(minutes=minute)
            for zone_id in zone_ids:
                observed = rng.randint(0, ceiling)
                if observed == 0:
                    continue
                dwell_seconds = MIN_DWELL_SECONDS + rng.random() * DWELL_RANGE_SECONDS
                events.append(
                    TrafficEvent(
                        timestamp=timestamp,
                        zone_id=zone_id,
                        customer_count=observed,
                        dwell_seconds=round(dwell_seconds, 2),
                    )
                )
        return events


def aggregate_heatmap(events: Sequence[TrafficEvent]) -> dict[str, float]:
    """Sum ``customer_count * dwell_seconds`` per zone, rounded to two decimals.

    Empty input returns an empty dict. Zones with no positive samples are not
    created, so the heatmap only carries observed intensity.
    """
    totals: dict[str, float] = {}
    for event in events:
        if event.customer_count <= 0:
            continue
        totals[event.zone_id] = totals.get(event.zone_id, 0.0) + (
            event.customer_count * event.dwell_seconds
        )
    return {zone: round(value, 2) for zone, value in totals.items()}


def simulate_traffic(
    snapshot: StoreResponse,
    duration_minutes: int = 60,
    customer_count: int = 42,
    *,
    seed: int = CANONICAL_SEED,
    started_at: datetime | None = None,
) -> list[TrafficEvent]:
    """One-shot wrapper around :class:`TrafficSimulator`.

    Convenience for callers that don't need a reusable simulator.
    """
    return TrafficSimulator(seed=seed).simulate(
        snapshot=snapshot,
        duration_minutes=duration_minutes,
        customer_count=customer_count,
        started_at=started_at,
    )


# ─── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retailtwin-traffic",
        description="Simulate customer traffic for the day-0 store fixture.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=CANONICAL_SEED,
        help="Random seed for determinism.",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=60,
        help="Window length in whole minutes.",
    )
    parser.add_argument(
        "--customer-count",
        type=int,
        default=42,
        help="Total shoppers across the window before per-zone split.",
    )
    parser.add_argument(
        "--store-id",
        type=str,
        default="store-001",
        help="Store id to load from the fixture.",
    )
    parser.add_argument(
        "--started-at",
        type=str,
        default=None,
        help="ISO-8601 window start; defaults to 2026-10-15T08:00:00Z.",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=str(REPO_ROOT / "data" / "schemas" / "store-state.example.json"),
        help="Path to the store-state fixture.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="-",
        help="Write JSON events here, or '-' for stdout.",
    )
    return parser


def _parse_started_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("started_at must be timezone-aware (use ISO-8601 with offset).")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    from retailtwin_api.store import StoreRepository, open_store

    parser = _build_parser()
    args = parser.parse_args(argv)

    fixture = Path(args.fixture)
    repo = open_store(fixture, args.store_id)
    if not isinstance(repo, StoreRepository):
        # Memory or Firestore stores are not supported in the CLI; the
        # simulator must run on the deterministic day-0 fixture only.
        print(
                "traffic CLI requires the day-0 store fixture; "
                f"got {type(repo).__name__}.",
                file=sys.stderr,
            )
        return 2
    if not repo.loaded:
        print(f"store fixture failed to load: {repo.error}", file=sys.stderr)
        return 2

    started_at = _parse_started_at(args.started_at)
    events = simulate_traffic(
        snapshot=repo.view(),
        duration_minutes=args.duration_minutes,
        customer_count=args.customer_count,
        seed=args.seed,
        started_at=started_at,
    )
    payload = [
        {
            "timestamp": event.timestamp.isoformat(),
            "zone_id": event.zone_id,
            "customer_count": event.customer_count,
            "dwell_seconds": event.dwell_seconds,
        }
        for event in events
    ]
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    if args.output == "-":
        print(serialized)
    else:
        Path(args.output).write_text(serialized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())