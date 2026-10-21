"""Tests for typed GitHub API errors and retry logic.

These tests verify:
- Typed error classification from HTTP status codes
- Retry logic with safe retry contracts
- Idempotency checks for non-idempotent operations
"""

import pytest
from unittest.mock import AsyncMock, patch

from opsswarm.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    GitHubAPIError,
    GitHubAPIErrorType,
    RetryConfig,
    ResilienceMetrics,
    RetryExhaustedError,
    classify_httpx_error,
    retry_with_contract,
    resilience_metrics,
)


class TestGitHubAPIErrorClassification:
    """Tests for GitHub API error classification."""

    def test_classify_404_not_found(self):
        """404 errors should be NOT_FOUND, not retryable."""
        error = classify_httpx_error(404, "Not Found")
        assert error.error_type == GitHubAPIErrorType.NOT_FOUND
        assert error.status_code == 404
        assert not error.is_retryable
        assert error.is_idempotent

    def test_classify_403_forbidden(self):
        """403 errors should be FORBIDDEN, potentially retryable (rate limit)."""
        error = classify_httpx_error(403, "Forbidden")
        assert error.error_type == GitHubAPIErrorType.FORBIDDEN
        assert error.status_code == 403
        assert error.is_retryable  # Could be rate limited

    def test_classify_401_unauthorized(self):
        """401 errors should be UNAUTHORIZED, not retryable."""
        error = classify_httpx_error(401, "Unauthorized")
        assert error.error_type == GitHubAPIErrorType.UNAUTHORIZED
        assert error.status_code == 401
        assert not error.is_retryable

    def test_classify_422_validation_failed(self):
        """422 errors should be VALIDATION_FAILED, not retryable."""
        error = classify_httpx_error(422, "Validation Failed")
        assert error.error_type == GitHubAPIErrorType.VALIDATION_FAILED
        assert error.status_code == 422
        assert not error.is_retryable

    def test_classify_409_conflict(self):
        """409 errors should be CONFLICT, retryable."""
        error = classify_httpx_error(409, "Conflict")
        assert error.error_type == GitHubAPIErrorType.CONFLICT
        assert error.status_code == 409
        assert error.is_retryable

    def test_classify_500_server_error(self):
        """500 errors should be SERVER_ERROR, retryable."""
        error = classify_httpx_error(500, "Internal Server Error")
        assert error.error_type == GitHubAPIErrorType.SERVER_ERROR
        assert error.status_code == 500
        assert error.is_retryable

    def test_classify_503_service_unavailable(self):
        """503 errors should be SERVICE_UNAVAILABLE, retryable."""
        error = classify_httpx_error(503, "Service Unavailable")
        assert error.error_type == GitHubAPIErrorType.SERVICE_UNAVAILABLE
        assert error.status_code == 503
        assert error.is_retryable

    def test_classify_504_gateway_timeout(self):
        """504 errors should be GATEWAY_TIMEOUT, retryable."""
        error = classify_httpx_error(504, "Gateway Timeout")
        assert error.error_type == GitHubAPIErrorType.GATEWAY_TIMEOUT
        assert error.status_code == 504
        assert error.is_retryable

    def test_classify_timeout(self):
        """None status code with timeout message should be TIMEOUT."""
        error = classify_httpx_error(None, "Request timeout")
        assert error.error_type == GitHubAPIErrorType.TIMEOUT
        assert error.status_code is None
        assert error.is_retryable

    def test_classify_connection_error(self):
        """None status code with connection message should be CONNECTION_ERROR."""
        error = classify_httpx_error(None, "Connection refused")
        assert error.error_type == GitHubAPIErrorType.CONNECTION_ERROR
        assert error.status_code is None
        assert error.is_retryable


class TestRetryConfig:
    """Tests for retry configuration."""

    def test_default_config_retryable_types(self):
        """Default config should retry on server errors and transient issues."""
        config = RetryConfig()
        error_500 = GitHubAPIError(
            error_type=GitHubAPIErrorType.SERVER_ERROR,
            status_code=500,
            message="Error",
            is_retryable=True,  # Server errors are retryable
        )
        error_404 = GitHubAPIError(
            error_type=GitHubAPIErrorType.NOT_FOUND,
            status_code=404,
            message="Not Found",
        )
        assert config.should_retry(error_500)
        assert not config.should_retry(error_404)

    def test_custom_retry_types(self):
        """Custom config should only retry on specified types."""
        config = RetryConfig(retry_on_types=(GitHubAPIErrorType.SERVER_ERROR,))
        error_500 = GitHubAPIError(
            error_type=GitHubAPIErrorType.SERVER_ERROR,
            status_code=500,
            message="Error",
            is_retryable=True,  # Server errors are retryable
        )
        error_503 = GitHubAPIError(
            error_type=GitHubAPIErrorType.SERVICE_UNAVAILABLE,
            status_code=503,
            message="Service Unavailable",
        )
        assert config.should_retry(error_500)
        assert not config.should_retry(error_503)


class TestRetryWithContract:
    """Tests for retry with idempotent contract."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Successful execution should return result immediately."""
        async def succeed():
            return "success"

        config = RetryConfig(max_attempts=3)
        result = await retry_with_contract(succeed, config)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_on_retryable_error(self):
        """Should retry when error is retryable."""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise GitHubAPIError(
                    error_type=GitHubAPIErrorType.SERVER_ERROR,
                    status_code=500,
                    message="Server Error",
                    is_retryable=True,  # Server errors are retryable
                )
            return "success"

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        result = await retry_with_contract(flaky, config)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_error(self):
        """Should not retry when error is not retryable."""
        call_count = 0

        async def fails():
            nonlocal call_count
            call_count += 1
            raise GitHubAPIError(
                error_type=GitHubAPIErrorType.NOT_FOUND,
                status_code=404,
                message="Not Found",
            )

        config = RetryConfig(max_attempts=3)
        with pytest.raises(GitHubAPIError):
            await retry_with_contract(fails, config)
        assert call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_no_retry_on_non_idempotent_operation(self):
        """Should not retry non-idempotent operations even if error is retryable."""
        call_count = 0

        async def create():
            nonlocal call_count
            call_count += 1
            raise GitHubAPIError(
                error_type=GitHubAPIErrorType.SERVER_ERROR,
                status_code=500,
                message="Server Error",
                is_idempotent=False,  # POST is non-idempotent
            )

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        with pytest.raises(GitHubAPIError):
            await retry_with_contract(
                create,
                config,
                operation_is_idempotent=False,  # Explicit override
            )
        assert call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Should raise RetryExhaustedError after max attempts."""
        async def always_fails():
            raise GitHubAPIError(
                error_type=GitHubAPIErrorType.SERVER_ERROR,
                status_code=500,
                message="Server Error",
                is_retryable=True,  # Server errors are retryable
            )

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        with pytest.raises(RetryExhaustedError) as exc_info:
            await retry_with_contract(always_fails, config)
        assert exc_info.value.attempts == 3

    @pytest.mark.asyncio
    async def test_metrics_recorded(self):
        """Should record metrics for retries."""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise GitHubAPIError(
                    error_type=GitHubAPIErrorType.SERVER_ERROR,
                    status_code=500,
                    message="Server Error",
                    is_retryable=True,  # Server errors are retryable
                )
            return "success"

        # Reset metrics
        resilience_metrics.retries_total.clear()
        resilience_metrics.retry_success_total.clear()

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        await retry_with_contract(flaky, config)

        # Should have recorded retry attempts
        assert resilience_metrics.retries_total["server_error"] >= 1
        assert resilience_metrics.retry_success_total["server_error"] >= 1


class TestCircuitBreaker:
    """Tests for circuit breaker."""

    @pytest.mark.asyncio
    async def test_closed_by_default(self):
        """Circuit should be closed by default."""
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """Successful call should reset failure count."""
        cb = CircuitBreaker("test")
        cb._failure_count = 3
        await cb.call(AsyncMock(return_value="success"))
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self):
        """Circuit should open after failure threshold."""
        cb = CircuitBreaker("test", config=CircuitBreakerConfig())

        async def fail():
            raise Exception("fail")

        # Configure for quick failure threshold
        cb.config.failure_threshold = 3
        for _ in range(3):
            with pytest.raises(Exception):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_raises_fast_fail(self):
        """Open circuit should raise CircuitBreakerOpenError."""
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(AsyncMock(return_value="success"))

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """Circuit should transition to half-open after timeout."""
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic() - cb.config.timeout - 1

        # Accessing state should trigger transition
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_reset(self):
        """Manual reset should close circuit."""
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN
        cb._failure_count = 5
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_records_failure_metric(self):
        """Circuit should record failure metrics."""
        # Use the module-level singleton
        from opsswarm import resilience

        resilience.resilience_metrics.circuit_failures.clear()

        cb = CircuitBreaker("test_github")
        cb.config.failure_threshold = 1

        async def fail():
            raise Exception("fail")

        with pytest.raises(Exception):
            await cb.call(fail)

        assert resilience.resilience_metrics.circuit_failures["test_github"] >= 1

    @pytest.mark.asyncio
    async def test_circuit_records_rejection_metric(self):
        """Circuit should record rejection when open."""
        from opsswarm import resilience

        resilience.resilience_metrics.circuit_rejections.clear()

        cb = CircuitBreaker("test_github")
        cb._state = CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await cb.call(AsyncMock(return_value="success"))

        assert exc_info.value.circuit_name == "test_github"
        assert resilience.resilience_metrics.circuit_rejections["test_github"] >= 1

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success(self):
        """Circuit should close after success threshold in half-open state."""
        cb = CircuitBreaker("test", config=CircuitBreakerConfig())
        cb._state = CircuitState.HALF_OPEN
        cb.config.success_threshold = 2

        # Two successes should close the circuit
        await cb.call(AsyncMock(return_value="success"))
        assert cb.state == CircuitState.HALF_OPEN  # Still half-open after first success
        await cb.call(AsyncMock(return_value="success"))
        assert cb.state == CircuitState.CLOSED  # Closed after second success

    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self):
        """Circuit should reopen on failure in half-open state."""
        cb = CircuitBreaker("test", config=CircuitBreakerConfig())
        cb._state = CircuitState.HALF_OPEN

        async def fail():
            raise Exception("fail")

        with pytest.raises(Exception):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN


class TestResilienceMetrics:
    """Tests for resilience metrics."""

    def test_cardinality_guard(self):
        """Metrics should track cardinality."""
        metrics = ResilienceMetrics()
        metrics.record_retry(GitHubAPIErrorType.SERVER_ERROR)
        metrics.record_retry(GitHubAPIErrorType.NOT_FOUND)

        guard = metrics.cardinality_guard
        assert guard["retries"] == 2

    def test_prometheus_export(self):
        """Should export valid Prometheus format."""
        metrics = ResilienceMetrics()
        metrics.record_retry(GitHubAPIErrorType.SERVER_ERROR)
        metrics.record_circuit_failure("github_api")

        output = metrics.to_prometheus()
        assert 'opsswarm_resilience_retries_total{error_type="server_error"}' in output
        assert 'opsswarm_resilience_circuit_failures_total{circuit="github_api"}' in output


class TestRetryDecorator:
    """Tests for the with_retry decorator."""

    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        """Decorator should add retry logic to function."""
        from opsswarm.resilience import with_retry

        call_count = 0

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise GitHubAPIError(
                    error_type=GitHubAPIErrorType.SERVER_ERROR,
                    status_code=500,
                    message="Server Error",
                    is_retryable=True,
                )
            return "success"

        result = await flaky()
        assert result == "success"
        assert call_count == 2


# Import time for circuit breaker tests
import time
