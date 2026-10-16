"""Tests for the FastAPI lifespan wiring of the autonomous trigger.

These tests exercise the ``create_app`` startup and teardown paths with
the autonomous trigger and scheduled publisher enabled, so the new
lifespan code in :mod:`retailtwin_api.main` is covered end-to-end.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.backbone import MemoryPipe
from retailtwin_api.demand_surge import DemandSurgeScheduler
from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "store_id": "store-001",
        "store_fixture_path": DEFAULT_FIXTURE,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_lifespan_wires_event_pipe_and_observer() -> None:
    """Default lifespan (trigger OFF) wires MemoryPipe + observer_quarantine."""

    settings = _settings()
    app = create_app(settings)
    with TestClient(app) as client:
        assert isinstance(app.state.event_pipe, MemoryPipe)
        assert app.state.activation_ledger is not None
        assert app.state.observer_quarantine is not None
        assert app.state.observer_starter is not None
        assert not hasattr(app.state, "trigger_task") or app.state.trigger_task is None
        assert not hasattr(app.state, "scheduler") or app.state.scheduler is None
        # Sanity: the app still serves traffic.
        assert client.get("/health").status_code in (200, 503)


def test_lifespan_starts_autonomous_trigger_when_enabled() -> None:
    """AUTONOMOUS_TRIGGER_ENABLED=true spawns the trigger task."""

    settings = _settings(autonomous_trigger_enabled=True, autonomous_trigger_interval_seconds=45)
    app = create_app(settings)
    with TestClient(app) as _client:
        task = getattr(app.state, "trigger_task", None)
        assert task is not None
        assert not task.done()
    # Lifespan teardown cancels the task.
    assert task.cancelled() or task.done()


def test_lifespan_starts_scheduler_when_enabled() -> None:
    """AUTONOMOUS_SCHEDULED_PUBLISHER_ENABLED=true starts the DemandSurgeScheduler."""

    settings = _settings(
        autonomous_scheduled_publisher_enabled=True,
        autonomous_trigger_interval_seconds=45,
    )
    app = create_app(settings)
    with TestClient(app) as _client:
        scheduler = getattr(app.state, "scheduler", None)
        assert isinstance(scheduler, DemandSurgeScheduler)
        assert scheduler._task is not None
        assert not scheduler._task.done()


def test_lifespan_production_uses_memory_pipe_regardless_of_project() -> None:
    """Production is push-only (P0-1).

    The lifespan wires ``MemoryPipe`` in production; the
    ``store-events-agent`` subscription is push-only (it carries a push
    endpoint at ``POST /pubsub/agent-events``). Running a second
    consumer (a pull loop) against the same subscription would flip it
    back to pull, which Cloud Run cannot do — push and pull are
    mutually exclusive on one subscription. ``GcpPubSubEventPipe`` is
    kept as a library for non-production tests; the production lifespan
    does not instantiate it.
    """

    settings = _settings(
        app_env="production",
        autonomous_pubsub_project="retailtwin-ai-511002",
        google_cloud_project="retailtwin-ai-511002",
    )
    app = create_app(settings)
    with TestClient(app) as _client:
        assert isinstance(app.state.event_pipe, MemoryPipe)


def test_lifespan_production_does_not_start_pull_loop() -> None:
    """Production must not start ``_autonomous_trigger_loop`` (P0-1).

    The lifespan skips the pull task when ``APP_ENV == production`` and
    ``AUTONOMOUS_PUBSUB_PULL_DISABLED_IN_PRODUCTION`` is true (default).
    Real events arrive over the push endpoint, not via a background
    puller.
    """

    settings = _settings(
        app_env="production",
        autonomous_trigger_enabled=True,
        autonomous_trigger_interval_seconds=45,
    )
    app = create_app(settings)
    with TestClient(app) as _client:
        trigger_task = getattr(app.state, "trigger_task", None)
        assert trigger_task is None


def test_lifespan_dev_runs_pull_loop_when_enabled() -> None:
    """Non-production keeps starting ``_autonomous_trigger_loop`` so tests
    exercise the same code path the lifespan did before P0-1."""

    settings = _settings(
        autonomous_trigger_enabled=True,
        autonomous_trigger_interval_seconds=45,
    )
    app = create_app(settings)
    with TestClient(app) as _client:
        task = getattr(app.state, "trigger_task", None)
        assert task is not None and not task.done()


def test_lifespan_production_can_opt_into_pull_loop_explicitly() -> None:
    """Setting ``AUTONOMOUS_PUBSUB_PULL_DISABLED_IN_PRODUCTION=false`` lets a
    production build opt back into the pull loop. The default is True —
    the production recommendation — but a future operator may want a
    separate pull-mode subscription."""

    settings = _settings(
        app_env="production",
        autonomous_trigger_enabled=True,
        autonomous_trigger_interval_seconds=45,
        autonomous_pubsub_pull_disabled_in_production=False,
    )
    app = create_app(settings)
    with TestClient(app) as _client:
        task = getattr(app.state, "trigger_task", None)
        assert task is not None and not task.done()


def test_autonomous_trigger_loop_runs_consume_available() -> None:
    """The trigger task actually consumes from the pipe and acks the message."""

    settings = _settings(
        autonomous_trigger_enabled=True,
        autonomous_trigger_interval_seconds=45,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # Reach into the lifespan-built pipe and publish a canonical event.
        pipe: MemoryPipe = app.state.event_pipe  # type: ignore[assignment]
        from retailtwin_api.demand_surge import build_canonical_sale_event

        event = build_canonical_sale_event()
        pipe.publish(event)

        # Wait for both the consumer to drain ``pending`` AND for the
        # ack to land. The consumer pulls the message out of ``pending``
        # before driving the flagship chain, so a check on ``pending``
        # alone races with the ``pipe.ack`` that runs after the chain.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not pipe.pending and pipe.acked:
                break
            time.sleep(0.05)
        assert pipe.pending == []  # consumed
        assert pipe.acked  # acked
        # Sanity: the app still serves traffic.
        assert client.get("/health").status_code in (200, 503)


def test_lifespan_teardown_is_clean_for_trigger_task() -> None:
    """Cancelling the lifespan does not leak threads or asyncio tasks."""

    settings = _settings(autonomous_trigger_enabled=True)
    app = create_app(settings)
    captured_task: asyncio.Task[None] | None = None
    with TestClient(app):
        captured_task = getattr(app.state, "trigger_task", None)
        assert captured_task is not None
    # After teardown the lifespan nulls the state slot.
    assert getattr(app.state, "trigger_task", "missing") is None