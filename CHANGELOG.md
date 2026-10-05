# Changelog — OpsSwarm Enterprise

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] — 2026-10-05

> **v2.2.0 — OpsSwarm Enterprise "Hardened Foundation"**

This release promotes OpsSwarm Enterprise from an operational prototype to a
release-grade incident response platform. v2.2.0 closes all P0 safety gaps and
major enterprise correctness gaps identified in the Epic #1 v2.2 audit.

### Security hardening

- **ADR-028 SSRF transport boundary**: `GitHubClient` now validates that all
  HTTP(S) requests resolve to `api.github.com`, `github.com`, or configured
  allowlist hosts. Direct IP targets, internal ranges, and redirects to
  arbitrary hosts are rejected fail-closed. (Fixes #5–#8 CodeQL alerts.)
- **ADR-029 log injection prevention**: `sanitize_for_log()` and
  `sanitize_for_log_key()` are applied to all structured-log string
  interpolations in `orchestrator.py` and `github_client.py`. Token patterns,
  bearer headers, and key= value pairs are redacted before logging. (Fixes
  #5–#8 CodeQL alerts.)
- **TLS certificate verification**: `GitHubClient` now hardcodes `verify=True`
  on all HTTPX requests, eliminating the CodeQL certificate-validation alert.
- **Sanitized operator output**: raw exception text, OpenClaw stderr, Pydantic
  validation details, file paths, and tokens are never posted to GitHub
  comments. Operators receive a fixed banner + sanitised category + a
  traceable correlation ID. Full redacted traces are available in server logs.

### Architecture and governance

- **ADR-014 Runtime API authentication**: `/metrics`, `/runs`, `/runs/{n}`,
  `/runs/{n}/evidence`, and `/runs/{n}/checkpoint` are now gated behind
  scoped bearer tokens (`opsswarm:read`, `opsswarm:write`, `opsswarm:admin`).
  `/hooks/monitoring` supports both bearer token and HMAC webhook signature
  authentication. Unauthenticated access returns 401.
- **ADR-013 Trusted Capability Registry**: production capability registry
  replaces the development allowlist. Risk-scored operations are fail-closed when
  no verified capability covers the request. Stale approvals and unknown writes
  are rejected.
- **ADR-016 Governed Remediation Workflow** (ADR-015 two-phase plan):
  immediate mitigation is now a first-class governed subflow — branch → PR →
  CI → approval → merge/deploy → S7 verification — so that operational
  response does not require full RCA confidence before acting. (Closes #44.)
- **ADR-009 Evidence contract improvements**: idempotent JSONL append with
  fsync-after-write; `EvidenceStore.verify()` integrity check; tolerant mode
  for corrupt rows; deduplication strategy. Tamper-evident evidence contract
  closes #28.
- **ADR-008 Reproducible Release Policy**: locked `requirements.lock` with
  SHA-256 hashes; `pip check` enforced in CI; release artifacts verified with
  SHA256SUMS, CycloneDX SBOM, and GitHub OIDC provenance attestation.

### Observability

- **Prometheus metrics** (`/metrics`, `opsswarm:admin` scope):
  `active_runs` (gauge, per-state), `run_duration_seconds` (histogram),
  `human_gate_seconds` (histogram), `webhook_delivery_total` (counter, with
  result label), `reconciliation_outcome_total` (counter, with outcome label).
  Cardinality guards cap label-value explosion. (Closes #30.)
- **`/health` endpoint**: returns `{"ok": true, "version": "<version>",
  "architecture": "openclaw+github"}` for health probes.
- **Correlation middleware**: every request is stamped with `X-Correlation-ID`,
  `X-Request-ID`, and `X-Corr-ID` headers using an incoming value if provided
  or a freshly generated short hex ID. Structured log entries include the
  correlation ID for end-to-end trace.
- **Metrics dashboard**: `docs/opsswarm-metrics-dashboard.json` Grafana dashboard
  definition for all metric families.

### Reliability and execution

- **Bounded execution budgets**: `ExecutionBudget` enforces wall-time,
  token, and tool-call caps. Fail-closed enforcement in production execution
  path. Budget exhaustion raises `BudgetExhausted` before any side effect.
- **Checkpoint and recovery**: `orchestrator.py` emits checkpoints at
  intentional decision points. `/runs/{n}/resume` accepts a POST with auth to
  continue from the last checkpoint. Checkpoint state is recorded in evidence
  for S7 verification.
- **Structured command outcomes**: `CommandOutcome` model captures result,
  error, and recovery fields with validated schema, replacing free-form text.
- **Idempotent evidence appends**: `EvidenceStore` writes are deterministic
  and retry-safe; corrupt rows are skipped with a warning; `verify()` confirms
  all rows parse as JSON.

### Quality and CI

- **Test coverage 90%+**: gap tests covering validators, evidence models,
  API endpoints, and evidence store. Coverage is enforced in CI at 90%.
- **Skill Gates**: ADR-007 skill gate validator executes mapped skill tests.
  ADR-006 skill frontmatter contract enforced. (Closes #6.)
- **Layered CI pipeline**: `ci.yml` (lint, type-check, unit tests, coverage),
  `security.yml` (bandit, gitleaks, Semgrep, pip-audit, dependency audit),
  `skill-gates.yml` (skill contract + integration tests per skill),
  `release.yml` (wheel/sdist build, smoke, provenance attestation, draft
  GitHub Release).
- **ADR governance**: Architecture Decision Records govern all major design
  choices with status tracking (Proposed → Approved → Deprecated).

### Version canonicalization (this release)

- `opsswarm/__version__.py` is now the single authoritative version source.
  All consumers (`__init__.py`, `api.py`, `pyproject.toml`, `smoke-wheel.py`,
  `test_api.py`) derive from it. Version is `2.2.0`.

### Known limitations

- **Multi-instance HA**: not yet supported. Only single-node deployment
  profiles are tested. (#70 — post-v2.2)
- **OCI/Kubernetes deployment**: container and Helm/Kustomize deployment
  profiles are not yet shipped. (#73 — post-v2.2)
- **GitHub Enterprise Server**: custom CA certificate and GES endpoint support
  not yet verified. (#72 — v2.2 cycle, in progress)
- **Typed dependency failures**: some optional type annotations may still fail
  at runtime under exotic dependency version combinations. (#75 — in progress)

### Migration impact

- **Auth required for all `/runs` endpoints**: callers previously accessing
  `/runs` or `/runs/{n}` without credentials will receive 401. Update to
  supply a valid bearer token scoped to `opsswarm:read`. The `/health`
  endpoint remains unauthenticated for health probes.
- **Evidence path contract**: code that constructs evidence paths manually
  (rather than using `EvidenceStore.list()`) must use the flat
  `runtime-data/evidence/{run_id}.jsonl` format. The previous
  `evidence/evidence/` double-nesting is removed.
- **GitHub PAT required in production**: `GITHUB_TOKEN` environment variable
  must be set. Operations without a token will fail gracefully with a
  descriptive error rather than silently skipping effects.

---

## [2.1.0] — 2026-09-??

Initial structured import. See `git log` for the complete commit history.
