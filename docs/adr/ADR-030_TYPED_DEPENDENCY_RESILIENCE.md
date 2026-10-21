# ADR-030: Typed Dependency Errors, Idempotent Retry, and Circuit Breaker

**Status:** Proposed
**Created:** 2026-10-05
**Issue:** [#75](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/75)
**Deciders:** dev-architect

## Context

`GitHubClient._req()` collapses every failure mode — rate-limit (429), timeout,
5xx server error, 401/403 auth denial, malformed JSON, and network transport
failure — into a bare `PermissionError`. Callers cannot:

- Distinguish a permanent auth denial from a transient 5xx — retry logic is
  impossible to implement correctly.
- Honour GitHub's `Retry-After` header on 429 responses — the rate-limit signal
  is lost.
- Reason about whether a write succeeded or not when the HTTP response is lost —
  the orchestrator's `ambiguous` flag cannot be set accurately.

There is no run-level circuit-breaker to shed load when the GitHub API is
consistently failing. An extended outage causes all in-flight runs to hammer a
dead endpoint, degrading recovery SLOM.

The orchestrator already handles `AmbiguousWriteOutcome` at
`orchestrator.py:518–525` (sets `run.execution.ambiguous=True`, posts a
decision-request comment), and `metrics.ambiguous_writes` counter already exists.
The mechanism is wired at the top; it just needs typed error propagation.

## Decision

### D1: Typed Exception Taxonomy (in `opsswarm/resilience.py`)

Every failure mode is modelled as a distinct sub-class of `DependencyError`,
each carrying structured metadata so callers and operators can programmatically
route without inspecting string messages.

```
DependencyError (base)
├── AuthDenied               — 401/403; never retry
├── RateLimited              — 429; retry_after + reset_at metadata
├── DependencyTimeout        — ConnectTimeout / ReadTimeout; bounded retry for reads
├── DependencyUnavailable    — 5xx; bounded retry for reads
├── InvalidDependencyResponse — malformed JSON / 4xx; bounded retry for reads
├── AmbiguousWriteOutcome    — write failure; route to reconciliation; never retry
└── DependencyCircuitOpen    — circuit-breaker is OPEN; fail-fast
```

`PolicyDenied` (policy denial, not a transport error) is a sibling of
`DependencyError` and is also never retried.

`for_comment()` on every exception returns a safe string for GitHub comments:
`[error_slug | ref: correlation_id]` — no raw exception text, no file paths,
no tokens.

`for_log()` returns a structured fragment with correlation ID, operation name,
and idempotency key.

### D2: Read vs. Write Retry Policy

Every GitHub method is classified idempotent (read) or non-idempotent (write):

| Category  | Methods                                                               |
|-----------|-----------------------------------------------------------------------|
| Idempotent (safe to retry) | `get_issue`, `get_pr_status`, `permission` |
| Non-idempotent (write)     | `comment`, `set_labels`, `close_issue`, `create_issue`, `create_branch`, `open_pr`, `merge_pr` |

Retry rules:

| Exception type            | Reads (idempotent) | Writes (non-idempotent) |
|---------------------------|--------------------|-------------------------|
| `RateLimited`             | Retry (honour `Retry-After`) | Raise `AmbiguousWriteOutcome` |
| `DependencyTimeout`        | Bounded retry (max 3) | Raise `AmbiguousWriteOutcome` |
| `DependencyUnavailable` (5xx) | Bounded retry (max 3) | Raise `AmbiguousWriteOutcome` |
| `InvalidDependencyResponse` (malformed JSON / 4xx) | No retry | Raise `AmbiguousWriteOutcome` |
| `AuthDenied`              | Never retry         | Never retry |
| `DependencyCircuitOpen`    | Never retry         | Never retry |
| `PolicyDenied`            | Never retry         | Never retry |

Bounded retry uses exponential backoff with full jitter: `base_delay=1.0s`,
`max_delay=30.0s`, capped at `base * 2^attempt`. On `RateLimited`, the
`Retry-After` header value (capped at `max_delay`) is used instead of backoff.

### D3: Circuit Breaker

A per-`GitHubClient` circuit-breaker (`CircuitBreaker`, `opsswarm/resilience.py`)
protects against cascading failures when the GitHub API is consistently failing.

State machine: `CLOSED → OPEN → HALF_OPEN → CLOSED`

- **CLOSED**: normal operation; consecutive failures are counted.
- **OPEN**: fail-fast; every call raises `DependencyCircuitOpen` immediately.
  Transitions to HALF_OPEN after `recovery_timeout` (default 30 s).
- **HALF_OPEN**: probe; `half_open_max_calls` (default 1) calls are allowed
  through. Success → CLOSED; failure → OPEN.

Constructor parameters (all overridable via `GitHubClient` constructor):

```
failure_threshold:  5        — consecutive failures before OPEN
recovery_timeout:  30.0 s   — wait before half-open probe
half_open_max_calls: 1       — probes allowed in HALF_OPEN
```

The circuit state is exposed via:
- `GitHubClient.circuit_breaker` property (returns the `CircuitBreaker` instance).
- `CircuitBreaker.snapshot()` → `{"name", "state", "consecutive_failures", ...}`.
- `metrics.record_circuit_state(name, state)` — emitted to Prometheus endpoint.
- `DependencyCircuitOpen.for_comment()` and `for_log()` for operator visibility.

### D4: Idempotency Key Integration

`AmbiguousWriteOutcome` carries an `idempotency_key` field. The orchestrator
uses this key to route the failed write to reconciliation rather than blindly
retry. The existing `run.execution.ambiguous = True` path (orchestrator.py:518)
is triggered when `AmbiguousWriteOutcome` propagates from the skill layer.

### D5: Metrics

New metric families added to `Metrics` and the Prometheus exporter:

| Metric                                 | Labels               | Description                                |
|----------------------------------------|----------------------|--------------------------------------------|
| `opsswarm_dependency_retries_exhausted_total` | `operation`         | Read retry exhausted; last exception propagated |
| `opsswarm_circuit_state`               | `dependency`, `state`| Circuit state transitions (CLOSED/OPEN/HALF_OPEN) |
| `opsswarm_execution_ambiguous_total`    | — (existing)         | Write outcome ambiguous; routed to reconciliation (already exists as `ambiguous_writes`) |

`record_dependency_retry_exhausted(operation)` and `record_circuit_state(name, state)`
are added to `Metrics`. `record_ambiguous_write()` already exists.

### D6: Backward Compatibility

- `GitHubClient` constructor gains `max_attempts` (default 3), `base_delay`
  (default 1.0), `max_delay` (default 30.0), `circuit_failure_threshold`
  (default 5) parameters. All have sensible defaults; existing direct construction
  is unaffected.
- The two existing fault-injection tests in `tests/faults/` that assert
  `PermissionError` on 429 and 500 are updated to assert the new typed
  exceptions (`RateLimited` / `DependencyUnavailable`).
- `PermissionError` is no longer raised by `GitHubClient`. Any caller that
  catches `PermissionError` from `GitHubClient` is updated to catch the
  appropriate typed exception.

## Consequences

- **Positive**: Typed exceptions enable precise caller-side routing (retry /
  reconcile / fail-fast). Rate-limit backoff respects GitHub's `Retry-After`.
  Circuit breaker prevents cascading failure. All failure metadata is
  structured and safe for operator-facing output.
- **Negative**: `PermissionError` is removed from `GitHubClient` public surface.
  Callers (existing fault tests) must be updated. This is a breaking change
  for any external code that constructs `GitHubClient` and catches `PermissionError`.
- **Neutral**: The WIP `opsswarm/resilience.py` and
  `tests/faults/test_github_typed_failures.py` are the authoritative
  implementation reference. The existing two legacy fault tests are updated
  to assert typed exceptions. No changes to the orchestrator's top-level
  `ambiguous` handling are required — it already exists and is correct.

## Implementation Phases

See `docs/guides/ISSUE_75_IMPLEMENTATION_PLAN.md` for the phased task breakdown.

---

*This ADR is informed by: `opsswarm/github_client.py:338–364` (current `_req()`),
`opsswarm/orchestrator.py:518–525` (ambiguous write handling),
`opsswarm/metrics.py` (existing metric families),
`opsswarm/resilience.py` (WIP — authoritative implementation reference),
`tests/faults/test_github_typed_failures.py` (WIP — authoritative test suite).*
