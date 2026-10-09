"""Fault injection tests for GitHubClient typed failure taxonomy and retry/circuit-breaker (Issue #75)."""

import asyncio
import time as time_module
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
    DependencyError,
    DependencyTimeout,
    DependencyUnavailable,
    InvalidDependencyResponse,
    RateLimited,
    idempotent_retry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockResponse:
    """A minimal fake httpx.Response that passes r.status_code comparisons.

    httpx.Response uses __slots__ so we can't set _status_code via object.__setattr__.
    Instead we wrap it in a duck-compatible fake.
    """
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self._content = text.encode() if text else b""
        self.headers = httpx.Headers(headers or {})
        self.text = text

    def json(self):
        import json as _json
        return _json.loads(self._content)


async def mk_resp(status_code: int, text: str = "", headers: dict | None = None) -> MockResponse:
    """Async factory for MockResponse -- used as side_effect in mocked request()."""
    return MockResponse(status_code, text, headers)


# ---------------------------------------------------------------------------
# Test: GET timeout -> bounded retry then DependencyTimeout
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_get_timeout_bounded_retry_then_dependency_timeout():
    """GitHub GET timeout: retries bounded, then raises DependencyTimeout."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def timeout_request(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    with patch.object(client.client, "request", side_effect=timeout_request):
        with pytest.raises(DependencyTimeout) as exc_info:
            await client.get_issue(1)

        exc = exc_info.value
        assert exc.error_slug == "dependency_timeout"
        assert exc.correlation_id != ""
        assert exc.operation != ""
        assert exc.is_transport_error is False


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_get_timeout_eventually_succeeds():
    """GitHub GET timeout: retries and succeeds on second attempt."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    success_r = MockResponse(200, '{"number":1}')
    call_count = [0]

    async def flaky_request(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise httpx.ReadTimeout("timeout")
        return success_r

    with patch.object(client.client, "request", side_effect=flaky_request):
        result = await client.get_issue(1)
        assert result["number"] == 1
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Test: GitHub 429 -> honours Retry-After, typed RateLimited
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_429_raises_rate_limited():
    """GitHub 429 raises RateLimited with retry_after and reset_at metadata."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    response_429 = MockResponse(
        429,
        text="Too Many Requests",
        headers={
            "Retry-After": "30",
            "X-RateLimit-Reset": "1791138000",
        },
    )

    async def return_429(*args, **kwargs):
        return response_429

    with patch.object(client.client, "request", side_effect=return_429):
        with pytest.raises(RateLimited) as exc_info:
            await client.get_issue(1)

        exc = exc_info.value
        assert exc.error_slug == "rate_limited"
        assert exc.retry_after == 30.0
        assert exc.status_code == 429
        assert exc.reset_at is not None
        assert exc.reset_at.timestamp() == pytest.approx(1791138000, rel=1)


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_429_retry_after_respected():
    """After RateLimited, retry is attempted after retry_after delay."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=2)

    response_429 = MockResponse(429, headers={"Retry-After": "2"})
    success_r = MockResponse(200, '{"number":1}')
    call_count = [0]

    async def flaky_request(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return response_429
        return success_r

    with patch.object(client.client, "request", side_effect=flaky_request):
        start = time_module.monotonic()
        result = await client.get_issue(1)
        elapsed = time_module.monotonic() - start

        assert result["number"] == 1
        assert elapsed >= 1.9  # waited at least ~2s (retry_after)


# ---------------------------------------------------------------------------
# Test: GitHub 401/403 -> no retry, typed AuthDenied
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_401_raises_auth_denied_no_retry():
    """GitHub 401 raises AuthDenied; no retry attempted."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_401(*args, **kwargs):
        return MockResponse(401, "Bad credentials")

    with patch.object(client.client, "request", side_effect=return_401) as mock_req:
        with pytest.raises(AuthDenied) as exc_info:
            await client.get_issue(1)

        exc = exc_info.value
        assert exc.error_slug == "auth_denied"
        assert exc.status_code == 401
        assert mock_req.call_count == 1  # no retry


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_403_raises_auth_denied_no_retry():
    """GitHub 403 raises AuthDenied; no retry attempted."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_403(*args, **kwargs):
        return MockResponse(403, "Forbidden")

    with patch.object(client.client, "request", side_effect=return_403) as mock_req:
        with pytest.raises(AuthDenied) as exc_info:
            await client.get_issue(1)

        exc = exc_info.value
        assert exc.error_slug == "auth_denied"
        assert exc.status_code == 403
        assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# Test: GitHub POST with lost response -> no blind retry, AmbiguousWriteOutcome
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_post_timeout_raises_ambiguous_write_outcome():
    """GitHub POST timeout: raises AmbiguousWriteOutcome, never retried."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def timeout_request(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    with patch.object(client.client, "request", side_effect=timeout_request) as mock_req:
        with pytest.raises(AmbiguousWriteOutcome) as exc_info:
            await client.comment(1, "hello")

        exc = exc_info.value
        assert exc.error_slug == "ambiguous_write"
        assert "comment" in exc.operation
        assert mock_req.call_count == 1  # no retry


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_post_429_raises_ambiguous_write_outcome():
    """GitHub POST 429: raises AmbiguousWriteOutcome (never auto-retry a write)."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_429(*args, **kwargs):
        return MockResponse(429, headers={"Retry-After": "5"})

    with patch.object(client.client, "request", side_effect=return_429) as mock_req:
        with pytest.raises(AmbiguousWriteOutcome) as exc_info:
            await client.comment(1, "hello")

        exc = exc_info.value
        assert exc.error_slug == "ambiguous_write"
        # Should NOT have waited 5s (no retry for writes)
        assert mock_req.call_count == 1


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_post_500_raises_ambiguous_write_outcome():
    """GitHub POST 500: raises AmbiguousWriteOutcome (never auto-retry a write)."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_500(*args, **kwargs):
        return MockResponse(500, "Internal Server Error")

    with patch.object(client.client, "request", side_effect=return_500) as mock_req:
        with pytest.raises(AmbiguousWriteOutcome) as exc_info:
            await client.create_issue("title", "body", [])

        exc = exc_info.value
        assert exc.error_slug == "ambiguous_write"
        assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# Test: GitHub 5xx -> bounded retry for GETs, AmbiguousWriteOutcome for writes
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_get_500_bounded_retry_then_dependency_unavailable():
    """GitHub GET 500: retries bounded, then raises DependencyUnavailable."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_500(*args, **kwargs):
        return MockResponse(500, "Internal Server Error")

    with patch.object(client.client, "request", side_effect=return_500) as mock_req:
        with pytest.raises(DependencyUnavailable) as exc_info:
            await client.get_issue(1)

        exc = exc_info.value
        assert exc.error_slug == "dependency_unavailable"
        assert exc.status_code == 500
        # All 3 attempts made
        assert mock_req.call_count == 3


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_get_502_eventually_succeeds():
    """GitHub GET 502: succeeds on retry after two failures."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    success_r = MockResponse(200, '{"number":1}')
    call_count = [0]

    async def flaky_request(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] < 3:
            return MockResponse(502, "Bad Gateway")
        return success_r

    with patch.object(client.client, "request", side_effect=flaky_request):
        result = await client.get_issue(1)
        assert result["number"] == 1
        assert call_count[0] == 3


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_post_500_raises_ambiguous_write_not_dependency_unavailable():
    """POST 500 must raise AmbiguousWriteOutcome, not DependencyUnavailable."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_500(*args, **kwargs):
        return MockResponse(500, "Internal Server Error")

    with patch.object(client.client, "request", side_effect=return_500) as mock_req:
        with pytest.raises(AmbiguousWriteOutcome):
            await client.comment(1, "hello")

        assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# Test: Circuit-breaker: opens, raises DependencyCircuitOpen on 4th call
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    """Circuit opens after failure_threshold consecutive failures.

    Calls 1-3: ValueError propagates (circuit still CLOSED during execution).
    After 3rd: circuit transitions CLOSED->OPEN.
    Call 4: DependencyCircuitOpen is raised (circuit is OPEN).
    """
    cb = CircuitBreaker(name="test", failure_threshold=3)

    async def failing():
        raise ValueError("boom")

    # 2 failures -- still CLOSED; ValueError propagates
    for i in range(2):
        with pytest.raises(ValueError):
            await cb.call(failing())
    assert cb.state == "CLOSED"

    # 3rd failure -- ValueError propagates, circuit transitions CLOSED->OPEN
    with pytest.raises(ValueError):
        await cb.call(failing())
    assert cb.state == "OPEN"

    # 4th call -- circuit is OPEN, DependencyCircuitOpen is raised immediately
    with pytest.raises(DependencyCircuitOpen):
        await cb.call(failing())


@pytest.mark.fault
@pytest.mark.asyncio
async def test_circuit_open_raises_dependency_circuit_open():
    """When circuit is OPEN, DependencyCircuitOpen is raised."""
    cb = CircuitBreaker(name="test", failure_threshold=2)

    async def failing():
        raise ValueError("boom")

    # Trip the circuit (2 failures -> OPEN)
    with pytest.raises(ValueError):
        await cb.call(failing())
    with pytest.raises(ValueError):
        await cb.call(failing())
    assert cb.state == "OPEN"

    # Next call: circuit is OPEN
    with pytest.raises(DependencyCircuitOpen) as exc_info:
        await cb.call(failing())

    assert exc_info.value.error_slug == "circuit_open"


@pytest.mark.fault
@pytest.mark.asyncio
async def test_circuit_recovery_deterministic_close():
    """After recovery_timeout, circuit transitions to HALF_OPEN then CLOSED on success."""
    cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1)

    async def failing():
        raise ValueError("boom")

    # Trip the circuit
    with pytest.raises(ValueError):
        await cb.call(failing())
    assert cb.state == "OPEN"

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # HALF_OPEN probe succeeds -> CLOSED
    result = await cb.call(asyncio.sleep(0, result=42))
    assert result == 42
    assert cb.state == "CLOSED"


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_client_circuit_breaker_exposed():
    """GitHubClient exposes circuit_breaker property."""
    client = GitHubClient(token="tok", repo="owner/repo")
    assert client.circuit_breaker is client._circuit


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_get_circuit_open_raises_dependency_circuit_open():
    """When circuit is OPEN, GitHubClient GET raises DependencyCircuitOpen."""
    client = GitHubClient(token="tok", repo="owner/repo", circuit_failure_threshold=2)

    async def failing():
        raise ValueError("boom")

    # Pre-trip the circuit (2 failures -> OPEN)
    with pytest.raises(ValueError):
        await client._circuit.call(failing())
    with pytest.raises(ValueError):
        await client._circuit.call(failing())

    assert client.circuit_breaker.state == "OPEN"

    # Now a real call raises DependencyCircuitOpen before making the HTTP request
    with pytest.raises(DependencyCircuitOpen):
        await client.get_issue(1)


# ---------------------------------------------------------------------------
# Test: Retry budget exhaustion -> auditable typed failure
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_retry_exhaustion_raises_last_exception():
    """All attempts exhausted -> last exception type is raised."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3, base_delay=0.001)

    async def return_500(*args, **kwargs):
        return MockResponse(500, "Internal Server Error")

    with patch.object(client.client, "request", side_effect=return_500) as mock_req:
        with pytest.raises(DependencyUnavailable) as exc_info:
            await client.get_issue(1)

        assert exc_info.value.error_slug == "dependency_unavailable"
        assert mock_req.call_count == 3


@pytest.mark.fault
@pytest.mark.asyncio
async def test_retry_exhaustion_records_metric():
    """Retry exhaustion is recorded in metrics."""
    from opsswarm.metrics import Metrics

    m = Metrics()
    m.record_dependency_retry_exhausted("GET:/repos/owner/repo/issues/1")
    assert ("GET:repos:owner:repo:issues:1",) in m.retry_exhausted


# ---------------------------------------------------------------------------
# Test: DependencyError subclasses -- for_comment / for_log
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_auth_denied_for_comment():
    exc = AuthDenied(
        "401 for GET /repos/owner/repo/issues/1",
        correlation_id="abc123",
        status_code=401,
    )
    assert "[auth_denied | ref: abc123]" == exc.for_comment()


@pytest.mark.fault
@pytest.mark.asyncio
async def test_rate_limited_for_log():
    exc = RateLimited(
        "Rate limited",
        retry_after=30.0,
        correlation_id="xyz789",
        operation="GET /test",
    )
    log_line = exc.for_log()
    assert "xyz789" in log_line
    assert "GET /test" in log_line


# ---------------------------------------------------------------------------
# Test: PermissionError is NOT raised by GitHubClient
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_no_permission_error_on_401():
    """PermissionError is not raised -- AuthDenied is used instead."""
    client = GitHubClient(token="tok", repo="owner/repo")

    async def return_401(*args, **kwargs):
        return MockResponse(401, "Bad credentials")

    with patch.object(client.client, "request", side_effect=return_401):
        with pytest.raises(AuthDenied):
            await client.get_issue(1)


@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_no_permission_error_on_timeout():
    """PermissionError is not raised -- DependencyTimeout is used instead."""
    client = GitHubClient(token="tok", repo="owner/repo")

    async def timeout_request(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    with patch.object(client.client, "request", side_effect=timeout_request):
        with pytest.raises(DependencyTimeout):
            await client.get_issue(1)


# ---------------------------------------------------------------------------
# Test: idempotent_retry helper directly
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_idempotent_retry_success_first_attempt():
    """idempotent_retry: succeeds on first attempt, no sleeping."""
    client_call_count = [0]

    async def flaky():
        client_call_count[0] += 1
        return {"data": "ok"}

    result = await idempotent_retry(
        flaky,
        operation="test",
        idempotency_key="test-key",
        max_attempts=3,
        base_delay=10.0,  # would be wrong if we sleep
        _is_idempotent=True,
    )
    assert result == {"data": "ok"}
    assert client_call_count[0] == 1


@pytest.mark.fault
@pytest.mark.asyncio
async def test_idempotent_retry_succeeds_after_failing_attempts():
    """idempotent_retry: fails twice, succeeds on third attempt."""
    counter = [0]

    async def flaky():
        counter[0] += 1
        if counter[0] < 3:
            raise RateLimited("rate limited", retry_after=0.001)
        return {"ok": True}

    result = await idempotent_retry(
        flaky,
        operation="test",
        idempotency_key="test-key",
        max_attempts=3,
        base_delay=0.001,
        max_delay=1.0,
        _is_idempotent=True,
    )
    assert result == {"ok": True}
    assert counter[0] == 3


@pytest.mark.fault
@pytest.mark.asyncio
async def test_idempotent_retry_non_idempotent_write():
    """idempotent_retry with _is_idempotent=False: no retry, AmbiguousWriteOutcome."""
    async def write():
        raise RateLimited("rate limited", retry_after=0)

    with pytest.raises(AmbiguousWriteOutcome):
        await idempotent_retry(
            write,
            operation="POST /test",
            idempotency_key="write-key",
            _is_idempotent=False,
        )


@pytest.mark.fault
@pytest.mark.asyncio
async def test_idempotent_retry_auth_denied_never_retry():
    """idempotent_retry: AuthDenied is never retried."""
    counter = [0]

    async def auth_denied():
        counter[0] += 1
        raise AuthDenied("401", correlation_id="c1", status_code=401)

    with pytest.raises(AuthDenied):
        await idempotent_retry(
            auth_denied,
            operation="GET /test",
            idempotency_key="test-key",
            max_attempts=3,
            _is_idempotent=True,
        )
    assert counter[0] == 1  # no retry


# ---------------------------------------------------------------------------
# Test: CircuitBreaker snapshot
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_circuit_breaker_snapshot():
    cb = CircuitBreaker(name="github:owner/repo", failure_threshold=3, recovery_timeout=30.0)
    snap = cb.snapshot()
    assert snap["name"] == "github:owner/repo"
    assert snap["state"] == "CLOSED"
    assert snap["failure_threshold"] == 3
    assert snap["recovery_timeout"] == 30.0
    assert snap["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Test: 404 raises InvalidDependencyResponse (not retried for GET)
# ---------------------------------------------------------------------------

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_404_raises_invalid_dependency_response():
    """GitHub 404 raises InvalidDependencyResponse; not retried for GET."""
    client = GitHubClient(token="tok", repo="owner/repo", max_attempts=3)

    async def return_404(*args, **kwargs):
        return MockResponse(404, "Not Found")

    with patch.object(client.client, "request", side_effect=return_404) as mock_req:
        with pytest.raises(InvalidDependencyResponse) as exc_info:
            await client.get_issue(9999)

        exc = exc_info.value
        assert exc.error_slug == "invalid_response"
        # No retry for client errors (4xx)
        assert mock_req.call_count == 1
