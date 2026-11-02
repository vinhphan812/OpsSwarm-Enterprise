"""
opsswarm.resilience — Typed dependency failures, bounded retry and circuit-breaker.

Design
------
``GitHubClient._req()`` previously collapsed every failure mode (auth denial,
rate limiting, timeout, 5xx, malformed response, lost write response) into a
bare ``PermissionError``.  Callers could not distinguish a permanent
authorization denial from a transient 5xx, could not honour GitHub's
``Retry-After`` metadata, and had no dependency-health policy to shed load
while a dependency was failing.

This module provides:

1. A typed failure taxonomy (sub-classes of :class:`DependencyError`) that
   models every failure mode the client can encounter.  Each class carries
   structured metadata so callers and operators can decide programmatically
   instead of parsing strings.

2. A bounded, idempotency-aware retry policy (:class:`RetryPolicy`) with
   exponential backoff + bounded jitter.  Only demonstrably idempotent reads
   are ever retried; potentially side-effecting writes are never retried
   automatically.

3. A per-dependency circuit-breaker (:class:`CircuitBreaker`) that opens after
   a run of *dependency* failures (timeout / 5xx / lost transport) and
   fail-fasts while open.  Ordinary client errors (401/403/404/409/422 …) are
   **not** dependency failures and never move the circuit.

4. Metric instrumentation that preserves the documented metric contract
   (see ``docs/OPERATIONS.md``) with bounded label cardinality.

Failure taxonomy
----------------
The slugs below are the published operator-facing taxonomy — they are a
public contract and must not be renamed:

======================  ====================================================
slug                    cause
======================  ====================================================
``auth_denied``         401, or 403 without rate-limit evidence
``rate_limited``        429, or 403 *with* GitHub rate-limit evidence
``dependency_timeout``  connect / read / write timeout
``dependency_unavailable``  5xx, or transport-level failure
``invalid_response``    4xx (non-auth), redirect, malformed body
``ambiguous_write``     write whose outcome is unknown (transport loss)
``circuit_open``        circuit fail-fast state
======================  ====================================================

Compatibility note
------------------
:class:`DependencyError` derives from ``PermissionError`` so that existing
``except PermissionError`` handlers (``opsswarm/api.py``,
``opsswarm/orchestrator.py``) keep working unchanged.  The failures are *not*
collapsed: each category is a distinct type with a distinct slug and distinct
structured metadata, so callers can discriminate precisely while legacy
callers still catch the family.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from .metrics import metrics

logger = logging.getLogger(__name__)

__all__ = [
    "AmbiguousWriteOutcome",
    "AuthDenied",
    "CircuitBreaker",
    "DependencyError",
    "DependencyTimeout",
    "DependencyUnavailable",
    "InvalidDependencyResponse",
    "RateLimited",
    "RetryPolicy",
    "classify_http_error",
    "classify_transport_error",
    "normalize_operation",
    "parse_retry_after",
]


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class DependencyError(PermissionError):
    """Base class for every typed dependency failure.

    Derives from ``PermissionError`` for backward compatibility with existing
    ``except PermissionError`` handlers; the concrete subclass carries the
    precise category.
    """

    #: Published operator-facing slug (public contract).
    error_slug: str = "dependency_error"

    #: True when retrying the *same* request could plausibly succeed.
    retryable: bool = False

    #: True when the outcome of the operation is unknown, so the caller must
    #: reconcile against real remote state instead of retrying.
    ambiguous: bool = False

    #: True when this failure counts as a dependency outage for the
    #: circuit-breaker.  Ordinary client errors (4xx) do **not**.
    counts_toward_circuit: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        operation: str = "",
        retry_after: float | None = None,
        reset_at: datetime | None = None,
        correlation_id: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation
        self.retry_after = retry_after
        self.reset_at = reset_at
        self.correlation_id = correlation_id

    def for_comment(self) -> str:
        """Category + correlation ID only — safe to post to a GitHub comment."""
        return f"[{self.error_slug} | ref: {self.correlation_id or 'n/a'}]"

    def for_log(self) -> str:
        """Redacted single-line log fragment."""
        parts = [f"[{self.correlation_id or 'n/a'}]", str(self.args[0])]
        if self.operation:
            parts.append(f"op={self.operation}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        return " ".join(parts)


class AuthDenied(DependencyError):
    """401, or 403 without evidence of GitHub throttling.

    Never retried: the token is invalid, expired, or lacks the required scope.
    """

    error_slug = "auth_denied"
    retryable = False
    counts_toward_circuit = False


class RateLimited(DependencyError):
    """429, or 403 that carries GitHub rate-limit / secondary-rate-limit evidence.

    ``retry_after`` is the minimum number of seconds GitHub asked us to wait
    (from ``Retry-After`` or ``X-RateLimit-Reset``).  ``reset_at`` is the
    wall-clock reset time when it could be derived.
    """

    error_slug = "rate_limited"
    retryable = True
    counts_toward_circuit = False


class DependencyTimeout(DependencyError):
    """Connect / read / write timeout against the dependency."""

    error_slug = "dependency_timeout"
    retryable = True
    counts_toward_circuit = True


class DependencyUnavailable(DependencyError):
    """5xx response, or a transport-level failure that is not a timeout."""

    error_slug = "dependency_unavailable"
    retryable = True
    counts_toward_circuit = True


class InvalidDependencyResponse(DependencyError):
    """Non-auth 4xx, redirect, or a malformed/undecodable response body.

    Terminal: retrying the same request cannot change the outcome.
    """

    error_slug = "invalid_response"
    retryable = False
    counts_toward_circuit = False


class AmbiguousWriteOutcome(DependencyError):
    """A side-effecting write whose outcome could not be determined.

    The request may or may not have been applied.  It must never be retried
    automatically — the caller has to reconcile against the real remote state.
    """

    error_slug = "ambiguous_write"
    retryable = False
    counts_toward_circuit = True
    #: Callers must reconcile against real remote state before touching the
    #: same target again.  Published for orchestration layers that have to
    #: distinguish "denied" from "unknown".
    ambiguous = True

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(
            f"{message} — outcome unknown; reconcile remote state, do not retry this write",
            **kwargs,
        )
        # Ambiguous writes are the canonical "we do not know" signal and are
        # surfaced through the documented ambiguous-write metric.
        metrics.record_ambiguous_write()


class DependencyCircuitOpen(DependencyError):
    """The dependency circuit is open — calls fail fast until the TTL elapses."""

    error_slug = "circuit_open"
    retryable = False
    counts_toward_circuit = False


# ---------------------------------------------------------------------------
# Operation labels (bounded cardinality)
# ---------------------------------------------------------------------------

#: Path segments that are fixed GitHub API vocabulary.  Anything else in a
#: path is variable (issue numbers, SHAs, usernames, branch names) and is
#: replaced by a placeholder so metric labels stay bounded.
_PATH_KEYWORDS: frozenset[str] = frozenset(
    {
        "assignees",
        "blobs",
        "branches",
        "check-runs",
        "collaborators",
        "comments",
        "compare",
        "commits",
        "contents",
        "git",
        "heads",
        "issues",
        "labels",
        "merge",
        "milestones",
        "permission",
        "pulls",
        "releases",
        "repos",
        "statuses",
        "tags",
        "trees",
    }
)

_OPERATION_MAX_LEN = 120
_OPERATION_SAFE_RE = re.compile(r"[^A-Za-z0-9:_./{}|-]")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def normalize_operation(method: str, path: str) -> str:
    """Return a bounded, cardinality-safe operation label.

    The label has the shape ``"<METHOD>:/repos/{repo}/issues/{number}"``.
    Variable path segments (numbers, SHAs, names) are collapsed to
    placeholders so the label set stays small and can never be influenced by
    attacker-controlled values.
    """
    verb = (method or "UNKNOWN").upper()[:8]
    segments = [s for s in (path or "").split("/") if s]
    normalised: list[str] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if segment == "repos" and index + 2 < len(segments):
            # owner/repo collapse into a single placeholder.
            normalised.append("repos")
            normalised.append("{repo}")
            index += 3
            continue
        if segment.isdigit():
            normalised.append("{number}")
        elif _SHA_RE.match(segment):
            normalised.append("{sha}")
        elif segment in _PATH_KEYWORDS:
            normalised.append(segment)
        else:
            normalised.append("{name}")
        index += 1
    template = "/" + "/".join(normalised) if normalised else "/"
    label = f"{verb}:{template}"
    label = _OPERATION_SAFE_RE.sub("_", label)
    return label[:_OPERATION_MAX_LEN]


# ---------------------------------------------------------------------------
# Rate-limit metadata
# ---------------------------------------------------------------------------


def _header_value(headers: Any, name: str) -> str | None:
    """Return a header value only when it is a real string.

    Guards against non-string header containers (e.g. test doubles) silently
    masquerading as rate-limit evidence.
    """
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    try:
        value = getter(name)
    except Exception:  # pragma: no cover - defensive: exotic header containers
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_retry_after(headers: Any, *, now: datetime | None = None) -> tuple[float | None, datetime | None]:
    """Derive ``(retry_after_seconds, reset_at)`` from GitHub headers.

    Honours ``Retry-After`` (delta-seconds or HTTP-date) and
    ``X-RateLimit-Reset`` (epoch seconds).  Returns ``(None, None)`` when the
    headers carry no usable information.

    Non-finite values (``nan``, ``inf``, ``1e400``) and epochs outside the
    representable range are rejected: they are not a wait instruction, and
    feeding them to ``timedelta``/``fromtimestamp`` would raise instead of
    degrading to the local backoff schedule.
    """
    now = now or datetime.now(timezone.utc)
    retry_after = _header_value(headers, "retry-after")
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = None
        if seconds is not None and math.isfinite(seconds) and seconds >= 0:
            return seconds, now + timedelta(seconds=seconds)

    reset = _header_value(headers, "x-ratelimit-reset")
    if reset is not None:
        try:
            epoch = float(reset)
        except ValueError:
            epoch = None
        if epoch is not None and math.isfinite(epoch):
            try:
                reset_at = datetime.fromtimestamp(epoch, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None, None
            delta = (reset_at - now).total_seconds()
            return max(delta, 0.0), reset_at
    return None, None


_RATE_LIMIT_BODY_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate-limit",
    "ratelimit",
    "secondary rate limit",
    "abuse detection",
    "too many requests",
)


def _has_rate_limit_evidence(headers: Any, body: str) -> bool:
    """Return True only when GitHub itself proved the 403 was throttling.

    Evidence sources:
    - ``X-RateLimit-Remaining: 0`` (primary limit exhausted)
    - a ``Retry-After`` header (secondary limit / abuse detection)
    - an explicit rate-limit / secondary-rate-limit message in the body

    An ordinary "forbidden" / "resource not accessible" 403 carries none of
    these and stays a terminal :class:`AuthDenied`.
    """
    remaining = _header_value(headers, "x-ratelimit-remaining")
    if remaining is not None:
        try:
            if int(remaining) <= 0:
                return True
        except ValueError:
            pass
    if _header_value(headers, "retry-after") is not None:
        return True
    lowered = (body or "").lower()
    return any(marker in lowered for marker in _RATE_LIMIT_BODY_MARKERS)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_http_error(
    response: Any,
    *,
    method: str,
    path: str,
    operation: str = "",
) -> DependencyError:
    """Map an HTTP error response onto the typed taxonomy.

    ``response`` may be an ``httpx.Response`` or any object exposing
    ``status_code`` / ``headers`` / ``text``.
    """
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        status = 0
    headers = getattr(response, "headers", None)
    body = getattr(response, "text", "") or ""
    if not isinstance(body, str):
        body = ""
    message = f"GitHub API returned {status} for {method} {path}"

    if status == 401:
        return AuthDenied(message, status_code=status, operation=operation)

    if status == 403:
        if _has_rate_limit_evidence(headers, body):
            retry_after, reset_at = parse_retry_after(headers)
            return RateLimited(
                message,
                status_code=status,
                operation=operation,
                retry_after=retry_after,
                reset_at=reset_at,
            )
        return AuthDenied(message, status_code=status, operation=operation)

    if status == 429:
        retry_after, reset_at = parse_retry_after(headers)
        return RateLimited(
            message,
            status_code=status,
            operation=operation,
            retry_after=retry_after,
            reset_at=reset_at,
        )

    if 500 <= status <= 599:
        return DependencyUnavailable(message, status_code=status, operation=operation)

    if 300 <= status <= 399:
        # Redirects are never followed (ADR-028) and must stay blocked.
        return InvalidDependencyResponse(
            f"GitHub API returned a redirect ({status}) for {method} {path}",
            status_code=status,
            operation=operation,
        )

    # Any other 4xx (404, 409, 422, …) is a known rejection: the request was
    # refused by the server, so the outcome is *known* and not ambiguous.
    return InvalidDependencyResponse(message, status_code=status, operation=operation)


def classify_transport_error(
    exc: BaseException,
    *,
    method: str,
    path: str,
    operation: str = "",
    is_write: bool = False,
) -> DependencyError:
    """Map a transport-level exception onto the typed taxonomy.

    Connect-phase failures (DNS, refused connection, connect timeout) mean the
    request was never delivered — the outcome is *known* (nothing happened).
    Failures after the request left the process (read timeout, protocol /
    network error while reading the response) mean the outcome is *unknown*:
    for a side-effecting write that is an :class:`AmbiguousWriteOutcome`.
    """
    message = f"GitHub API request failed for {method} {path}"
    if is_write and _may_have_been_delivered(exc):
        return AmbiguousWriteOutcome(
            f"GitHub API write outcome is unknown for {method} {path}",
            operation=operation,
        )
    if isinstance(exc, httpx.TimeoutException):
        return DependencyTimeout(message, operation=operation)
    return DependencyUnavailable(message, operation=operation)


def _may_have_been_delivered(exc: BaseException) -> bool:
    """True when the request may have reached the dependency.

    Connect-phase failures (DNS failure, refused connection, connect timeout)
    provably never delivered the request, so the outcome is *known* — nothing
    happened.  Everything else (read timeout, protocol error, connection reset
    while reading the response) may have been applied.
    """
    if isinstance(exc, httpx.ConnectError):
        return False
    if isinstance(exc, httpx.ConnectTimeout):
        return False
    if isinstance(exc, httpx.PoolTimeout):
        return False
    return True


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for demonstrably idempotent reads.

    Attributes
    ----------
    max_attempts:
        Total attempts (including the first) for a retried operation.
        ``1`` disables retrying.
    base_delay:
        Base backoff delay in seconds.
    max_delay:
        Upper bound for any single sleep (also caps ``Retry-After``).
    jitter_ratio:
        Fraction of the computed delay that is randomised, in ``[0, 1]``.
        The delay is always at least ``(1 - jitter_ratio)`` of the base value
        so it stays bounded and non-zero.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter_ratio: float = 0.5
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0:
            raise ValueError("base_delay must be >= 0")
        if self.max_delay < 0:
            raise ValueError("max_delay must be >= 0")
        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be within [0, 1]")

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """Return the bounded, jittered delay before ``attempt`` + 1.

        ``attempt`` is 1-based (the attempt that just failed).  When GitHub
        supplied ``retry_after`` metadata that value wins, capped at
        ``max_delay`` — honouring the server is always preferable to our own
        backoff schedule.
        """
        if retry_after is not None and math.isfinite(retry_after) and retry_after > 0:
            return min(float(retry_after), self.max_delay)
        exponent = max(attempt - 1, 0)
        raw = self.base_delay * (2**exponent)
        capped = min(raw, self.max_delay)
        if capped <= 0:
            return 0.0
        jitter_span = capped * self.jitter_ratio
        floor = capped - jitter_span
        return floor + random.uniform(0.0, jitter_span)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Per-dependency circuit-breaker.

    State machine
    -------------
    ``CLOSED``    normal operation; dependency failures are counted.
    ``OPEN``      fail fast; every call raises :class:`DependencyCircuitOpen`
                  until ``recovery_timeout`` elapses.
    ``HALF_OPEN`` a single probe call is admitted; success closes the circuit,
                  failure re-opens it.

    Only failures flagged ``counts_toward_circuit`` (timeout / 5xx / lost
    transport) move the circuit.  Ordinary client errors are *not* dependency
    failures and never open the circuit.
    """

    VALID_STATES: frozenset[str] = frozenset({"CLOSED", "OPEN", "HALF_OPEN"})

    def __init__(
        self,
        name: str,
        *,
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

        self._state = "CLOSED"
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    # -- introspection ----------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def is_open(self) -> bool:
        return self._state == "OPEN"

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }

    # -- state machine ----------------------------------------------------

    async def acquire(self, *, operation: str = "") -> bool:
        """Admit a call, or raise :class:`DependencyCircuitOpen`.

        Returns ``True`` when the call consumed the single HALF_OPEN probe
        slot.  The caller must hand that slot back through
        :meth:`release_probe` if the probe finishes without a verdict for the
        circuit (a terminal client error, a malformed body, or cancellation);
        otherwise a healthy dependency stays wedged in HALF_OPEN and every
        later call fails fast forever.
        """
        async with self._lock:
            if self._state == "OPEN":
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    self._half_open_calls = 0
                    metrics.record_circuit_state(self.name, "HALF_OPEN")
                    logger.warning(
                        "Circuit '%s' OPEN -> HALF_OPEN after %.1fs", self.name, elapsed
                    )
                else:
                    raise DependencyCircuitOpen(
                        f"Dependency circuit '{self.name}' is open; fail-fast active.",
                        operation=operation,
                    )
            if self._state == "HALF_OPEN":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise DependencyCircuitOpen(
                        f"Dependency circuit '{self.name}' is half-open and probing.",
                        operation=operation,
                    )
                self._half_open_calls += 1
                return True
            return False

    def release_probe(self) -> None:
        """Return a HALF_OPEN probe slot when the probe reached no verdict.

        Deliberately synchronous: it is called from ``finally`` blocks,
        including ones that run while the task is being cancelled, where an
        ``await`` could itself be cancelled and leak the slot.
        """
        if self._state != "HALF_OPEN":
            return
        if self._half_open_calls > 0:
            self._half_open_calls -= 1

    async def record_success(self) -> None:
        """Record a reachable dependency (closes a half-open circuit)."""
        async with self._lock:
            self._consecutive_failures = 0
            if self._state != "CLOSED":
                self._state = "CLOSED"
                self._half_open_calls = 0
                metrics.record_circuit_state(self.name, "CLOSED")
                logger.info("Circuit '%s' HALF_OPEN -> CLOSED (probe succeeded)", self.name)

    async def record_failure(self) -> None:
        """Record a dependency failure and open the circuit when warranted."""
        async with self._lock:
            self._consecutive_failures += 1
            if self._state == "HALF_OPEN":
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                self._half_open_calls = 0
                metrics.record_circuit_state(self.name, "OPEN")
                logger.warning("Circuit '%s' HALF_OPEN -> OPEN (probe failed)", self.name)
            elif self._state == "CLOSED" and self._consecutive_failures >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.monotonic()
                metrics.record_circuit_state(self.name, "OPEN")
                logger.error(
                    "Circuit '%s' CLOSED -> OPEN (consecutive failures=%d)",
                    self.name,
                    self._consecutive_failures,
                )
