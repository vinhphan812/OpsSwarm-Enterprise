"""
Pytest configuration and shared fixtures for E2E smoke tests.

Provides:
- FastAPI TestClient wired to the real app (no mocking of HTTP transport)
- Per-test isolated EventLog so events from one test never leak into another
- Session-scoped run_id for correlation across all test modules
- Timer utilities for stage-level timing assertions
- Fixture reset: API event log is cleared per test; inventory is read-only fixture

Scope conventions:
  function  – isolated per-test (event log, request state)
  session   – run_id, environment facts

Secrets policy: no real credentials; fixture data only.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.events import EventLog
from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run_id() -> str:
    """Unique run identifier shared across all tests in this session."""
    return f"smoke-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


@pytest.fixture(scope="session")
def env_info(run_id: str) -> dict:
    """Static environment facts for this smoke run."""
    return {
        "run_id": run_id,
        "canonical_path": "EVENT -> AI -> INVESTIGATE -> SIMULATE -> GUARD -> LIVE -> VERIFY",
        "store_id": "store-001",
        "fixture_path": str(DEFAULT_FIXTURE),
        "python_version": "3.11+",
    }


# ---------------------------------------------------------------------------
# Application fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> Settings:
    """Test settings – no env vars, deterministic paths."""
    return Settings(
        _env_file=None,
        app_env="e2e-smoke",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
        log_level="INFO",
    )


@pytest.fixture
def isolated_events() -> EventLog:
    """A fresh in-process EventLog per test so events never leak."""
    return EventLog()


@pytest.fixture
def client(settings: Settings, isolated_events: EventLog) -> Generator[TestClient, None, None]:
    """TestClient wired to a real FastAPI app with an isolated EventLog.

    The app's store fixture is read-only (not mutated by POST /events per
    routes.py contract), so a fresh client per test is safe for inventory.
    """
    app = create_app(settings)
    # Replace the shared event log with our isolated per-test instance
    app.state.events = isolated_events
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Timer utilities
# ---------------------------------------------------------------------------

class StageTimer:
    """Context manager that records wall-clock elapsed time for a named stage."""

    _stages: dict[str, float]

    def __init__(self) -> None:
        self._stages = {}
        self._start: float = 0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def checkpoint(self, name: str) -> float:
        """Record elapsed seconds up to this point under `name`."""
        elapsed = time.perf_counter() - self._start
        self._stages[name] = elapsed
        return elapsed

    @property
    def stages(self) -> dict[str, float]:
        return dict(self._stages)

    def report(self) -> dict:
        """Full report with durations and total."""
        stages = self.stages
        total = max(stages.values()) if stages else 0.0
        return {
            "stages": {name: round(sec, 4) for name, sec in stages.items()},
            "total_seconds": round(total, 4),
        }


@pytest.fixture
def timer() -> StageTimer:
    return StageTimer()


# ---------------------------------------------------------------------------
# Canonical event factory
# ---------------------------------------------------------------------------

def make_event(
    event_id: str | None = None,
    correlation_id: str | None = None,
    event_type: str = "sale.completed",
    sku: str = "P001",
    quantity: int = 1,
) -> dict:
    """Factory for a well-formed StoreEvent payload.

    All timestamps are UTC-aware to satisfy AwareDatetime validation.
    """
    return {
        "event_id": event_id or f"evt-{uuid.uuid4().hex[:8]}",
        "correlation_id": correlation_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "event_type": event_type,
        "store_id": "store-001",
        "sku": sku,
        "quantity": quantity,
        "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "e2e-smoke",
    }
