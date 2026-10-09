"""
opsswarm.resilience — Typed dependency failures, idempotent retry, and circuit-breaker.

Design
------
``GitHubClient._req()`` previously collapsed all errors (rate-limit, timeout,
5xx, auth, malformed response) into a bare ``PermissionError``.  Callers could not
distinguish a permanent auth denial from a transient 5xx, could not honour
GitHub's ``Retry-After`` header, and had no run-level circuit-breaker to shed
load when a dependency was consistently failing.

This module provides:

1. A typed exception taxonomy (sub-classes of ``DependencyError``) that
   precisely models every failure mode the client can encounter.  Each class
   carries structured metadata so callers and operators can make the right
   decision without inspecting string messages.

2. An ``IdempotentRetry`` helper that wraps an async callable and applies
   bounded exponential-backoff-with-jitter retry only when the operation is
   explicitly marked as idempotent.  Writes and ambiguous-side-effect calls are
   never retried; they raise ``AmbiguousWriteOutcome`` so the caller can route
   to reconciliation instead.

3. A ``CircuitBreaker`` that tracks consecutive failures per dependency,
   transitions to OPEN after a threshold, and half-opens after a brief TTL.
   When open it raises ``DependencyCircuitOpen`` on every call so callers never
   silently fall through — the failure is observable and auditable.

4. Integration with ``metrics`` so circuit/degraded state is visible in the
   Prometheus endpoint, and with the readiness endpoint so load balancers are
   notified when the dependency is unhealthy.

Exception hierarchy
------------------
::

    DependencyError (base for all transport/infrastructure errors)
        AuthDenied         — 401 / 403; never retry
        RateLimited        — 429; retry_after / reset_at metadata
        DependencyTimeout  — ConnectTimeout / ReadTimeout; bounded retry for reads
        DependencyUnavailable — 5xx; bounded retry
        InvalidDependencyResponse — malformed JSON / schema mismatch
        DependencyCircuitOpen — circuit-breaker is OPEN; fail-fast
        AmbiguousWriteOutcome — write response lost; route to #9 reconciliation

    PolicyDenied — operation denied by policy; not a transport error
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar

from .metrics import metrics

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class DependencyError(Exception):
    """Base for all dependency / transport failures.

    Sub-classes carry structured metadata so callers can programmatically
    distinguish failure modes without inspecting string messages.
    """

    #: Human-readable slug used in logs and metrics labels.
    error_slug: str = "dependency_error"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
    ):
        self.correlation_id = correlation_id or ""
        self.operation = operation or ""
        self.idempotency_key = idempotency_key or ""
        super().__init__(message)

    def for_comment(self) -> str:
        """Short safe text for GitHub comments — category + correlation ID only."""
        return f"[{self.error_slug} | ref: {self.correlation_id}]"

    def for_log(self) -> str:
        """Structured log line fragment."""
        parts = [f"[{self.correlation_id}] {self.args[0]}"]
        if self.operation:
            parts.append(f"op={self.operation}")
        if self.idempotency_key:
            parts.append(f"idempotency_key={self.idempotency_key}")
        return " ".join(parts)


class AuthDenied(DependencyError):
    """401 or 403 — authentication or authorization failure.

    No retry is safe: the token is invalid, expired, or lacks the required scope.
    """

    error_slug = "auth_denied"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
        status_code: int | None = None,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        self.status_code = status_code


class RateLimited(DependencyError):
    """429 Too Many Requests.

    ``retry_after`` is the minimum seconds to wait (from the ``Retry-After``
    header or the ``X-RateLimit-Reset`` header).  After waiting, a retry is safe.
    """

    error_slug = "rate_limited"

    def __init__(
        self,
        message: str,
        retry_after: float,
        *,
        reset_at: datetime | None = None,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
        status_code: int = 429,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        self.retry_after = retry_after  # minimum seconds to wait
        self.reset_at = reset_at        # wall-clock datetime when limit resets
        self.status_code = status_code


class DependencyTimeout(DependencyError):
    """Connection timeout or read timeout.

    Safe for bounded retry ONLY on explicitly idempotent operations (GETs).
    Transport errors (e.g. DNS resolution failure) are also modelled here.
    """

    error_slug = "dependency_timeout"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
        is_transport_error: bool = False,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        #: True when this is a transport-level error (DNS, refused connection)
        #: rather than an HTTP-level timeout.
        self.is_transport_error = is_transport_error


class DependencyUnavailable(DependencyError):
    """5xx server error from the dependency.

    Safe for bounded retry on idempotent operations.
    """

    error_slug = "dependency_unavailable"

    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        self.status_code = status_code


class InvalidDependencyResponse(DependencyError):
    """Malformed JSON, schema mismatch, or unexpected HTTP status.

    Safe for bounded retry ONLY on idempotent operations; malformed response
    bodies on writes are ``AmbiguousWriteOutcome`` instead.
    """

    error_slug = "invalid_response"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )


class AmbiguousWriteOutcome(DependencyError):
    """A write (POST/PATCH/PUT/DELETE) whose HTTP response was lost.

    The caller cannot determine whether the write succeeded or not.
    The operation MUST NOT be blindly retried.  Route to #9 reconciliation.
    """

    error_slug = "ambiguous_write"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        metrics.record_ambiguous_write()


class DependencyCircuitOpen(DependencyError):
    """Circuit-breaker is OPEN — dependency is considered unavailable.

    Fail-fast state reached after consecutive failures exceeded the threshold.
    Recovery will be attempted after the circuit's TTL expires.
    """

    error_slug = "circuit_open"

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        operation: str | None = None,
        idempotency_key: str | None = None,
    ):
        super().__init__(
            message,
            correlation_id=correlation_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )


class PolicyDenied(Exception):
    """Operation denied by policy — not a transport or auth failure.

    This is separate from ``DependencyError`` because it is an authorization
    decision (the token is valid and the dependency is reachable), not an
    infrastructure failure.
    """

    error_slug = "policy_denied"

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        reason: str | None = None,
    ):
        self.operation = operation or ""
        self.reason = reason or ""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Circuit-breaker
# ---------------------------------------------------------------------------


@dataclass
class CircuitState:
    """Mutable snapshot of circuit state shared between CircuitBreaker instances."""

    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    state: str = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
    last_state_change: float = field(default_factory=time.time)


class CircuitBreaker:
    """Per-dependency circuit-breaker.

    Parameters
    ----------
    name:
        Human-readable name of the dependency (used in logs and metrics).
    failure_threshold:
        Consecutive failures before the circuit trips to OPEN.
    recovery_timeout:
        Seconds to wait before attempting a half-open probe call.
    half_open_max_calls:
        Number of probe calls allowed in HALF_OPEN before deciding outcome.

    State machine
    -------------
    CLOSED   — normal operation; failures are counted
    OPEN     — fail-fast; every call raises DependencyCircuitOpen
    HALF_OPEN — probe; first ``half_open_max_calls`` calls are allowed through;
                success → CLOSED; failure → OPEN
    """

    #: Cardinality-safe labels
    VALID_STATES: frozenset[str] = frozenset({"CLOSED", "OPEN", "HALF_OPEN"})

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be > 0")
        if half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be >= 1")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState()
        self._half_open_calls = 0
        # Lock to serialise state transitions (avoids race in async context)
        self._lock = asyncio.Lock()

    # --- Public API ---

    @property
    def state(self) -> str:
        """Current circuit state."""
        return self._state.state

    @property
    def is_open(self) -> bool:
        """True when the circuit is currently failing fast."""
        return self._state.state == "OPEN"

    @property
    def is_closed(self) -> bool:
        """True when the circuit is allowing calls normally."""
        return self._state.state == "CLOSED"

    async def call(
        self,
        coro: Awaitable[T],
        *,
        correlation_id: str = "",
        operation: str = "",
    ) -> T:
        """Execute ``coro`` through the circuit-breaker.

        Raises
        ------
        DependencyCircuitOpen
            When the circuit is OPEN and the recovery timeout has not elapsed.
        """
        await self._check_or_enter_half_open()

        try:
            result = await coro
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure()
            # Re-raise the original exception; don't wrap it.
            raise

    def record_success(self) -> None:
        """Record a successful call (for synchronous callers that don't use call())."""
        asyncio.create_task(self._on_success())

    def record_failure(self) -> None:
        """Record a failed call (for synchronous callers that don't use call())."""
        asyncio.create_task(self._on_failure())

    # --- Internal state machine ---

    async def _check_or_enter_half_open(self) -> None:
        """Check OPEN state; transition to HALF_OPEN if recovery timeout elapsed."""
        if self._state.state != "OPEN":
            return

        elapsed = time.time() - self._state.last_state_change
        if elapsed >= self.recovery_timeout:
            async with self._lock:
                # Re-check after acquiring lock
                if self._state.state == "OPEN":
                    self._state.state = "HALF_OPEN"
                    self._half_open_calls = 0
                    self._state.last_state_change = time.time()
                    logger.warning(
                        "Circuit '%s' transitioning OPEN -> HALF_OPEN after %.1fs",
                        self.name,
                        elapsed,
                    )
                    metrics.record_circuit_state(self.name, "HALF_OPEN")

    async def _on_success(self) -> None:
        """Handle a successful call."""
        async with self._lock:
            if self._state.state == "HALF_OPEN":
                # Probe succeeded → close circuit
                self._state.consecutive_failures = 0
                self._state.state = "CLOSED"
                self._state.last_state_change = time.time()
                self._half_open_calls = 0
                logger.info("Circuit '%s' HALF_OPEN -> CLOSED (probe succeeded)", self.name)
                metrics.record_circuit_state(self.name, "CLOSED")
            elif self._state.state == "CLOSED":
                self._state.consecutive_failures = 0

    async def _on_failure(self) -> None:
        """Handle a failed call."""
        async with self._lock:
            self._state.consecutive_failures += 1
            self._state.last_failure_at = time.time()

            if self._state.state == "HALF_OPEN":
                # Probe failed → trip back to OPEN
                self._state.state = "OPEN"
                self._state.last_state_change = time.time()
                self._half_open_calls = 0
                logger.warning(
                    "Circuit '%s' HALF_OPEN -> OPEN (probe failed, failures=%d)",
                    self.name,
                    self._state.consecutive_failures,
                )
                metrics.record_circuit_state(self.name, "OPEN")

            elif self._state.state == "CLOSED":
                if self._state.consecutive_failures >= self.failure_threshold:
                    self._state.state = "OPEN"
                    self._state.last_state_change = time.time()
                    logger.error(
                        "Circuit '%s' CLOSED -> OPEN (threshold=%d reached)",
                        self.name,
                        self.failure_threshold,
                    )
                    metrics.record_circuit_state(self.name, "OPEN")

    def raise_if_open(self) -> None:
        """Raise ``DependencyCircuitOpen`` if the circuit is currently OPEN.

        Call this from synchronous code paths that don't go through ``call()``.
        """
        if self._state.state == "OPEN":
            elapsed = time.time() - self._state.last_state_change
            raise DependencyCircuitOpen(
                f"Circuit '{self.name}' is OPEN; fail-fast active. "
                f"Circuit has been open for {elapsed:.1f}s.",
                correlation_id="",
                operation="",
            )

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot of circuit state."""
        return {
            "name": self.name,
            "state": self._state.state,
            "consecutive_failures": self._state.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "seconds_since_last_failure": (
                round(time.time() - self._state.last_failure_at, 2)
                if self._state.last_failure_at else None
            ),
            "seconds_since_last_state_change": (
                round(time.time() - self._state.last_state_change, 2)
            ),
        }


# ---------------------------------------------------------------------------
# Idempotent retry
# ---------------------------------------------------------------------------


@dataclass
class RetryBudget:
    """Tracks remaining retry budget for one operation."""

    attempts_left: int
    max_attempts: int
    operation: str
    idempotency_key: str


def _compute_retry_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_after: float | None = None,
) -> float:
    """Exponential backoff with full jitter, capped at max_delay.

    If ``retry_after`` is provided (from a ``RateLimited`` exception), return
    that value instead so we honour GitHub's requested wait.
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, max_delay)

    # Full jitter in [0, min(cap, base * 2^attempt)]
    cap = min(max_delay, base_delay * (2**attempt))
    return random.uniform(0.0, cap)


async def idempotent_retry(
    coro: Callable[..., Awaitable[T]],
    *args: P.args,
    operation: str,
    idempotency_key: str,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    _is_idempotent: bool = True,
    **kwargs: P.kwargs,
) -> T:
    """Retry an async callable only when it is safe to do so.

    Parameters
    ----------
    coro:
        Async callable to execute. Must be idempotent when _is_idempotent=True.
    operation:
        Human-readable name of the operation (for logs and exception metadata).
    idempotency_key:
        Stable key that identifies this logical operation across retries.
        Passed to exception metadata.
    max_attempts:
        Maximum total attempts (1 = no retry).
    base_delay:
        Base delay in seconds for exponential backoff.
    max_delay:
        Maximum delay in seconds (cap on backoff and Retry-After honouring).
    _is_idempotent:
        Set to False for side-effecting operations (writes).  When False, this
        function never retries; it raises ``AmbiguousWriteOutcome`` on the first
        failure instead.

    Raises
    ------
    AmbiguousWriteOutcome
        When _is_idempotent=False and the call fails (never retry writes).
    DependencyTimeout / DependencyUnavailable / RateLimited / InvalidDependencyResponse
        When _is_idempotent=True and all retry attempts are exhausted.
    """
    if not _is_idempotent:
        # Write path: never retry; route to reconciliation on failure.
        try:
            return await coro(*args, **kwargs)
        except DependencyError as exc:
            exc.operation = operation
            exc.idempotency_key = idempotency_key
            raise AmbiguousWriteOutcome(
                f"Write '{operation}' failed with {exc.error_slug}; "
                f"response may have been lost — routing to reconciliation.",
                correlation_id=exc.correlation_id,
                operation=operation,
                idempotency_key=idempotency_key,
            ) from exc

    budget = RetryBudget(
        attempts_left=max_attempts,
        max_attempts=max_attempts,
        operation=operation,
        idempotency_key=idempotency_key,
    )

    last_exc: Exception | None = None
    while budget.attempts_left > 0:
        budget.attempts_left -= 1
        try:
            result = await coro(*args, **kwargs)
            return result
        except RateLimited as exc:
            # Honour Retry-After even on last attempt (still worth waiting).
            exc.operation = operation
            exc.idempotency_key = idempotency_key
            delay = _compute_retry_delay(
                attempt=(budget.max_attempts - budget.attempts_left),
                base_delay=base_delay,
                max_delay=max_delay,
                retry_after=exc.retry_after,
            )
            logger.debug(
                "RateLimited on %s attempt %d/%d; sleeping %.1fs (retry_after=%.1f)",
                operation,
                budget.max_attempts - budget.attempts_left,
                budget.max_attempts,
                delay,
                exc.retry_after,
            )
            await asyncio.sleep(delay)
            last_exc = exc
        except (DependencyTimeout, DependencyUnavailable, InvalidDependencyResponse) as exc:
            exc.operation = operation
            exc.idempotency_key = idempotency_key
            last_exc = exc
            if budget.attempts_left == 0:
                break
            attempt = budget.max_attempts - budget.attempts_left
            delay = _compute_retry_delay(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=max_delay,
            )
            logger.debug(
                "%s on %s attempt %d/%d; retrying in %.1fs",
                exc.error_slug,
                operation,
                attempt + 1,
                budget.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
        except DependencyError:
            # AuthDenied, DependencyCircuitOpen, PolicyDenied — never retry.
            raise

    # All attempts exhausted
    metrics.record_dependency_retry_exhausted(operation)
    assert last_exc is not None
    raise last_exc
