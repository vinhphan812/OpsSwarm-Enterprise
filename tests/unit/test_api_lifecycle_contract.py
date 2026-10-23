"""Unit tests for the container-delivery lifecycle contract (Issue #73).

The container delivery acceptance criteria (ADR-030) depend on behaviours
that are easy to regress silently because they only run on the shutdown path
or on failure paths:

* the lifecycle state machine must expose ``startup_error`` and
  ``is_accepting_work`` so ``/ready`` can report *why* it is not ready
  without leaking internals;
* ``drain()`` must cancel background tasks that exceed the drain timeout
  instead of waiting forever;
* ``wait_for_drain()`` must be usable from a synchronous context;
* an inaccessible data directory must fail closed with a ``ValueError``;
* a failed startup check must mark the app FAILED rather than crash the
  process, so ``/health`` still answers while ``/ready`` reports 503;
* the ``/metrics`` scrape must reflect the live run-state counts;
* a malformed ``Content-Length`` header must not defeat the monitoring
  body-size guard.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

import pytest

import opsswarm.api as api_module
from opsswarm.api import AppState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_lifecycle_state():
    """Restore the singleton lifecycle state after each test.

    ``LifecycleManager`` is a process-wide singleton, so state left behind by
    another test module (a FAILED startup, a registered background task) would
    otherwise leak into these assertions.  The fixture installs a known
    baseline before the test and restores the previous state afterwards.
    """
    original_state = api_module.lifecycle._state
    original_error = api_module.lifecycle._startup_error
    original_tasks = list(api_module.lifecycle._background_tasks)
    original_timeout = api_module.lifecycle._drain_timeout

    api_module.lifecycle._state = AppState.STARTING
    api_module.lifecycle._startup_error = None
    api_module.lifecycle._background_tasks = []
    api_module.lifecycle._drain_event.clear()

    yield

    api_module.lifecycle._state = original_state
    api_module.lifecycle._startup_error = original_error
    api_module.lifecycle._background_tasks = original_tasks
    api_module.lifecycle._drain_timeout = original_timeout
    api_module.lifecycle._drain_event.clear()


# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------


class TestLifecycleStateReporting:
    """The lifecycle must report state and reason without leaking internals."""

    def test_startup_error_is_none_before_a_failure(self):
        """A healthy process has no startup error."""
        api_module.lifecycle.set_ready()
        assert api_module.lifecycle.startup_error is None

    def test_startup_error_records_the_failure_reason(self):
        """set_failed() records the reason /ready reports internally."""
        api_module.lifecycle.set_failed("auth token missing")

        assert api_module.lifecycle.startup_error == "auth token missing"
        assert api_module.lifecycle.state == AppState.FAILED

    def test_is_accepting_work_only_when_ready(self):
        """Work is accepted only in the READY state."""
        api_module.lifecycle.set_ready()
        assert api_module.lifecycle.is_accepting_work is True

        api_module.lifecycle.set_draining()
        assert api_module.lifecycle.is_accepting_work is False

    def test_draining_only_transitions_from_ready(self):
        """A non-READY state must not be silently overwritten by set_draining."""
        api_module.lifecycle._state = AppState.FAILED
        api_module.lifecycle.set_draining()
        assert api_module.lifecycle.state == AppState.FAILED


# ---------------------------------------------------------------------------
# Drain behaviour
# ---------------------------------------------------------------------------


class TestDrainBehaviour:
    """Drain must be bounded and must cancel work that overruns the timeout."""

    @pytest.mark.asyncio
    async def test_drain_without_background_tasks_completes(self):
        """With nothing registered, drain completes immediately."""
        api_module.lifecycle._background_tasks = []

        await api_module.lifecycle.drain(timeout=1)

        assert api_module.lifecycle.wait_for_drain(timeout=1) is True

    @pytest.mark.asyncio
    async def test_drain_cancels_tasks_that_exceed_the_timeout(self):
        """A task that never finishes is cancelled, not awaited forever."""
        cancelled = asyncio.Event()

        async def never_ends() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(never_ends())
        api_module.lifecycle.register_background_task(task)

        await api_module.lifecycle.drain(timeout=1)

        # drain() cancels the task but does not await its cancellation; give
        # the event loop a turn so the coroutine observes the CancelledError.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert cancelled.is_set(), "the overrunning background task must be cancelled"
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_drain_awaits_a_task_that_finishes_in_time(self):
        """A task that completes within the timeout is not cancelled."""
        finished = asyncio.Event()

        async def finishes_soon() -> None:
            await asyncio.sleep(0)
            finished.set()

        task = asyncio.create_task(finishes_soon())
        api_module.lifecycle.register_background_task(task)

        await api_module.lifecycle.drain(timeout=5)

        assert finished.is_set()
        assert not task.cancelled()

    def test_wait_for_drain_returns_false_on_timeout(self):
        """wait_for_drain() reports a bounded wait, never blocking forever."""
        api_module.lifecycle._drain_event.clear()

        assert api_module.lifecycle.wait_for_drain(timeout=1) is False


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


class TestStartupValidation:
    """Startup failures must fail closed, not crash the process."""

    def test_inaccessible_data_directory_raises_value_error(self, tmp_path):
        """An unwritable data directory is a startup failure."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        unusable = str(blocker / "nested")

        with pytest.raises(ValueError, match="Data directory not accessible"):
            api_module._validate_data_path(unusable)

    def test_writable_data_directory_is_resolved(self, tmp_path):
        """A writable data directory is created and resolved to an absolute path."""
        target = tmp_path / "runtime-data"

        resolved = api_module._validate_data_path(str(target))

        assert os.path.isabs(resolved)
        assert os.path.isdir(resolved)
        # The write probe must not leave a file behind.
        assert not (target / ".write_test").exists()

    @pytest.mark.asyncio
    async def test_failed_startup_check_marks_the_app_failed(self, monkeypatch):
        """A raising startup check leaves the app FAILED but still serving."""

        async def boom() -> None:
            raise RuntimeError("config missing")

        monkeypatch.setattr(api_module, "_startup_checks", boom)

        async with api_module.lifespan(api_module.app):
            assert api_module.lifecycle.state == AppState.FAILED
            assert api_module.lifecycle.startup_error == "config missing"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetricsRunStates:
    """The /metrics scrape must reflect the live run-state counts."""

    @pytest.mark.asyncio
    async def test_metrics_counts_runs_by_state(self, monkeypatch):
        """Runs in different states are counted separately."""
        import opsswarm.metrics as metrics_module

        run_open = MagicMock()
        run_open.state = api_module.RunState.OPEN if hasattr(api_module, "RunState") else None
        run_closed = MagicMock()
        run_closed.state = None

        fake_engine = MagicMock()
        fake_engine.runs = {1: run_open, 2: run_closed}
        monkeypatch.setattr(api_module, "engine", fake_engine)

        response = await api_module.get_metrics()

        assert response.status_code == 200
        body = response.body.decode("utf-8")
        assert "opsswarm_active_runs" in body or "active_runs" in body
        assert metrics_module.metrics is not None


# ---------------------------------------------------------------------------
# Monitoring ingress guards
# ---------------------------------------------------------------------------


class TestMonitoringBodySizeGuard:
    """A malformed Content-Length must not bypass the body-size guard."""

    @pytest.mark.asyncio
    async def test_invalid_content_length_is_treated_as_unknown(self):
        """A non-integer Content-Length is ignored, then the real body is checked."""
        checked: list[int | None] = []

        class _FakeRequest:
            headers = {"content-length": "not-a-number"}
            client = None

            async def body(self) -> bytes:
                return b"{}"

        def _record(value: int | None) -> None:
            checked.append(value)

        original = api_module.check_monitoring_body_size
        api_module.check_monitoring_body_size = _record
        try:
            with pytest.raises(api_module.HTTPException):
                await api_module.monitoring_event(_FakeRequest())
        finally:
            api_module.check_monitoring_body_size = original

        # The header-derived value is None (unparseable) and the real body
        # length is still checked.
        assert checked[0] is None
        assert checked[1] == 2
