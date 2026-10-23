"""Unit and fault tests for opsswarm.resilience and GitHubClient dependency resilience."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from opsswarm.github_client import GitHubClient
from opsswarm.resilience import (
    AmbiguousWriteOutcome,
    AuthDenied,
    CircuitBreaker,
    DependencyCircuitOpen,
    DependencyTimeout,
    DependencyUnavailable,
    InvalidDependencyResponse,
    RateLimited,
    RetryPolicy,
    classify_http_error,
    classify_transport_error,
    normalize_operation,
    parse_retry_after,
)


class TestRetryPolicy:
    def test_invalid_parameters(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RetryPolicy(max_attempts=0)
        with pytest.raises(ValueError, match="base_delay must be >= 0"):
            RetryPolicy(base_delay=-1.0)
        with pytest.raises(ValueError, match="max_delay must be >= 0"):
            RetryPolicy(max_delay=-1.0)
        with pytest.raises(ValueError, match="jitter_ratio must be within"):
            RetryPolicy(jitter_ratio=1.5)

    def test_delay_for_exponential_and_jitter(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter_ratio=0.0)
        assert policy.delay_for(1) == 1.0  # 1 * 2^0
        assert policy.delay_for(2) == 2.0  # 1 * 2^1
        assert policy.delay_for(3) == 4.0  # 1 * 2^2

    def test_delay_for_retry_after_wins(self):
        policy = RetryPolicy(max_delay=5.0)
        delay = policy.delay_for(1, retry_after=3.5)
        assert delay == 3.5

        # Capped at max_delay
        delay_capped = policy.delay_for(1, retry_after=20.0)
        assert delay_capped == 5.0


class TestOperationNormalization:
    def test_normalize_operation(self):
        assert normalize_operation("GET", "/repos/owner/repo/issues/123") == "GET:/repos/{repo}/issues/{number}"
        assert normalize_operation("POST", "/repos/foo/bar/git/commits/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2") == "POST:/repos/{repo}/git/commits/{sha}"
        assert normalize_operation("GET", "/health") == "GET:/{name}"


class TestErrorClassification:
    def test_classify_401(self):
        resp = MagicMock(status_code=401, headers={}, text="Unauthorized")
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, AuthDenied)
        assert err.error_slug == "auth_denied"
        assert not err.retryable
        assert not err.counts_toward_circuit

    def test_classify_403_plain(self):
        resp = MagicMock(status_code=403, headers={}, text="Forbidden")
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, AuthDenied)
        assert err.error_slug == "auth_denied"

    def test_classify_403_with_rate_limit_evidence(self):
        resp = MagicMock(
            status_code=403,
            headers={"x-ratelimit-remaining": "0"},
            text="API rate limit exceeded",
        )
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, RateLimited)
        assert err.error_slug == "rate_limited"
        assert err.retryable

    def test_classify_429(self):
        resp = MagicMock(
            status_code=429,
            headers={"retry-after": "5"},
            text="Too Many Requests",
        )
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, RateLimited)
        assert err.retry_after == 5.0
        assert err.retryable

    def test_classify_5xx(self):
        resp = MagicMock(status_code=503, headers={}, text="Service Unavailable")
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, DependencyUnavailable)
        assert err.error_slug == "dependency_unavailable"
        assert err.retryable
        assert err.counts_toward_circuit

    def test_classify_redirect(self):
        resp = MagicMock(status_code=302, headers={}, text="Found")
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, InvalidDependencyResponse)
        assert err.error_slug == "invalid_response"
        assert not err.retryable

    def test_classify_transport_error_connect_vs_write(self):
        connect_exc = httpx.ConnectError("Connection refused")
        err_read = classify_transport_error(connect_exc, method="POST", path="/test", is_write=True)
        # Connect failure provably never delivered the request -> not ambiguous write
        assert not isinstance(err_read, AmbiguousWriteOutcome)

        read_timeout_exc = httpx.ReadTimeout("Read timed out")
        err_write = classify_transport_error(read_timeout_exc, method="POST", path="/test", is_write=True)
        assert isinstance(err_write, AmbiguousWriteOutcome)
        assert err_write.error_slug == "ambiguous_write"
        assert not err_write.retryable
        assert err_write.counts_toward_circuit


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_circuit_normal_and_failure_threshold(self):
        cb = CircuitBreaker("test-dep", failure_threshold=2, recovery_timeout=0.1)
        assert cb.state == "CLOSED"

        # 4xx client errors do not count toward circuit
        # (simulated via record_failure only for circuit-counting errors)
        await cb.record_failure()
        assert cb.state == "CLOSED"

        await cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.is_open

        # Fail fast when open
        with pytest.raises(DependencyCircuitOpen):
            await cb.acquire(operation="GET:/test")

        # Wait for recovery timeout to elapse -> HALF_OPEN
        await asyncio.sleep(0.15)
        await cb.acquire(operation="GET:/test")
        assert cb.state == "HALF_OPEN"

        # Success closes circuit
        await cb.record_success()
        assert cb.state == "CLOSED"


class TestGitHubClientResilienceWiring:
    @pytest.fixture
    def client(self):
        return GitHubClient(token="test-token", repo="owner/repo")

    @pytest.mark.asyncio
    async def test_idempotent_get_retries_on_5xx_and_succeeds(self, client):
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_fail = MagicMock()
            mock_fail.status_code = 503
            mock_fail.text = "Service Unavailable"
            mock_fail.content = b"Service Unavailable"
            mock_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
                "503 Service Unavailable", request=MagicMock(), response=mock_fail
            )

            mock_success = MagicMock()
            mock_success.status_code = 200
            mock_success.content = b'{"ok": true}'
            mock_success.json.return_value = {"ok": True}
            mock_success.raise_for_status = MagicMock()

            mock_request.side_effect = [mock_fail, mock_success]

            # Fast sleep during test
            client.retry_policy = RetryPolicy(max_attempts=3, base_delay=0.01, sleep=AsyncMock())

            res = await client.get_issue(1)
            assert res == {"ok": True}
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_writes_never_auto_retried(self, client):
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_fail = MagicMock()
            mock_fail.status_code = 503
            mock_fail.text = "Service Unavailable"
            mock_fail.content = b"Service Unavailable"
            mock_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
                "503 Service Unavailable", request=MagicMock(), response=mock_fail
            )
            mock_request.return_value = mock_fail

            client.retry_policy = RetryPolicy(max_attempts=3, base_delay=0.01, sleep=AsyncMock())

            with pytest.raises(DependencyUnavailable):
                await client.comment(1, "hello")

            # POST request must not be retried automatically
            assert mock_request.call_count == 1


class TestResilienceAdditionalCoverage:
    def test_dependency_error_for_log(self):
        err = DependencyUnavailable("error message", operation="GET:/test", status_code=503, correlation_id="corr-123")
        log_str = err.for_log()
        assert "corr-123" in log_str
        assert "op=GET:/test" in log_str
        assert "status=503" in log_str
        comment_str = err.for_comment()
        assert "dependency_unavailable" in comment_str
        assert "corr-123" in comment_str

    def test_classify_http_error_other_status(self):
        from opsswarm.resilience import classify_http_error
        resp = MagicMock(status_code=400, headers={}, text="Bad Request")
        err = classify_http_error(resp, method="GET", path="/test")
        assert isinstance(err, InvalidDependencyResponse)


    def test_header_value_edge_cases(self):
        from opsswarm.resilience import _header_value
        assert _header_value(None, "foo") is None
        assert _header_value(object(), "foo") is None

    def test_parse_retry_after_invalid(self):
        # Invalid float in retry-after and x-ratelimit-reset
        headers1 = {"retry-after": "not-a-float"}
        assert parse_retry_after(headers1) == (None, None)

        headers2 = {"x-ratelimit-reset": "not-a-float"}
        assert parse_retry_after(headers2) == (None, None)

    def test_parse_retry_after_valid_reset(self):
        # Valid x-ratelimit-reset epoch timestamp
        now = datetime.now(timezone.utc)
        epoch = (now.timestamp() + 10)
        headers = {"x-ratelimit-reset": str(epoch)}
        delta, reset_at = parse_retry_after(headers, now=now)
        assert delta is not None
        assert reset_at is not None


    def test_has_rate_limit_evidence_invalid_remaining(self):
        from opsswarm.resilience import _has_rate_limit_evidence
        headers = {"x-ratelimit-remaining": "invalid"}
        assert _has_rate_limit_evidence(headers, "some body") is False

    def test_circuit_breaker_validation_and_half_open_limits(self):
        with pytest.raises(ValueError):
            CircuitBreaker("cb", failure_threshold=0)
        with pytest.raises(ValueError):
            CircuitBreaker("cb", recovery_timeout=0.0)
        with pytest.raises(ValueError):
            CircuitBreaker("cb", half_open_max_calls=0)

        cb = CircuitBreaker("cb", failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=1)
        snapshot = cb.snapshot()
        assert snapshot["name"] == "cb"
        assert snapshot["state"] == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_max_calls_exceeded(self):
        cb = CircuitBreaker("cb", failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        await cb.record_failure()
        assert cb.state == "OPEN"
        await asyncio.sleep(0.02)
        # Transition to HALF_OPEN
        await cb.acquire(operation="GET:/test")
        assert cb.state == "HALF_OPEN"
        # Second acquire in same half_open window should raise DependencyCircuitOpen
        with pytest.raises(DependencyCircuitOpen):
            await cb.acquire(operation="GET:/test")

    def test_retry_policy_capped_zero_delay(self):
        policy = RetryPolicy(base_delay=0.0)
        assert policy.delay_for(1) == 0.0

