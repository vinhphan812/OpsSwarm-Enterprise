"""Deterministic traffic-simulator tests (issue #36)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.main import create_app
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.synthetic.traffic import (
    CANONICAL_SEED,
    DEFAULT_STARTED_AT,
    DWELL_RANGE_SECONDS,
    MIN_DWELL_SECONDS,
    TrafficEvent,
    TrafficSimulator,
    aggregate_heatmap,
    derive_zone_ids,
    simulate_traffic,
)


def _multi_zone_snapshot() -> StoreResponse:
    """A three-shelf store used to exercise the per-zone heatmap path."""
    return StoreResponse(
        store_id="store-001",
        context_version="store-001:test",
        version="v1",
        products=[
            ProductInventory(
                store_id="store-001",
                sku="P001",
                shelf_id="A01",
                slot_id="A01-S01",
                facings=3,
                shelf_quantity=8,
                backroom_quantity=42,
                version=1,
            ),
            ProductInventory(
                store_id="store-001",
                sku="P002",
                shelf_id="B01",
                slot_id="B01-S01",
                facings=4,
                shelf_quantity=10,
                backroom_quantity=20,
                version=1,
            ),
            ProductInventory(
                store_id="store-001",
                sku="P003",
                shelf_id="B02",
                slot_id="B02-S01",
                facings=2,
                shelf_quantity=5,
                backroom_quantity=15,
                version=1,
            ),
        ],
    )


def _single_zone_snapshot() -> StoreResponse:
    """Mirror of the committed day-0 fixture: a single shelf zone."""
    return StoreResponse(
        store_id="store-001",
        context_version="store-001:v1",
        version="v1",
        products=[
            ProductInventory(
                store_id="store-001",
                sku="P001",
                shelf_id="A01",
                slot_id="A01-S01",
                facings=3,
                shelf_quantity=8,
                backroom_quantity=42,
                version=1,
            ),
        ],
    )


class TestDeriveZoneIds:
    def test_returns_sorted_unique_zone_ids(self) -> None:
        snapshot = _multi_zone_snapshot()
        assert derive_zone_ids(snapshot) == ("A01", "B01", "B02")

    def test_single_zone_fixture(self) -> None:
        snapshot = _single_zone_snapshot()
        assert derive_zone_ids(snapshot) == ("A01",)


class TestDeterministicSeed:
    def test_simulator_is_deterministic_with_seed(self) -> None:
        snapshot = _multi_zone_snapshot()
        first = TrafficSimulator(seed=CANONICAL_SEED).simulate(
            snapshot, duration_minutes=30, customer_count=42
        )
        second = TrafficSimulator(seed=CANONICAL_SEED).simulate(
            snapshot, duration_minutes=30, customer_count=42
        )
        assert first == second
        assert len(first) > 0

    def test_different_seeds_produce_different_streams(self) -> None:
        snapshot = _multi_zone_snapshot()
        a = TrafficSimulator(seed=1).simulate(snapshot, duration_minutes=10, customer_count=42)
        b = TrafficSimulator(seed=2).simulate(snapshot, duration_minutes=10, customer_count=42)
        assert a != b


class TestZoneIdsValid:
    def test_simulator_emits_valid_zone_ids(self) -> None:
        snapshot = _multi_zone_snapshot()
        valid_zones = set(derive_zone_ids(snapshot))
        events = simulate_traffic(
            snapshot, duration_minutes=20, customer_count=42, seed=CANONICAL_SEED
        )
        assert events, "deterministic run should not be empty"
        unknown = {event.zone_id for event in events} - valid_zones
        assert not unknown, f"unknown zone ids emitted: {sorted(unknown)}"
        # Every snapshot zone appears at least once across the window.
        assert {event.zone_id for event in events} == valid_zones


class TestDurationRespected:
    def test_simulator_respects_duration(self) -> None:
        snapshot = _multi_zone_snapshot()
        events = simulate_traffic(
            snapshot,
            duration_minutes=15,
            customer_count=42,
            seed=CANONICAL_SEED,
            started_at=DEFAULT_STARTED_AT,
        )
        assert events
        earliest = min(event.timestamp for event in events)
        latest = max(event.timestamp for event in events)
        window = timedelta(minutes=15)
        assert earliest >= DEFAULT_STARTED_AT
        assert latest - earliest < window
        # At most one sample per (minute, zone) per zone-minute cell.
        cells = {(event.timestamp, event.zone_id) for event in events}
        assert len(cells) == len(events)


class TestHeatmapAggregation:
    def test_heatmap_aggregates_per_zone(self) -> None:
        snapshot = _multi_zone_snapshot()
        events = simulate_traffic(
            snapshot, duration_minutes=20, customer_count=42, seed=CANONICAL_SEED
        )
        heatmap = aggregate_heatmap(events)
        assert set(heatmap.keys()) == set(derive_zone_ids(snapshot))
        # Manual cross-check: heatmap equals sum of customer_count * dwell per zone.
        for zone_id, expected_total in heatmap.items():
            zone_events = [e for e in events if e.zone_id == zone_id]
            manual = sum(e.customer_count * e.dwell_seconds for e in zone_events)
            assert heatmap[zone_id] == round(manual, 2)

    def test_heatmap_is_empty_for_no_events(self) -> None:
        assert aggregate_heatmap([]) == {}

    def test_heatmap_skips_zero_count_events(self) -> None:
        events = [
            TrafficEvent(
                timestamp=DEFAULT_STARTED_AT,
                zone_id="A01",
                customer_count=0,
                dwell_seconds=120.0,
            ),
            TrafficEvent(
                timestamp=DEFAULT_STARTED_AT,
                zone_id="B01",
                customer_count=3,
                dwell_seconds=60.0,
            ),
        ]
        heatmap = aggregate_heatmap(events)
        assert heatmap == {"B01": 180.0}


class TestReplayableOutput:
    def test_simulator_produces_replayable_output(self, tmp_path: Path) -> None:
        snapshot = _multi_zone_snapshot()
        events = simulate_traffic(
            snapshot, duration_minutes=10, customer_count=42, seed=CANONICAL_SEED
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
        path = tmp_path / "events.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded == payload
        # Round-trip through TrafficEvent preserves equality.
        rebuilt = [
            TrafficEvent(
                timestamp=datetime.fromisoformat(item["timestamp"]),
                zone_id=item["zone_id"],
                customer_count=item["customer_count"],
                dwell_seconds=item["dwell_seconds"],
            )
            for item in reloaded
        ]
        assert rebuilt == events


class TestInvariants:
    def test_dwell_seconds_within_band(self) -> None:
        snapshot = _multi_zone_snapshot()
        events = simulate_traffic(
            snapshot, duration_minutes=10, customer_count=42, seed=CANONICAL_SEED
        )
        assert events
        for event in events:
            assert MIN_DWELL_SECONDS <= event.dwell_seconds <= MIN_DWELL_SECONDS + DWELL_RANGE_SECONDS
            assert event.customer_count >= 1

    def test_seed_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError):
            TrafficSimulator(seed=-1)

    def test_seed_rejects_non_integer(self) -> None:
        with pytest.raises(TypeError):
            TrafficSimulator(seed="1")  # type: ignore[arg-type]

    def test_duration_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            simulate_traffic(
                _multi_zone_snapshot(), duration_minutes=0, customer_count=42, seed=CANONICAL_SEED
            )

    def test_customer_count_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError):
            simulate_traffic(
                _multi_zone_snapshot(),
                duration_minutes=10,
                customer_count=-1,
                seed=CANONICAL_SEED,
            )

    def test_started_at_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValueError):
            simulate_traffic(
                _multi_zone_snapshot(),
                duration_minutes=10,
                customer_count=42,
                seed=CANONICAL_SEED,
                started_at=datetime(2026, 10, 15, 8, 0),
            )

    def test_empty_snapshot_returns_empty_events(self) -> None:
        empty = StoreResponse(
            store_id="store-001",
            context_version="store-001:v1",
            version="v1",
            products=[],
        )
        events = simulate_traffic(empty, duration_minutes=10, customer_count=42)
        assert events == []
        assert aggregate_heatmap(events) == {}


class TestTrafficHeatmapRoute:
    def _build_settings(self, traffic_enabled: bool) -> Settings:
        return Settings(
            _env_file=None,
            app_env="test",
            store_id="store-001",
            store_fixture_path=DEFAULT_FIXTURE,
            traffic_enabled=traffic_enabled,
        )

    def test_route_503_when_flag_off(self) -> None:
        app = create_app(self._build_settings(traffic_enabled=False))
        with TestClient(app) as client:
            response = client.get("/traffic/heatmap")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "traffic_disabled"

    def test_route_200_when_flag_on(self) -> None:
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            response = client.get(
                "/traffic/heatmap",
                params={"window_minutes": 30, "seed": CANONICAL_SEED, "customer_count": 12},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["store_id"] == "store-001"
        assert body["window_minutes"] == 30
        assert body["simulator_seed"] == CANONICAL_SEED
        assert isinstance(body["zone_customer_seconds"], dict)
        assert body["total_customer_seconds"] >= 0

    def test_route_is_deterministic_with_seed(self) -> None:
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            params = {"window_minutes": 30, "seed": CANONICAL_SEED, "customer_count": 12}
            first = client.get("/traffic/heatmap", params=params).json()
            second = client.get("/traffic/heatmap", params=params).json()
        # With the stable-anchor fix, ``started_at`` also falls back to the
        # documented fixed default, so two requests with identical inputs must
        # produce byte-identical responses.
        assert first == second

    def test_route_rejects_unknown_store(self) -> None:
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            response = client.get(
                "/traffic/heatmap",
                params={"store_id": "store-999", "seed": CANONICAL_SEED},
            )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "store_not_found"

    def test_route_validates_window_minutes(self) -> None:
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            response = client.get("/traffic/heatmap", params={"window_minutes": 0})
        assert response.status_code == 422

    def test_traffic_heatmap_uses_supplied_started_at(self) -> None:
        # Issue #36 review: explicit anchor must be echoed by the response so
        # callers can reproduce a heatmap byte-for-byte.
        anchor = "2026-10-16T12:00:00Z"
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            response = client.get(
                "/traffic/heatmap",
                params={"started_at": anchor, "seed": 42, "customer_count": 8},
            )
        assert response.status_code == 200
        body = response.json()
        # FastAPI normalizes the timezone to +00:00; accept the same wall value.
        assert datetime.fromisoformat(body["started_at"]) == datetime(
            2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc
        )
        assert body["simulator_seed"] == 42

    def test_traffic_heatmap_deterministic_for_same_seed_and_anchor(self) -> None:
        # Two requests with the same seed AND the same explicit anchor must
        # produce byte-identical responses, even when issued at different
        # wall-clock times.
        anchor = "2026-10-16T12:00:00+00:00"
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            params = {
                "started_at": anchor,
                "seed": 42,
                "customer_count": 8,
                "window_minutes": 30,
            }
            first = client.get("/traffic/heatmap", params=params).json()
            second = client.get("/traffic/heatmap", params=params).json()
        assert first == second
        # And the same seed with the same anchor yields a stable, equal response.
        assert first["started_at"] == second["started_at"]
        assert first["zone_customer_seconds"] == second["zone_customer_seconds"]
        assert first["total_customer_seconds"] == second["total_customer_seconds"]

    def test_traffic_heatmap_anchor_in_optional_path(self) -> None:
        # Omitting started_at must fall back to the documented fixed anchor so
        # the route stays deterministic without a caller-supplied value.
        app = create_app(self._build_settings(traffic_enabled=True))
        with TestClient(app) as client:
            response = client.get(
                "/traffic/heatmap",
                params={"seed": 42, "customer_count": 8, "window_minutes": 30},
            )
        assert response.status_code == 200
        body = response.json()
        assert (
            datetime.fromisoformat(body["started_at"])
            == DEFAULT_STARTED_AT.astimezone(timezone.utc)
        )
        # Same call repeated immediately must hit the same anchor; the route
        # never reads datetime.now(), so it cannot drift between requests.
        again = client.get(
            "/traffic/heatmap",
            params={"seed": 42, "customer_count": 8, "window_minutes": 30},
        ).json()
        assert again["started_at"] == body["started_at"]