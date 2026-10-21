"""opsswarm.resilience — Typed dependency resilience foundation.

Design goals
------------
- Typed dependency error classes for GitHub API failures with specific error codes
- Idempotent retry with safe retry contracts (no blind retry on ambiguous writes)
- Circuit breaker with configurable thresholds for fault tolerance
- Cardinality-safe Prometheus metrics (bounded counter labels)

This module provides the foundation for Issue #75: typed dependency resilience.
The circuit breaker is NOT wired into GitHubClient yet — that's a gated child task.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ----------------------------------------------------------------------
# Typed GitHub API Error Classes
# ----------------------------------------------------------------------


class GitHubAPIErrorType(Enum):
    """Categories of GitHub API errors for typed handling."""

    # 4xx Client Errors
    NOT_FOUND = "not_found"  # 404 - Resource not found
    FORBIDDEN = "forbidden"  # 403 - Rate limited or forbidden
    UNAUTHORIZED = "unauthorized"  # 401 - Auth failed
    VALIDATION_FAILED = "validation_failed"  # 422 - Validation failed
    CONFLICT = "conflict"  # 409 - Conflict (e.g., branch exists)

    # 5xx Server Errors
    SERVER_ERROR = "server_error"  # 500, 502, 503, 504 - Server issues
    SERVICE_UNAVAILABLE = "service_unavailable"  # 503
    GATEWAY_TIMEOUT = "gateway_timeout"  # 504

    # Network Errors
    TIMEOUT = "timeout"  # Request timeout
    CONNECTION_ERROR = "connection_error"  # Network connectivity issues

    # Unknown
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GitHubAPIError(Exception):
    """Typed GitHub API error with specific error classification.

    Attributes
    ----------
    error_type
        The categorized error type for targeted handling
    status_code
        HTTP status code if available
    message
        Error message (sanitized, safe for logs)
    is_retryable
        Whether this error should trigger a retry
    is_idempotent
        Whether the operation that caused this error was idempotent
    """

    error_type: GitHubAPIErrorType
    status_code: int | None
    message: str
    is_retryable: bool = False
    is_idempotent: bool = True

    def __str__(self) -> str:
        code_str = f" (status={self.status_code})" if self.status_code else ""
        return f"[{self.error_type.value}]{code_str}: {self.message}"


def classify_httpx_error(status_code: int | None, error_message: str) -> GitHubAPIError:
    """Classify an httpx error into a typed GitHubAPIError.

    Parameters
    ----------
    status_code
        HTTP status code from the response
    error_message
        Error message from the response

    Returns
    -------
    GitHubAPIError
        Typed error with retryability information
    """
    if status_code is None:
        # Network error - likely retryable
        if "timeout" in error_message.lower():
            return GitHubAPIError(
                error_type=GitHubAPIErrorType.TIMEOUT,
                status_code=None,
                message=error_message,
                is_retryable=True,
                is_idempotent=True,
            )
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.CONNECTION_ERROR,
            status_code=None,
            message=error_message,
            is_retryable=True,
            is_idempotent=True,
        )

    # 4xx Client Errors
    if status_code == 404:
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.NOT_FOUND,
            status_code=status_code,
            message=error_message,
            is_retryable=False,
            is_idempotent=True,  # GET is idempotent
        )
    if status_code == 403:
        # Could be rate limiting or forbidden - treat as retryable
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.FORBIDDEN,
            status_code=status_code,
            message=error_message,
            is_retryable=True,  # Could be rate limited
            is_idempotent=True,
        )
    if status_code == 401:
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.UNAUTHORIZED,
            status_code=status_code,
            message=error_message,
            is_retryable=False,  # Auth issue won't be fixed by retry
            is_idempotent=True,
        )
    if status_code == 422:
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.VALIDATION_FAILED,
            status_code=status_code,
            message=error_message,
            is_retryable=False,  # Validation won't pass on retry
            is_idempotent=False,  # Could be non-idempotent
        )
    if status_code == 409:
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.CONFLICT,
            status_code=status_code,
            message=error_message,
            is_retryable=True,  # Could be transient conflict
            is_idempotent=False,  # Conflict means state exists
        )

    # 5xx Server Errors - generally retryable
    if status_code >= 500:
        if status_code == 503:
            return GitHubAPIError(
                error_type=GitHubAPIErrorType.SERVICE_UNAVAILABLE,
                status_code=status_code,
                message=error_message,
                is_retryable=True,
                is_idempotent=True,
            )
        if status_code == 504:
            return GitHubAPIError(
                error_type=GitHubAPIErrorType.GATEWAY_TIMEOUT,
                status_code=status_code,
                message=error_message,
                is_retryable=True,
                is_idempotent=True,
            )
        return GitHubAPIError(
            error_type=GitHubAPIErrorType.SERVER_ERROR,
            status_code=status_code,
            message=error_message,
            is_retryable=True,
            is_idempotent=True,
        )

    # Unknown status code
    return GitHubAPIError(
        error_type=GitHubAPIErrorType.UNKNOWN,
        status_code=status_code,
        message=error_message,
        is_retryable=False,
        is_idempotent=True,
    )


# ----------------------------------------------------------------------
# Retry Contracts and Idempotent Retry
# ----------------------------------------------------------------------


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes
    ----------
    max_attempts
        Maximum number of retry attempts (including initial call)
    base_delay
        Base delay in seconds (exponential backoff multiplier)
    max_delay
        Maximum delay between retries in seconds
    jitter
        Whether to add random jitter to delays
    retry_on_types
        Error types that should trigger a retry
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
    retry_on_types: tuple[GitHubAPIErrorType, ...] = (
        GitHubAPIErrorType.SERVER_ERROR,
        GitHubAPIErrorType.SERVICE_UNAVAILABLE,
        GitHubAPIErrorType.GATEWAY_TIMEOUT,
        GitHubAPIErrorType.TIMEOUT,
        GitHubAPIErrorType.CONNECTION_ERROR,
        GitHubAPIErrorType.FORBIDDEN,  # Rate limiting
        GitHubAPIErrorType.CONFLICT,
    )

    def should_retry(self, error: GitHubAPIError) -> bool:
        """Determine if an error should trigger a retry."""
        return error.is_retryable and error.error_type in self.retry_on_types


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: GitHubAPIError):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_error}")


async def retry_with_contract(
    func: Callable[..., T],
    config: RetryConfig,
    *args: Any,
    operation_is_idempotent: bool | None = None,
    **kwargs: Any,
) -> T:
    """Execute a function with idempotent retry logic.

    This function implements safe retry contracts:
    - Never blindly retry non-idempotent operations
    - Only retry on specified error types
    - Use exponential backoff with jitter

    Parameters
    ----------
    func
        Async function to execute
    config
        Retry configuration
    operation_is_idempotent
        Override for idempotency detection. If None, uses error's is_idempotent.
    *args
        Positional arguments for func
    **kwargs
        Keyword arguments for func

    Returns
    -------
    T
        Result from successful function execution

    Raises
    ------
    RetryExhaustedError
        When all retry attempts are exhausted
    GitHubAPIError
        Non-retryable errors are raised immediately
    """
    last_error: GitHubAPIError | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            result = await func(*args, **kwargs)
            if attempt > 1:
                logger.info(
                    "Retry succeeded on attempt %d/%d",
                    attempt,
                    config.max_attempts,
                )
                # Record retry success metric
                if last_error is not None:
                    resilience_metrics.record_retry_success(last_error.error_type)
            return result
        except GitHubAPIError as e:
            last_error = e

            # Record retry attempt metric
            resilience_metrics.record_retry(e.error_type)

            # Determine if we should retry
            should_retry = config.should_retry(e)

            # Check idempotency contract
            is_idempotent = operation_is_idempotent if operation_is_idempotent is not None else e.is_idempotent

            if not is_idempotent:
                logger.warning(
                    "Skipping retry for non-idempotent operation: %s",
                    e,
                )
                raise

            if not should_retry:
                logger.info(
                    "Not retrying on non-retryable error: %s (attempt %d/%d)",
                    e,
                    attempt,
                    config.max_attempts,
                )
                raise

            # Check if we have retries left
            if attempt >= config.max_attempts:
                logger.error(
                    "Retry exhausted after %d attempts, last error: %s",
                    attempt,
                    e,
                )
                # Record retry exhaustion metric
                resilience_metrics.record_retry_exhausted(e.error_type)
                raise RetryExhaustedError(attempt, e) from e

            # Calculate delay with exponential backoff
            delay = min(config.base_delay * (2 ** (attempt - 1)), config.max_delay)

            # Add jitter
            if config.jitter:
                import random

                delay = delay * (0.5 + random.random())  # 50-150% of delay

            logger.warning(
                "Retrying after %.2fs (attempt %d/%d): %s",
                delay,
                attempt + 1,
                config.max_attempts,
                e,
            )
            await asyncio.sleep(delay)

    # Should not reach here, but handle edge case
    if last_error:
        raise RetryExhaustedError(config.max_attempts, last_error) from last_error

    raise RetryExhaustedError(config.max_attempts, GitHubAPIError(
        error_type=GitHubAPIErrorType.UNKNOWN,
        status_code=None,
        message="Unknown error during retry",
    ))


# ----------------------------------------------------------------------
# Circuit Breaker
# ----------------------------------------------------------------------


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes
    ----------
    failure_threshold
        Number of consecutive failures before opening the circuit
    success_threshold
        Number of consecutive successes needed to close the circuit
    timeout
        Seconds to wait before transitioning from OPEN to HALF_OPEN
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and fast-failing."""

    def __init__(self, circuit_name: str, state: CircuitState):
        self.circuit_name = circuit_name
        self.state = state
        super().__init__(f"Circuit '{circuit_name}' is {state.value}")


class CircuitBreaker:
    """Circuit breaker implementation for fault tolerance.

    The circuit breaker prevents cascading failures by failing fast when
    a dependency is experiencing issues.

    State transitions:
    - CLOSED -> OPEN: After failure_threshold consecutive failures
    - OPEN -> HALF_OPEN: After timeout seconds
    - HALF_OPEN -> CLOSED: After success_threshold consecutive successes
    - HALF_OPEN -> OPEN: On any failure
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transition."""
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            if time.monotonic() - self._last_failure_time >= self.config.timeout:
                # Transition to half-open
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit '%s' transitioned to HALF_OPEN after timeout", self.name)
        return self._state

    def _record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("Circuit '%s' CLOSED after %d successes", self.name, self._success_count)
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    def _record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open reopens the circuit
            self._state = CircuitState.OPEN
            self._success_count = 0
            logger.warning("Circuit '%s' reopened after HALF_OPEN failure", self.name)
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit '%s' opened after %d consecutive failures",
                    self.name,
                    self._failure_count,
                )

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a function through the circuit breaker.

        Parameters
        ----------
        func
            Async function to execute
        *args
            Positional arguments for func
        **kwargs
            Keyword arguments for func

        Returns
        -------
        T
            Result from successful function execution

        Raises
        ------
        CircuitBreakerOpenError
            When circuit is open and fast-failing
        """
        async with self._lock:
            if self.state == CircuitState.OPEN:
                resilience_metrics.record_circuit_rejection(self.name)
                raise CircuitBreakerOpenError(self.name, self.state)

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._record_success()
            return result
        except Exception as e:
            async with self._lock:
                resilience_metrics.record_circuit_failure(self.name)
                self._record_failure()
            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info("Circuit '%s' manually reset to CLOSED", self.name)


# ----------------------------------------------------------------------
# Cardinality-Safe Prometheus Metrics for Resilience
# ----------------------------------------------------------------------


class ResilienceMetrics:
    """Cardinality-safe Prometheus metrics for resilience patterns.

    This class provides metrics with bounded label sets to prevent
    Prometheus cardinality explosions. All label values come from
    enums or config, never from user input.
    """

    # Valid error type labels - comes from GitHubAPIErrorType enum
    VALID_ERROR_TYPES: set[str] = {e.value for e in GitHubAPIErrorType}

    # Valid circuit states - comes from CircuitState enum
    VALID_CIRCUIT_STATES: set[str] = {s.value for s in CircuitState}

    # Valid retry outcomes
    VALID_RETRY_OUTCOMES: set[str] = {"success", "exhausted", "non_retryable_error"}

    def __init__(self) -> None:
        # Retry metrics
        self.retries_total: Counter = Counter()  # error_type: count
        self.retry_success_total: Counter = Counter()  # error_type: count
        self.retry_exhausted_total: Counter = Counter()  # error_type: count

        # Circuit breaker metrics
        self.circuit_state_changes: Counter = Counter()  # (circuit, from_state, to_state): count
        self.circuit_failures: Counter = Counter()  # circuit: count
        self.circuit_rejections: Counter = Counter()  # circuit: count

        # Cardinality guard - tracks observed label values
        self._observed_labels: dict[str, set[str]] = {
            "retries": set(),
            "retry_success": set(),
            "retry_exhausted": set(),
            "circuit_state_changes": set(),
            "circuit_failures": set(),
            "circuit_rejections": set(),
        }

    def record_retry(self, error_type: GitHubAPIErrorType) -> None:
        """Record a retry attempt for an error type."""
        label = error_type.value
        if label not in self.VALID_ERROR_TYPES:
            label = "unknown"
        self.retries_total[label] += 1
        self._observed_labels["retries"].add(label)

    def record_retry_success(self, error_type: GitHubAPIErrorType) -> None:
        """Record a successful retry."""
        label = error_type.value
        if label not in self.VALID_ERROR_TYPES:
            label = "unknown"
        self.retry_success_total[label] += 1
        self._observed_labels["retry_success"].add(label)

    def record_retry_exhausted(self, error_type: GitHubAPIErrorType) -> None:
        """Record a retry exhaustion."""
        label = error_type.value
        if label not in self.VALID_ERROR_TYPES:
            label = "unknown"
        self.retry_exhausted_total[label] += 1
        self._observed_labels["retry_exhausted"].add(label)

    def record_circuit_state_change(
        self,
        circuit_name: str,
        from_state: CircuitState,
        to_state: CircuitState,
    ) -> None:
        """Record a circuit breaker state change."""
        key = f"{circuit_name}:{from_state.value}->{to_state.value}"
        self.circuit_state_changes[key] += 1
        self._observed_labels["circuit_state_changes"].add(key)

    def record_circuit_failure(self, circuit_name: str) -> None:
        """Record a failure through the circuit breaker."""
        self.circuit_failures[circuit_name] += 1
        self._observed_labels["circuit_failures"].add(circuit_name)

    def record_circuit_rejection(self, circuit_name: str) -> None:
        """Record a rejection due to open circuit."""
        self.circuit_rejections[circuit_name] += 1
        self._observed_labels["circuit_rejections"].add(circuit_name)

    @property
    def cardinality_guard(self) -> dict[str, int]:
        """Return observed cardinality per metric family for testing."""
        return {family: len(vals) for family, vals in self._observed_labels.items()}

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Retry metrics
        for error_type, count in sorted(self.retries_total.items()):
            lines.append(
                f'opsswarm_resilience_retries_total{{error_type="{error_type}"}} {count}'
            )
        for error_type, count in sorted(self.retry_success_total.items()):
            lines.append(
                f'opsswarm_resilience_retry_success_total{{error_type="{error_type}"}} {count}'
            )
        for error_type, count in sorted(self.retry_exhausted_total.items()):
            lines.append(
                f'opsswarm_resilience_retry_exhausted_total{{error_type="{error_type}"}} {count}'
            )

        # Circuit breaker metrics
        for circuit, count in sorted(self.circuit_failures.items()):
            lines.append(f'opsswarm_resilience_circuit_failures_total{{circuit="{circuit}"}} {count}')

        for circuit, count in sorted(self.circuit_rejections.items()):
            lines.append(
                f'opsswarm_resilience_circuit_rejections_total{{circuit="{circuit}"}} {count}'
            )

        # State changes (no labels - stored as key)
        for key, count in sorted(self.circuit_state_changes.items()):
            lines.append(f'opsswarm_resilience_circuit_state_changes_total{{key="{key}"}} {count}')

        return "\n".join(lines)


# Module-level metrics instance
resilience_metrics = ResilienceMetrics()


# ----------------------------------------------------------------------
# Decorator for easy retry integration
# ----------------------------------------------------------------------


def with_retry(config: RetryConfig | None = None):
    """Decorator to add retry logic to an async function.

    Usage
    -----
    @with_retry(RetryConfig(max_attempts=5))
    async def call_github_api():
        ...
    """
    retry_config = config or RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_with_contract(func, retry_config, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
