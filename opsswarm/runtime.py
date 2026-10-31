"""Local process readiness and graceful request draining.

This module is deliberately process-local. It gates new ingress while a worker
is stopping and waits for already-accepted dispatches to finish. Distributed
run ownership belongs to the future HA coordination backend (Issue #70).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from fastapi import HTTPException

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class ReadinessManager:
    """Coordinate startup readiness with a process-local graceful drain."""

    def __init__(self) -> None:
        self._is_ready = False
        self._is_draining = False
        self._inflight = 0
        self._lock = asyncio.Lock()
        self._drained = asyncio.Event()
        self._drained.set()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def startup_complete(self) -> None:
        """Mark a successfully preflighted process ready to accept dispatch."""
        async with self._lock:
            self._is_draining = False
            self._is_ready = True
            logger.info("Startup preflight complete; readiness is READY")

    async def begin_dispatch(self) -> None:
        """Atomically reject new work during drain or register accepted work."""
        async with self._lock:
            if self._is_draining:
                raise HTTPException(status_code=503, detail="Service is draining")
            self._inflight += 1
            self._drained.clear()

    async def end_dispatch(self) -> None:
        """Record completion of an accepted dispatch and wake a draining worker."""
        self._release_inflight()

    def _release_inflight(self) -> None:
        """Release one in-flight slot without awaiting.

        The release deliberately does not acquire ``self._lock``: it contains no
        await point, so it is atomic with respect to the event loop and cannot
        be interrupted by task cancellation.  A cancelled release would strand
        the in-flight counter above zero and make the drain wait forever.
        """
        if self._inflight <= 0:
            return
        self._inflight -= 1
        if self._inflight == 0:
            self._drained.set()

    async def _track_dispatch(self) -> None:
        """Count one accepted dispatch without re-checking the drain gate.

        Detached work is registered by a handler that already passed the drain
        gate, so the work is accepted even if the drain started in the
        meantime.  Re-checking the gate here would drop accepted work and make
        the caller retry it.
        """
        async with self._lock:
            self._inflight += 1
            self._drained.clear()

    async def start_background_dispatch(self, coroutine: Awaitable[Any]) -> None:
        """Register detached work before scheduling it, so drain sees its lifetime.

        The in-flight slot is held from before the task is scheduled until the
        task completes or is cancelled, and it is released exactly once.  The
        release never awaits, so a cancelled task cannot strand readiness
        state and leave the drain hanging.
        """
        try:
            await self._track_dispatch()
        except BaseException:
            # The reservation never happened, so the caller still owns the
            # coroutine: close it instead of leaving it un-awaited.
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()
            raise

        released = False
        started = False

        def release_once() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._release_inflight()

        async def run() -> None:
            nonlocal started
            started = True
            try:
                await coroutine
            finally:
                release_once()

        runner = run()
        try:
            task = asyncio.create_task(runner)
        except BaseException:
            # Task creation did not transfer ownership: close both unstarted
            # coroutines where possible and roll back the reservation.
            runner.close()
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()
            release_once()
            raise

        # Keep a strong reference so the task cannot be garbage collected
        # while it is still running detached work.
        self._background_tasks.add(task)

        def complete(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            try:
                completed.result()
            except asyncio.CancelledError:
                logger.info("Background dispatch cancelled during shutdown")
            except Exception:
                logger.exception("Background dispatch failed")
            finally:
                if not started:
                    # Cancelled before its first step: run() never entered its
                    # body, so the inner coroutine was never awaited.
                    close = getattr(coroutine, "close", None)
                    if close is not None:
                        close()
                # A task cancelled before its first step never reaches run()'s
                # finally block; release_once() is idempotent either way.
                release_once()

        task.add_done_callback(complete)

    async def initiate_drain(self) -> None:
        """Stop accepting dispatches, then wait for accepted work to complete."""
        async with self._lock:
            self._is_draining = True
            self._is_ready = False
            logger.info("Drain initiated; waiting for %d in-flight dispatch(es)", self._inflight)
        await self._drained.wait()
        logger.info("Drain complete; no in-flight dispatches remain")

    @property
    def ready(self) -> bool:
        return self._is_ready and not self._is_draining

    @property
    def draining(self) -> bool:
        return self._is_draining


readiness = ReadinessManager()


def get_readiness() -> ReadinessManager:
    """Return the process-wide readiness manager.

    Consumers must resolve the manager through this accessor instead of
    binding ``runtime.readiness`` at import time. The test-suite replaces the
    module attribute to isolate state; a by-value import would keep a stale
    reference and silently bypass the active manager.
    """
    return readiness


def check_draining(func: F) -> F:
    """Reject new mutable dispatches after drain starts and track accepted work."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        await get_readiness().begin_dispatch()
        try:
            return await func(*args, **kwargs)
        finally:
            await get_readiness().end_dispatch()

    return wrapper  # type: ignore[return-value]
