"""Local process readiness and graceful request draining.

This module is deliberately process-local. It gates new ingress while a worker
is stopping and waits for already-accepted dispatches to finish. Distributed
run ownership belongs to the future HA coordination backend (Issue #70).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypeVar

from fastapi import HTTPException

from .evidence import EvidenceStore
from .models import RunRecord, RunState
from .store import RunStore

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

#: How long shutdown waits for accepted work before declaring it abandoned.
#: Kubernetes sends SIGKILL after ``terminationGracePeriodSeconds``; waiting
#: past that point loses the evidence of what was still running, so the drain
#: is bounded and reports what it gave up on.
DEFAULT_DRAIN_TIMEOUT_SECONDS = 30.0

#: Environment override for the bounded drain, in seconds.
DRAIN_TIMEOUT_ENV = "OPSWARM_DRAIN_TIMEOUT_SECONDS"


def _configured_drain_timeout() -> float:
    """Return the drain timeout from the environment, falling back to the default."""
    raw = os.environ.get(DRAIN_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r", DRAIN_TIMEOUT_ENV, raw)
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    if not math.isfinite(value) or value < 0:
        logger.warning("Ignoring out-of-range %s=%r", DRAIN_TIMEOUT_ENV, raw)
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    return value


class ReadinessManager:
    """Coordinate startup readiness with a process-local graceful drain."""

    def __init__(
        self,
        *,
        store: RunStore | None = None,
        evidence: EvidenceStore | None = None,
        data_dir: str | None = None,
    ) -> None:
        self._is_ready = False
        self._is_draining = False
        self._inflight = 0
        self._lock = asyncio.Lock()
        self._drained = asyncio.Event()
        self._drained.set()
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._labels: dict[asyncio.Task[Any], str] = {}
        self._task_issues: dict[asyncio.Task[Any], int] = {}
        self._persist_accepted: dict[asyncio.Task[Any], bool] = {}
        self._store = store or RunStore(data_dir or "runtime-data")
        self._evidence = evidence or EvidenceStore(data_dir or "runtime-data")
        #: Labels of accepted dispatches that shutdown gave up on.  Shutdown
        #: never drops accepted work silently: anything listed here was still
        #: in flight when the drain deadline passed (or was cancelled), so its
        #: run must be reconciled from durable run state on the next start.
        self.abandoned_dispatches: list[str] = []


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

    async def start_background_dispatch(
        self,
        coroutine: Awaitable[Any],
        *,
        label: str | None = None,
        issue_number: int | None = None,
        persist_accepted: bool = False,
    ) -> None:
        """Register detached work before scheduling it, so drain sees its lifetime.

        The in-flight slot is held from before the task is scheduled until the
        task completes or is cancelled, and it is released exactly once.  The
        release never awaits, so a cancelled task cannot strand readiness
        state and leave the drain hanging.

        ``label`` names the work in the abandonment record.  Accepted work is
        never dropped silently: if the task is cancelled after it started, the
        label is recorded so the owning run can be reconciled from durable run
        state instead of vanishing with the process.
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
        if label is not None:
            self._labels[task] = label
        if issue_number is not None:
            self._task_issues[task] = issue_number
        self._persist_accepted[task] = persist_accepted

        def complete(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            self._labels.pop(completed, None)
            self._task_issues.pop(completed, None)
            self._persist_accepted.pop(completed, None)
            try:
                completed.result()
            except asyncio.CancelledError:
                logger.info("Background dispatch cancelled during shutdown")
                if started:
                    # The work had already begun.  Its run may be half
                    # applied, so record it for reconciliation rather than
                    # letting the cancellation erase the fact that it ran.
                    self._record_abandoned(label, issue_number, persist_accepted)

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

    def _record_abandoned(
        self,
        label: str | None,
        issue_number: int | None = None,
        persist_accepted: bool = False,
    ) -> None:
        """Persist a durable marker for an accepted dispatch shutdown gave up on.

        With ``persist_accepted`` the marker lands on the issue's own run record
        (creating one if the dispatch had not written it yet), so the ordinary
        restart reconciliation finds it.  Otherwise a dedicated marker record is
        written; it can never overwrite another incident's run.
        """
        name = label or "unlabelled"
        record: RunRecord | None = None
        if persist_accepted and issue_number is not None:
            record = next(
                (run for run in self._store.load_all() if run.issue_number == issue_number), None
            )
            if record is None:
                record = RunRecord(
                    run_id=f"RUN-GH-{issue_number}-{uuid.uuid4().hex[:8]}",
                    issue_number=issue_number,
                    state=RunState.INVESTIGATING,
                )
        if record is None:
            record = RunRecord(
                run_id=f"DISPATCH-{uuid.uuid4().hex}",
                issue_number=issue_number or 0,
                state=RunState.INVESTIGATING,
            )
        record.mark_command_unknown(name)
        record.error = (
            "Accepted background dispatch was interrupted during shutdown; outcome unknown."
        )
        self._store.save(record)
        self._store.save_checkpoint(record, "shutdown_drain_timeout")
        self._evidence.append(
            record.run_id,
            "S5.dispatch.abandoned",
            {
                "dispatch_label": name,
                "issue_number": issue_number,
                "outcome": "unknown",
                "reconciliation_required": True,
                "interrupted_by": "shutdown_drain_timeout",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        self.abandoned_dispatches.append(name)
        logger.error(
            "Dispatch abandoned during shutdown: %s (durable reconciliation marker %s)",
            name,
            record.run_id,
        )

    async def initiate_drain(self, timeout: float | None = None) -> bool:
        """Stop accepting dispatches, then wait for accepted work to complete.

        The wait is bounded: a hung dispatch must not carry shutdown past the
        orchestrator's grace period, because SIGKILL then destroys the evidence
        of what was still running.  Returns ``True`` when everything accepted
        finished, ``False`` when the deadline passed and work was abandoned.
        """
        if timeout is None:
            timeout = _configured_drain_timeout()
        async with self._lock:
            self._is_draining = True
            self._is_ready = False
            logger.info("Drain initiated; waiting for %d in-flight dispatch(es)", self._inflight)
        if self._inflight == 0:
            self._drained.set()
            logger.info("Drain complete; no in-flight dispatches remain")
            return True
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=timeout)
        except TimeoutError:
            remaining = self._inflight
            labels = list(self._labels.items())
            labelled = [
                (label, self._task_issues.get(task))
                for task, label in labels[:remaining]
            ]
            for label, issue_number in labelled:
                self._record_abandoned(label, issue_number)
            for _ in range(remaining - len(labelled)):
                self._record_abandoned(None)
            logger.error(
                "Drain deadline of %.1fs passed with %d dispatch(es) still in flight; "
                "shutdown is abandoning them for reconciliation on the next start",
                timeout,
                remaining,
            )
            return False
        logger.info("Drain complete; no in-flight dispatches remain")
        return True

    @property
    def ready(self) -> bool:
        return self._is_ready and not self._is_draining

    @property
    def draining(self) -> bool:
        return self._is_draining

    @property
    def inflight(self) -> int:
        """Number of accepted dispatches that have not finished yet."""
        return self._inflight


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
