"""Unit tests for the SIGTERM handler chaining contract (Issue #73).

The container delivery acceptance criteria (ADR-030) require that a SIGTERM
delivered to the application:

1. marks the lifecycle state as DRAINING, so ``/ready`` starts returning 503,
2. schedules the bounded background-task drain, and
3. delegates to the handler that was installed previously — typically uvicorn's
   — so the server actually performs its graceful shutdown.

Point (3) is the part that is easy to get wrong: replacing uvicorn's handler
instead of chaining to it leaves the process running until the orchestrator
escalates to SIGKILL.
"""

from __future__ import annotations

import asyncio
import signal
from unittest.mock import MagicMock

import pytest

import opsswarm.api as api_module
from opsswarm.api import AppState, _install_sigterm_handler, _make_sigterm_handler


@pytest.fixture(autouse=True)
def _reset_lifecycle_state():
    """Restore the lifecycle state after each test."""
    original = api_module.lifecycle._state
    yield
    api_module.lifecycle._state = original


class TestSigtermHandlerChaining:
    """The handler must chain to the previously installed handler."""

    def test_delegates_to_previous_callable_handler(self):
        """The previous handler is invoked with the original signum/frame."""
        previous = MagicMock()
        handler = _make_sigterm_handler(previous)

        frame = object()
        handler(signal.SIGTERM, frame)

        previous.assert_called_once()
        assert previous.call_args[0][0] == signal.SIGTERM
        assert previous.call_args[0][1] is frame

    def test_previous_handler_is_called_even_without_a_running_loop(self):
        """Chaining must not depend on the event loop being available."""
        previous = MagicMock()
        handler = _make_sigterm_handler(previous)

        # No event loop is running in this synchronous test, so the
        # call_soon_threadsafe path raises RuntimeError and is swallowed.
        handler(signal.SIGTERM, None)

        previous.assert_called_once()

    def test_marks_lifecycle_as_draining(self):
        """A SIGTERM moves the lifecycle out of READY."""
        api_module.lifecycle.set_ready()
        assert api_module.lifecycle.state == AppState.READY

        handler = _make_sigterm_handler(MagicMock())
        handler(signal.SIGTERM, None)

        assert api_module.lifecycle.state == AppState.DRAINING

    def test_sigdef_restores_default_and_resignals(self, monkeypatch):
        """When the previous handler was SIG_DFL, the default is restored.

        Restoring SIG_DFL and re-raising the signal reproduces the behaviour
        the process had before the handler was installed, rather than
        swallowing the signal.
        """
        killed = []

        def _fake_kill(pid, sig):
            killed.append((pid, sig))

        monkeypatch.setattr(api_module.os, "kill", _fake_kill)
        monkeypatch.setattr(api_module.signal, "signal", lambda *a, **k: None)

        handler = _make_sigterm_handler(signal.SIG_DFL)
        handler(signal.SIGTERM, None)

        assert len(killed) == 1
        assert killed[0][1] == signal.SIGTERM

    def test_no_previous_handler_does_not_raise(self):
        """A missing previous handler must not break the drain path."""
        api_module.lifecycle.set_ready()
        handler = _make_sigterm_handler(None)
        # Must not raise.
        handler(signal.SIGTERM, None)
        assert api_module.lifecycle.state == AppState.DRAINING


class TestInstallSigtermHandler:
    """Installation must be safe on every platform."""

    def test_installs_handler_and_returns_it(self, monkeypatch):
        """A successful installation returns the installed handler."""
        installed = {}

        def _fake_signal(sig, handler):
            installed[sig] = handler

        monkeypatch.setattr(api_module.signal, "signal", _fake_signal)
        monkeypatch.setattr(api_module.signal, "getsignal", lambda sig: None)

        handler = _install_sigterm_handler()

        assert handler is not None
        assert installed[signal.SIGTERM] is handler

    def test_returns_none_when_signal_unsupported(self, monkeypatch):
        """Platforms without SIGTERM support degrade to a no-op."""

        def _raise(*args, **kwargs):
            raise ValueError("signal only works in main thread")

        monkeypatch.setattr(api_module.signal, "signal", _raise)

        assert _install_sigterm_handler() is None


class TestSigtermDrainScheduling:
    """The drain coroutine must be scheduled on the running event loop."""

    @pytest.mark.asyncio
    async def test_drain_is_scheduled_on_the_running_loop(self):
        """The handler schedules lifecycle.drain() on the running loop."""
        api_module.lifecycle.set_ready()
        previous = MagicMock()
        handler = _make_sigterm_handler(previous)

        handler(signal.SIGTERM, None)

        # Let the scheduled callback run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert api_module.lifecycle.state == AppState.DRAINING
        previous.assert_called_once()
