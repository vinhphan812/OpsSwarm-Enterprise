# Issue #75 — Typed Dependency Resilience: Phased Implementation Plan

**Issue:** [#75](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/75)
**ADR:** ADR-030
**Reference WIP:** `opsswarm/resilience.py`, `tests/faults/test_github_typed_failures.py`
**Status:** Proposed

---

## Phase 1: Ship the resilience module and metrics (foundation)

**Goal:** Land `opsswarm/resilience.py` + metric additions without touching `github_client.py`.

### Task 1a — Add metrics methods

**File:** `opsswarm/metrics.py`

Add two new methods to `Metrics` (both guard cardinality with `_observed_labels`):

```python
# After record_reconciliation_outcome:
def record_dependency_retry_exhausted(self, operation: str):
    """Called when all read retry attempts are exhausted."""
    safe = operation[:256]  # guard: truncate before using as label
    self._observed_labels.setdefault("dependency_retries_exhausted", set()).add(safe)

def record_circuit_state(self, dependency: str, state: str):
    """Called on every circuit state transition."""
    VALID_CIRCUIT_STATES = frozenset({"CLOSED", "OPEN", "HALF_OPEN"})
    if state not in VALID_CIRCUIT_STATES:
        state = "UNKNOWN"
    safe_dep = dependency[:128]
    safe_state = state
    self._observed_labels.setdefault("circuit_state", set()).add(f"{safe_dep}:{safe_state}")
```

Add two new metric families to `to_prometheus()`:

```python
# After ambiguous_writes block:
for op, count in sorted(self._retry_exhausted_internal()):
    lines.append(f'opsswarm_dependency_retries_exhausted_total{{operation="{op}"}} {count}')
for dep_state, count in sorted(self._circuit_state_internal()):
    dep, state = dep_state.rsplit(":", 1)
    lines.append(f'opsswarm_circuit_state{{dependency="{dep}",state="{state}"}} {count}')
```

Where `_retry_exhausted_internal` and `_circuit_state_internal` are private counters
added to `__init__`:

```python
self._dependency_retries_exhausted = Counter()
self._circuit_state = Counter()
```

Acceptance criteria:
- [ ] `pytest tests/unit/test_metrics.py` passes
- [ ] `metrics.to_prometheus()` contains `opsswarm_dependency_retries_exhausted_total` and `opsswarm_circuit_state` lines

---

### Task 1b — Promote WIP resilience.py to tracked source

**File:** `opsswarm/resilience.py` (already written, untracked)

The WIP file at `opsswarm/resilience.py` is reviewed and complete. Add it to git:

```bash
git add opsswarm/resilience.py
```

Review checklist:
- [ ] `DependencyError` hierarchy is sound (base + all subclasses)
- [ ] `CircuitBreaker` state machine: CLOSED→OPEN→HALF_OPEN→CLOSED transitions are correct
- [ ] `CircuitBreaker.raise_if_open()` raises `DependencyCircuitOpen` not bare `Exception`
- [ ] `idempotent_retry()` never retries writes (`_is_idempotent=False` path)
- [ ] `idempotent_retry()` honours `RateLimited.retry_after`
- [ ] `AmbiguousWriteOutcome.__init__` calls `metrics.record_ambiguous_write()`
- [ ] `for_comment()` returns no raw exception text, no file paths, no tokens

---

## Phase 2: Wire circuit-breaker into GitHubClient

**Goal:** `GitHubClient` owns a `CircuitBreaker`; circuit state is visible; typed exceptions are raised from `_req`.

### Task 2a — Add circuit-breaker to `GitHubClient`

**File:** `opsswarm/github_client.py`

In `GitHubClient.__init__`, after `self.client = httpx.AsyncClient(...)`:

```python
from .resilience import (
    AmbiguousWriteOutcome,
    AuthDenied,
    DependencyCircuitOpen,
    DependencyTimeout,
    DependencyUnavailable,
    InvalidDependencyResponse,
    RateLimited,
    CircuitBreaker,
    idempotent_retry,
)

# Circuit-breaker for this client instance
self._circuit = CircuitBreaker(
    name=f"github:{self.repo}",
    failure_threshold=circuit_failure_threshold,
    recovery_timeout=30.0,
    half_open_max_calls=1,
)
```

Add constructor parameters:
```python
def __init__(
    self,
    token: str,
    repo: str,
    base_url: str = _DEFAULT_ORIGIN,
    allowed_origins: frozenset[str] | None = None,
    verify: bool | str = True,
    *,
    profile: str = _DEFAULT_PROFILE,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    circuit_failure_threshold: int = 5,
):
```

Add property:
```python
@property
def circuit_breaker(self) -> CircuitBreaker:
    """The circuit-breaker for this client instance."""
    return self._circuit
```

Acceptance criteria:
- [ ] `client.circuit_breaker` is a `CircuitBreaker` instance
- [ ] `client.circuit_breaker.name` is `"github:{repo}"`
- [ ] Constructor is backward-compatible: existing `GitHubClient(token, repo)` works

---

### Task 2b — Rewrite `_req` with typed exceptions and retry

**File:** `opsswarm/github_client.py`

Replace the current `_req` method. The new version:

1. Generates a correlation ID.
2. Checks circuit via `await self._circuit.call(inner())` where `inner()` does the httpx request.
3. On httpx `HTTPStatusError`:
   - 401/403 → raise `AuthDenied`
   - 429 → parse `Retry-After` / `X-RateLimit-Reset`, raise `RateLimited`
   - 4xx (not 429) → raise `InvalidDependencyResponse`
   - 5xx → raise `DependencyUnavailable`
4. On `httpx.TimeoutException` → raise `DependencyTimeout`
5. On JSON decode error → raise `InvalidDependencyResponse`
6. All exceptions carry `correlation_id`, `operation`, `idempotency_key`.
7. **All write operations** (`comment`, `set_labels`, `close_issue`, `create_issue`, `create_branch`, `open_pr`, `merge_pr`) use `idempotent_retry(..., _is_idempotent=False)` so a failure becomes `AmbiguousWriteOutcome`.
8. **Read operations** (`get_issue`, `get_pr_status`, `permission`) use `idempotent_retry(..., _is_idempotent=True)`.

The `idempotent_retry` function in `resilience.py` already handles the retry loop
and raising `AmbiguousWriteOutcome` for non-idempotent failures.

Simplified rewrite of `_req` and write methods:

```python
async def _req(self, method: str, path: str, **kwargs) -> Any:
    """Internal request — raises typed DependencyError on failure."""
    corr_id = new_correlation_id()
    op = f"{method} {path}"

    async def inner():
        r = await self.client.request(method, path, **kwargs)
        return r

    async def call_with_circuit():
        return await self._circuit.call(
            inner(),
            correlation_id=corr_id,
            operation=op,
        )

    try:
        r = await call_with_circuit()
        r.raise_for_status()
        if r.content:
            return r.json()
        return None
    except DependencyCircuitOpen:
        raise  # already typed
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        retry_after: float | None = None
        reset_at: datetime | None = None
        if status == 429:
            retry_after = self._parse_retry_after(e.response.headers)
            reset_ts = e.response.headers.get("X-RateLimit-Reset")
            if reset_ts:
                try:
                    reset_at = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
                except (ValueError, TypeError):
                    pass
            raise RateLimited(
                f"GitHub API rate limited",
                retry_after=retry_after or 60.0,
                reset_at=reset_at,
                correlation_id=corr_id,
                operation=op,
                status_code=429,
            )
        if status in (401, 403):
            raise AuthDenied(
                f"GitHub API returned {status}",
                correlation_id=corr_id,
                operation=op,
                status_code=status,
            )
        if 400 <= status < 500:
            raise InvalidDependencyResponse(
                f"GitHub API returned client error {status}",
                correlation_id=corr_id,
                operation=op,
            )
        # 5xx
        raise DependencyUnavailable(
            f"GitHub API server error {status}",
            status_code=status,
            correlation_id=corr_id,
            operation=op,
        )
    except httpx.TimeoutException:
        raise DependencyTimeout(
            f"GitHub API timed out",
            correlation_id=corr_id,
            operation=op,
            is_transport_error=False,
        )
    except Exception as e:
        # Malformed JSON or other unexpected error
        raise InvalidDependencyResponse(
            f"GitHub API unexpected error: {e!s}",
            correlation_id=corr_id,
            operation=op,
        )

def _parse_retry_after(self, headers: httpx.Headers) -> float:
    val = headers.get("Retry-After", "")
    try:
        return float(val)
    except (ValueError, TypeError):
        return 60.0  # fallback
```

Then rewrite write methods to use `idempotent_retry`:

```python
async def comment(self, number: int, body: str):
    key = f"comment:{self.repo}:{number}:{hash(body)}"
    async def do():
        return await self._req(
            "POST", f"/repos/{self.repo}/issues/{number}/comments",
            json={"body": body}
        )
    return await idempotent_retry(
        do,
        operation=f"POST /repos/{self.repo}/issues/{number}/comments",
        idempotency_key=key,
        max_attempts=self._max_attempts,
        base_delay=self._base_delay,
        max_delay=self._max_delay,
        _is_idempotent=False,
    )
```

Acceptance criteria:
- [ ] `PermissionError` is NEVER raised by `GitHubClient` after this change
- [ ] 429 raises `RateLimited` with `retry_after` and `reset_at`
- [ ] 401/403 raises `AuthDenied`
- [ ] 5xx raises `DependencyUnavailable`
- [ ] Timeout raises `DependencyTimeout`
- [ ] Write failures (timeout / 429 / 5xx) raise `AmbiguousWriteOutcome`
- [ ] Circuit-breaker trips after `circuit_failure_threshold` consecutive failures
- [ ] When circuit is OPEN, `DependencyCircuitOpen` is raised before any HTTP request

---

### Task 2c — Update `api.py` circuit-breaker exposure (optional readiness endpoint)

**File:** `opsswarm/api.py`

Optionally expose circuit state via the `/metrics` endpoint (already covered by
`metrics.to_prometheus()` emitting `opsswarm_circuit_state` when `record_circuit_state`
is called). No code change required if `to_prometheus()` is called regularly.

Add to `/health` or a new `/ready` endpoint:

```python
@app.get("/ready")
async def ready():
    circuit_state = gh.circuit_breaker.state
    return {"ok": circuit_state != "OPEN", "circuit_state": circuit_state}
```

Acceptance criteria:
- [ ] `/ready` returns `{"ok": true}` when circuit is CLOSED or HALF_OPEN
- [ ] `/ready` returns `{"ok": false, "circuit_state": "OPEN"}` when circuit is OPEN

---

## Phase 3: Update legacy fault tests

**Goal:** The two existing fault-injection tests that assert `PermissionError` are updated to assert the correct typed exception.

### Task 3a — Update `test_github_api_error.py`

**File:** `tests/faults/test_github_api_error.py`

```python
# Before:
with pytest.raises(PermissionError):
    await client.get_issue(1)

# After:
with pytest.raises(DependencyUnavailable) as exc_info:
    await client.get_issue(1)
assert exc_info.value.status_code == 500
```

Also add test for write path:
```python
async def test_github_500_raises_ambiguous_on_write():
    """POST 500 on write raises AmbiguousWriteOutcome, not DependencyUnavailable."""
    client = GitHubClient(token="tok", repo="owner/repo")
    async def return_500(*args, **kwargs):
        r = httpx.Response(500, content=b"Internal Server Error")
        r.request = httpx.Request("POST", "https://api.github.com/repos/owner/repo/issues")
        return r
    with patch.object(client.client, "request", side_effect=return_500):
        with pytest.raises(AmbiguousWriteOutcome):
            await client.create_issue("title", "body", [])
```

### Task 3b — Update `test_github_rate_limit.py`

**File:** `tests/faults/test_github_rate_limit.py`

```python
# Before:
with pytest.raises(PermissionError):
    await client.get_issue(1)

# After:
with pytest.raises(RateLimited) as exc_info:
    await client.get_issue(1)
assert exc_info.value.retry_after > 0
assert exc_info.value.status_code == 429
```

Add write-path test:
```python
async def test_github_429_raises_ambiguous_on_write():
    client = GitHubClient(token="tok", repo="owner/repo")
    async def return_429(*args, **kwargs):
        r = httpx.Response(429, content=b"Too Many Requests", headers={"Retry-After": "5"})
        r.request = httpx.Request("POST", "https://api.github.com/repos/owner/repo/issues/1/comments")
        return r
    with patch.object(client.client, "request", side_effect=return_429):
        with pytest.raises(AmbiguousWriteOutcome):
            await client.comment(1, "hello")
```

Acceptance criteria:
- [ ] `pytest tests/faults/test_github_api_error.py tests/faults/test_github_rate_limit.py -v` passes
- [ ] All 28 tests in `test_github_typed_failures.py` pass

---

## Phase 4: Update ADR index

**File:** `docs/adr/README.md`

Add to the ADR index table:
```
| [030](ADR-030_TYPED_DEPENDENCY_RESILIENCE.md) | Typed Dependency Errors, Idempotent Retry, and Circuit Breaker | Proposed | #75 typed errors, idempotent retry, circuit-breaker, metrics |
```

---

## Phase 5: Update orchestrator exception handling (no code change needed)

**Goal:** Verify the orchestrator's existing `ambiguous` handling is compatible.

The orchestrator at `orchestrator.py:518` handles `ambiguous=True` from `run.execution`.
After Phase 2, `AmbiguousWriteOutcome` propagates from `S.execute_recovery` in
`skill_logic.py` when a write fails and the response is lost. The existing handler
is already correct:

```python
if run.execution.ambiguous:
    run.decision = DecisionRequest(...)
    await self._set_state(run, RunState.WAITING_DECISION)
    await self.github.comment(run.issue_number, decision_request(run))
```

Review checklist:
- [ ] `skill_logic.py` catches typed exceptions and sets `execution.ambiguous = True`
- [ ] The orchestrator's `except Exception` at `orchestrator.py:411` does not swallow `AmbiguousWriteOutcome`
- [ ] No new `except` blocks are needed

---

## Phase 6: End-to-end smoke test

Run the full test suite:

```bash
pnpm run test   # or: pytest tests/ -v --timeout=60
```

Expected results:
- All existing tests pass (no regressions)
- All 28 tests in `test_github_typed_failures.py` pass
- Both updated legacy fault tests pass
- `test_metrics.py` passes (new metric families)
- `test_github_api_error.py` and `test_github_rate_limit.py` pass with typed assertions

---

## Hotspot Warning

`opsswarm/github_client.py` is modified by both this issue and the active branch
`feat/ghes-api-origins` (already merged to staging). The `_req()` rewrite in Phase 2
must be applied after the `feat/ghes-api-origins` branch content is stable. Coordinate
the Phase 2 implementation with the branch owner to avoid merge conflicts.

Flagged on kanban card `t_0d1e70cc` via `kanban_comment`.
