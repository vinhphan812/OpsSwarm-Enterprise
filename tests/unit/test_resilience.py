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

    def test_jitter_bounds(self):
        policy = RetryPolicy(base_delay=4.0, max_delay=10.0, jitter_ratio=0.5)
        for _ in range(50):
            d = policy.delay_for(1)
            assert 2.0 <= d <= 4.0

    def test_parse_retry_after_headers(self):
        headers = MagicMock()
        headers.get = lambda k: "12" if k == "retry-after" else None
        secs, reset = parse_retry_after(headers)
        assert secs == 12.0

    @pytest.mark.asyncio
    async def test_circuit_half_open_concurrency(self):
        cb = CircuitBreaker("probe-dep", failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        await cb.record_failure()
        assert cb.is_open
        await asyncio.sleep(0.02)
        await cb.acquire()
        assert cb.state == "HALF_OPEN"
        with pytest.raises(DependencyCircuitOpen):
            await cb.acquire()

    @pytest.mark.asyncio
    async def test_ambiguous_write_handling(self, client):
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ReadTimeout("Read timed out")
            client.retry_policy = RetryPolicy(max_attempts=3, base_delay=0.01, sleep=AsyncMock())
            with pytest.raises(AmbiguousWriteOutcome) as exc_info:
                await client.comment(1, "hello")
            assert "ambiguous_write" in exc_info.value.error_slug
            assert mock_request.call_count == 1


class TestHalfOpenProbeRelease:
    """The single HALF_OPEN probe slot must never be stranded."""

    @pytest.mark.asyncio
    async def test_probe_slot_is_released_after_a_terminal_client_error(self):
        """A 404 on the probe leaves the circuit usable instead of stuck."""
        cb = CircuitBreaker("probe-404", failure_threshold=1, recovery_timeout=0.01)
        await cb.record_failure()
        await asyncio.sleep(0.02)

        probe = await cb.acquire(operation="GET:/test")
        assert probe is True
        assert cb.state == "HALF_OPEN"

        # A 404 is a known rejection: it never records a circuit failure, so
        # the slot has to be handed back explicitly.
        cb.release_probe()

        assert await cb.acquire(operation="GET:/test") is True

    @pytest.mark.asyncio
    async def test_probe_slot_is_released_when_the_probe_is_cancelled(self):
        """Cancelling an admitted probe must not wedge the circuit."""
        cb = CircuitBreaker("probe-cancel", failure_threshold=1, recovery_timeout=0.01)
        await cb.record_failure()
        await asyncio.sleep(0.02)

        admitted = asyncio.Event()

        async def probe_call() -> None:
            is_probe = await cb.acquire(operation="GET:/test")
            try:
                admitted.set()
                await asyncio.sleep(10)
            finally:
                if is_probe:
                    cb.release_probe()

        task = asyncio.create_task(probe_call())
        await admitted.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert await cb.acquire(operation="GET:/test") is True

    @pytest.mark.asyncio
    async def test_half_open_admits_exactly_one_probe_concurrently(self):
        """Concurrent callers cannot all probe a recovering dependency."""
        cb = CircuitBreaker("probe-single", failure_threshold=1, recovery_timeout=0.01)
        await cb.record_failure()
        await asyncio.sleep(0.02)

        async def attempt() -> bool:
            try:
                await cb.acquire(operation="GET:/test")
            except DependencyCircuitOpen:
                return False
            return True

        results = await asyncio.gather(*(attempt() for _ in range(5)))

        assert results.count(True) == 1


class TestNonFiniteRetryMetadata:
    """A malformed header must degrade to local backoff, never raise."""

    def _headers(self, **values: str) -> MagicMock:
        lower = {k.replace("_", "-"): v for k, v in values.items()}
        headers = MagicMock()
        headers.get = lambda key: lower.get(key)
        return headers

    @pytest.mark.parametrize("value", ["inf", "-inf", "nan", "1e400"])
    def test_retry_after_rejects_non_finite_values(self, value):
        headers = self._headers(retry_after=value)

        assert parse_retry_after(headers) == (None, None)

    @pytest.mark.parametrize("value", ["inf", "nan", "1e400"])
    def test_rate_limit_reset_rejects_non_finite_epochs(self, value):
        headers = self._headers(x_ratelimit_reset=value)

        assert parse_retry_after(headers) == (None, None)

    def test_out_of_range_epoch_is_rejected(self):
        headers = self._headers(x_ratelimit_reset="1e30")

        assert parse_retry_after(headers) == (None, None)

    def test_finite_retry_after_still_honoured(self):
        headers = self._headers(retry_after="30")

        seconds, reset_at = parse_retry_after(headers)

        assert seconds == 30.0
        assert reset_at is not None

    @pytest.mark.parametrize("value", [float("inf"), float("nan"), float("-inf")])
    def test_retry_policy_ignores_non_finite_retry_after(self, value):
        policy = RetryPolicy(base_delay=1.0, max_delay=4.0, jitter_ratio=0.0)

        delay = policy.delay_for(1, retry_after=value)

        assert delay == 1.0


class TestAmbiguousWriteBarrier:
    """An unknown write outcome must block the replay of that write."""

    @pytest.fixture
    def client(self):
        client = GitHubClient(token="test-token", repo="owner/repo")
        client.circuit = CircuitBreaker("barrier", failure_threshold=100)
        client.retry_policy = RetryPolicy(max_attempts=3, base_delay=0.0, sleep=AsyncMock())
        return client

    @pytest.mark.asyncio
    async def test_replay_is_blocked_until_the_outcome_is_reconciled(self, client):
        path = f"/repos/{client.repo}/issues/1/comments"
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ReadTimeout("Read timed out")
            with pytest.raises(AmbiguousWriteOutcome):
                await client.comment(1, "hello")

            assert f"POST {path}" in client.unreconciled_writes

            # A second attempt must not reach the transport at all.
            with pytest.raises(AmbiguousWriteOutcome) as exc_info:
                await client.comment(1, "hello")
            assert "unreconciled" in str(exc_info.value)
            assert mock_request.call_count == 1

            assert client.acknowledge_ambiguous_write("POST", path) is True
            assert client.unreconciled_writes == frozenset()

            mock_request.side_effect = None
            mock_success = MagicMock()
            mock_success.status_code = 201
            mock_success.content = b'{"id": 1}'
            mock_success.json.return_value = {"id": 1}
            mock_success.headers = {}
            mock_success.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_success]

            assert await client.comment(1, "hello") == {"id": 1}
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_acknowledging_an_unblocked_write_reports_no_change(self, client):
        assert client.acknowledge_ambiguous_write("POST", "/repos/owner/repo/issues/1/labels") is False

    @pytest.mark.asyncio
    async def test_ambiguous_message_demands_reconciliation(self, client):
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ReadTimeout("Read timed out")
            with pytest.raises(AmbiguousWriteOutcome) as exc_info:
                await client.comment(1, "hello")

        message = str(exc_info.value)
        assert "outcome unknown" in message
        assert "do not retry" in message
        assert exc_info.value.ambiguous is True

    @pytest.mark.asyncio
    async def test_probe_slot_is_released_after_a_terminal_client_error(self, client):
        """A 404 during a HALF_OPEN probe does not wedge the shared circuit."""
        circuit = client.circuit
        circuit.recovery_timeout = 0.01
        circuit.failure_threshold = 1
        await circuit.record_failure()
        await asyncio.sleep(0.02)

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            response = MagicMock()
            response.status_code = 404
            response.text = "Not Found"
            response.content = b"Not Found"
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=response
            )
            mock_request.return_value = response

            with pytest.raises(InvalidDependencyResponse):
                await client.get_issue(1)

        assert circuit.state == "HALF_OPEN"
        assert circuit._half_open_calls == 0
