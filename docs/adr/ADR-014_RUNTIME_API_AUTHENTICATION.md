# ADR-014: Runtime API Authentication, Scopes, and Ingress Controls

**Date:** 2026-09-29
**Task:** t_02978d74
**Source:** GitHub Issue #21 — "[Security][P0] Authenticate and authorize Runtime API and monitoring ingress"
**Status:** ACCEPTED

---

## Decision Summary

| ID  | Decision | Rationale |
|-----|----------|-----------|
| D1  | HMAC-SHA256 bearer tokens over env var; no repo secrets; rotation via env reload | FastAPI-native; constant-time comparison; compatible with k8s secrets / Vault; rotation is zero-downtime |
| D2  | Four endpoint scopes: `opsswarm:read`, `opsswarm:write`, `opsswarm:monitor`, `opsswarm:admin` | Minimum viable privilege separation; maps 1:1 to endpoint categories |
| D3  | 401 for missing/invalid token; 403 for valid token + insufficient scope; `/health` always public | Aligns with RFC 9110; preserves liveness probe contract |
| D4  | Fail-closed: required auth config absent in production → 503 at startup + per-request 503 | Prevents silent misconfiguration; degrades visibly, not invisibly |
| D5  | Monitoring ingress: max body 64 KB, 20 req/min per source IP, HMAC-SHA256 or scoped bearer token | Protects GitHub issue creation from abuse; rate-limit gates self-inflicted DoS |
| D6  | GitHub webhook HMAC is independent auth domain; precedence: HMAC verified → trusted event, then human authority evaluated inside handler | Webhook trust is derived from GitHub infrastructure, not the runtime API key |

---

## ADR-014-1: Authentication Mechanism

### Status: ACCEPTED

### Context

Issue #21 identifies that `opsswarm/api.py` exposes `/runs/**` and `/hooks/monitoring` without application-layer authentication. The service binds to `127.0.0.1:8088` via systemd (production deployment assumes a reverse proxy in front). GitHub webhook HMAC is validated only for `/webhooks/github`.

Requirements from issue #21:
- Explicit mechanism compatible with existing Python/FastAPI service.
- No repository secrets.
- Credential rotation support.
- Fail-closed on missing required config in production.
- Keep GitHub webhook HMAC independent.

### Decision

**HMAC-SHA256 bearer tokens delivered via environment variable, not repository config.**

#### Credential source

| Env var | Required? | Purpose |
|---------|----------|---------|
| `OPSWARM_RUNTIME_SECRET` | Yes (production) | Master secret used to generate/validate HMAC-SHA256 bearer tokens. Loaded at startup. |
| `OPSWARM_API_KEY_<SCOPE>` | No | Optional pre-shared scoped keys (e.g. `OPSWARM_API_KEY_READ`, `OPSWARM_API_KEY_MONITOR`). Loaded at startup. Operators may use these as bearer tokens directly. |

The secret MUST NOT appear in any repository file (`.env`, config YAML, CI, or code). Operators inject it via:
- Kubernetes Secret mounted as env
- HashiCorp Vault / AWS Secrets Manager injected at runtime
- systemd `EnvironmentFile` owned outside the repo (already implied by existing `EnvironmentFile=/opt/opsswarm/.env`)

#### Token format

```
Authorization: Bearer <scope>:<hmac_hex>
```

Where:
- `<scope>` is one of `opsswarm:read`, `opsswarm:write`, `opsswarm:monitor`, `opsswarm:admin`
- `<hmac_hex>` = HMAC-SHA256 of `<http_method>:<path>:<unix_timestamp>` using `OPSWARM_RUNTIME_SECRET`
- Token is valid for 5 minutes (sliding window)
- Timestamp must be within `±60 s` of server clock (anti-replay)

#### Validation steps (pseudocode)

```
1. Extract "Bearer <token>" from Authorization header.
2. Parse <scope>:<hmac_hex>.
3. Derive <http_method>:<path>:<timestamp> from the live request.
4. Compute expected_hmac = HMAC-SHA256(secret, "<method>:<path>:<timestamp>").
5. If computed HMAC != presented HMAC → 401.
6. If timestamp outside ±60 s window → 401 (replay or clock skew).
7. If requested endpoint scope not covered by token scope → 403.
8. Otherwise → pass request through.
```

#### Optional pre-shared key path

Operators who prefer static tokens (simpler ops, rotate by regeneration) may set `OPSWARM_API_KEY_<SCOPE>` to an opaque bearer value. The validator accepts either path: HMAC-derived token OR exact match against any scoped pre-shared key.

#### Fail-closed on missing required config

- At FastAPI startup (` lifespan` or module init): if `OPSWARM_RUNTIME_SECRET` is absent AND no `OPSWARM_API_KEY_*` vars are set AND `APP_ENV=production`, raise `RuntimeError("OPSWARM_RUNTIME_SECRET or OPSWARM_API_KEY_* required in production")` — app refuses to start.
- Per-request: if auth config is present but validation fails for any reason, return `401` (never fall through to unauthenticated access).
- Health endpoint (`/health`) is exempt and always returns `{"ok": true}` regardless of auth config state — preserving Kubernetes liveness/readiness contract.

#### Why HMAC bearer tokens (not mTLS / SSO / JWT)

| Mechanism | FastAPI compatibility | Rotation | No repo secrets | Operator complexity |
|-----------|----------------------|----------|------------------|---------------------|
| HMAC bearer (chosen) | Native, <10 LoC | Zero-downtime (env reload) | Yes | Low |
| mTLS | Requires cert mgmt; not always available behind reverse proxy | Rotation via cert rotation | Yes | High |
| SSO/OIDC | Requires external IdP; enterprise-only | Via IdP | Yes | High |
| JWT (signed) | Library needed; secret management same problem | Token expiry helps | Yes | Medium |

The systemd service binds to localhost; reverse proxy (nginx / envoy) terminates TLS and can inject `X-Forwarded-*` headers. The chosen mechanism works for both direct localhost and proxied deployments.

---

## ADR-014-2: Authorization Scopes

### Status: ACCEPTED

### Context

The issue requires minimum four authorization categories: read run/evidence, monitoring trigger, resume/reconciliation, admin. Existing endpoints must be mapped without breaking the current API surface.

### Decision

Four scopes, each covering a specific endpoint category:

| Scope | Covers |
|-------|--------|
| `opsswarm:read` | `GET /runs`, `GET /runs/{issue_number}`, `GET /runs/{issue_number}/evidence`, `GET /runs/{issue_number}/checkpoint` |
| `opsswarm:write` | `POST /runs/{issue_number}/resume` |
| `opsswarm:monitor` | `POST /hooks/monitoring` |
| `opsswarm:admin` | All above + `GET /metrics` (if operator chooses to protect it) |

Scope hierarchy (cumulative):
- `opsswarm:admin` implies all other scopes.
- `opsswarm:write` does NOT imply `opsswarm:read` (read and write are separate concerns).
- `opsswarm:monitor` is strictly limited to `/hooks/monitoring` — a monitoring identity cannot read runs or trigger resume.

#### Precedent with GitHub webhook HMAC

GitHub webhook HMAC (`/webhooks/github`) is a separate authentication domain and is not subject to runtime API scopes. Once `verify_signature()` confirms the request came from GitHub, the handler delegates authorization to `gh.permission(actor)` — GitHub's own collaborator permission model. This is documented in `docs/SECURITY.md` and is unchanged.

---

## ADR-014-3: HTTP Status Code Contract

### Status: ACCEPTED

### Context

The current `api.py` uses `HTTPException(status_code=403)` for both missing credentials and insufficient credentials. RFC 9110 requires distinguishing these.

### Decision

| Condition | Status code | Detail |
|-----------|-------------|--------|
| No `Authorization` header present | `401 Unauthorized` | `{"detail": "Missing credentials"}` |
| `Authorization` header present but token invalid (bad HMAC, wrong secret, expired timestamp) | `401 Unauthorized` | `{"detail": "Invalid credentials"}` |
| Token valid but scope insufficient for endpoint | `403 Forbidden` | `{"detail": "Insufficient scope for this operation"}` |
| Run / issue not found | `404 Not Found` | (unchanged) |
| Request body over limit | `413 Content Too Large` | (see D5) |
| Rate limit exceeded | `429 Too Many Requests` | (see D5) |
| Auth config missing in production | `503 Service Unavailable` | `{"detail": "Authentication not configured"}` |

The `X-OpsSwarm-API-Key` header used by the current `api.py` is deprecated in favour of the `Authorization: Bearer` format. The `X-OpsSwarm-API-Key` path continues to work for the transition period but is not documented as the primary mechanism.

---

## ADR-014-4: Fail-Closed Deployment Behaviour

### Status: ACCEPTED

### Context

The issue requires that missing required authentication config in production results in a visible failure, not silent degradation.

### Decision

| Deployment mode | Auth config state | Behaviour |
|-----------------|-------------------|-----------|
| Production (`APP_ENV=production`) | `OPSWARM_RUNTIME_SECRET` or any `OPSWARM_API_KEY_*` absent | App raises `RuntimeError` at startup; refuses to bind port |
| Production | Config present, validation fails | Per-request `401`/`403`/`503` |
| Non-production (`APP_ENV=development` / unset) | Any state | App starts; unauthenticated requests to protected endpoints receive `401`; `/health` always OK |
| Any mode | `GITHUB_WEBHOOK_SECRET` absent | `/webhooks/github` always returns `401`; other endpoints unaffected |

`APP_ENV` defaults to `development` if unset. Operators must explicitly set `APP_ENV=production` to enforce startup-time config validation.

`/health` remains fully public and does not check auth state — preserving the liveness/readiness contract for Kubernetes, load balancers, and monitoring systems that do not carry operator credentials.

---

## ADR-014-5: Monitoring Ingress Abuse Controls

### Status: ACCEPTED

### Context

`POST /hooks/monitoring` can create a GitHub issue and start an OpsSwarm run for any caller who can reach the service. Without protections, this endpoint is an abuse vector (DoS via self-inflicted incident spam).

### Decision

| Control | Value | Rationale |
|---------|-------|-----------|
| Maximum request body | 64 KB | Monitoring payloads (PagerDuty, Datadog, etc.) are small JSON; prevents accidental large-file abuse |
| Rate limit | 20 req/min per source IP (no token) or per token (with token) | Standard operational threshold; above this is anomalous |
| Authentication | `opsswarm:monitor` scoped bearer token OR HMAC-SHA256 webhook signature (same mechanism as GitHub webhooks) | Monitoring systems that support webhook signatures use this path; others use scoped tokens |
| Response on rate limit | `429 Too Many Requests` with `Retry-After: <seconds>` header |
| Response on body size exceeded | `413 Content Too Large` |
| Response on invalid auth | `401` or `403` per D3 |

GitHub issue creation is the only side effect of this endpoint. The issue body is generated server-side from the monitoring payload — no user-controlled text is passed to GitHub without sanitisation.

---

## ADR-014-6: GitHub Webhook HMAC Independence

### Status: ACCEPTED

### Context

The existing `verify_signature()` in `opsswarm/webhook.py` validates GitHub webhook payloads using `GITHUB_WEBHOOK_SECRET`. This must remain functional and independent of the runtime API authentication mechanism.

### Decision

GitHub webhooks and runtime API calls are separate authentication domains:

```
GitHub → POST /webhooks/github
  → verify_signature(GITHUB_WEBHOOK_SECRET, body, X-Hub-Signature-256)
  → trusted event, then human authority via gh.permission()
  → scope: NOT subject to opsswarm:*

External operator / monitoring system → any /runs/* or /hooks/*
  → Authorization: Bearer <scope>:<hmac_hex>
  → subject to opsswarm scopes
```

Both mechanisms use HMAC-SHA256 but with different secrets, different trust domains, and different authorisation models. They do not interfere with each other.

---

## ADR-014-7: Migration and Rollback

### Status: ACCEPTED

### Context

The current `api.py` uses `X-OpsSwarm-API-Key` header with a single shared secret. Operators need a migration path from the current flat credential model to scoped tokens.

### Decision

#### Migration path (non-breaking)

**Phase 1 — Introduce scoped tokens (backward-compatible):**
- Deploy new `verify_scoped_bearer()` alongside existing `verify_api_key()`.
- Operators provision `OPSWARM_RUNTIME_SECRET` and start issuing scoped tokens.
- Old `X-OpsSwarm-API-Key` header still accepted for read endpoints during transition.

**Phase 2 — Enforce scoped tokens:**
- Remove `X-OpsSwarm-API-Key` acceptance from all endpoints.
- All callers must use `Authorization: Bearer` format.
- Phase 1 and 2 can be combined in a single release with a flag-day if operators coordinate.

**Phase 3 — Audit compliance (optional):**
- Emit structured access logs (JSON) with `subject`, `scope`, `endpoint`, `result` fields for SIEM integration.

#### Rollback

If the new auth layer causes operational issues:
1. Set `APP_ENV=development` to disable startup-time enforcement.
2. Restore `X-OpsSwarm-API-Key` acceptance by keeping the old `verify_api_key` dependency on sensitive endpoints.
3. Full rollback: revert to the pre-auth state (endpoints unprotected) — acceptable only in non-production; production rollback requires reverting the release.

#### No repository-secret dependency

No credentials appear in:
- `config/production.yaml` or `config/test.yaml`
- `.env.example`
- Repository CI/CD workflows
- Source code

Credentials are operator-managed via the existing `EnvironmentFile` mechanism or a secrets manager.

---

## ADR-014-8: API / Test Acceptance Contract

### Status: ACCEPTED

### Context

Issue #21 specifies explicit acceptance criteria and test requirements that the implementation must satisfy.

### Decision

#### Required security tests (`tests/security/`)

| Test | Scenario | Expected outcome |
|------|----------|-----------------|
| `test_anonymous_read_rejected` | `GET /runs` without `Authorization` header | `401`, body `"Missing credentials"` |
| `test_anonymous_monitor_rejected` | `POST /hooks/monitoring` without credentials | `401` |
| `test_read_token_cannot_write` | `POST /runs/1/resume` with `opsswarm:read` token | `403`, body `"Insufficient scope"` |
| `test_read_token_cannot_monitor` | `POST /hooks/monitoring` with `opsswarm:read` token | `403` |
| `test_monitor_token_cannot_read` | `GET /runs` with `opsswarm:monitor` token | `403` |
| `test_monitor_token_cannot_resume` | `POST /runs/1/resume` with `opsswarm:monitor` token | `403` |
| `test_admin_token_covers_all` | All above operations with `opsswarm:admin` token | `200` (subject to run existence) |
| `test_invalid_hmac_rejected` | Bearer with bad HMAC | `401`, body `"Invalid credentials"` |
| `test_expired_timestamp_rejected` | Bearer with timestamp >60 s old | `401` |
| `test_replay_detected` | Same bearer token used twice within window | First request succeeds; second returns `401` (anti-replay log) |
| `test_github_webhook_unchanged` | Valid GitHub webhook payload to `/webhooks/github` | `200`, no auth header required |
| `test_health_always_public` | `GET /health` without auth, in production mode | `200`, `{"ok": true}` |
| `test_production_startup_fails_without_secret` | `APP_ENV=production`, no `OPSWARM_RUNTIME_SECRET`, no `OPSWARM_API_KEY_*` | `RuntimeError` raised, port not bound |
| `test_rate_limit_exceeded` | >20 req/min to `/hooks/monitoring` from same IP | `429` with `Retry-After` |
| `test_body_size_limit_exceeded` | Monitoring payload >64 KB | `413` |

#### Documentation updates required

| File | Change |
|------|--------|
| `docs/SECURITY.md` | Add section "Runtime API authentication" covering D1–D5; update `/health` policy statement |
| `docs/SECURITY.md` | Add "Operational credentials" subsection in Secrets Policy |
| `README.md` or `docs/ops/` | Add "Operator authentication" deployment guide (how to provision `OPSWARM_RUNTIME_SECRET`, generate tokens, map scopes) |
| `config/production.yaml` | Add `# OPSWARM_RUNTIME_SECRET` and `# OPSWARM_API_KEY_<SCOPE>` as commented placeholders with no default values |
| `.env.example` | Add commented placeholder for `APP_ENV=production` |

---

## Consequences

### Positive
- All non-public endpoints have explicit authn/authz contracts.
- Monitoring ingress abuse is rate-limited and size-bounded.
- Missing auth config fails visibly in production, not silently.
- HMAC-SHA256 tokens are self-contained; no external IdP dependency.
- Migration from flat API key to scoped tokens is backward-compatible.

### Negative
- Operators must provision and rotate `OPSWARM_RUNTIME_SECRET` out-of-band; no built-in self-service token management UI.
- Clock skew between token issuer and server >60 s causes spurious 401; requires NTP.
- Anti-replay window requires stateful token tracking per issuer (5-min sliding window; acceptable for a single-service deployment; scales with Redis for multi-instance).

### Neutral
- `/health` remains public; monitoring/lb health checks are unaffected.
- GitHub webhook HMAC is unchanged; no migration required for the existing webhook trust model.
- FastAPI dependency injection is used; no new framework dependencies.

---

## Implementation Notes

1. Add `opsswarm/auth.py` module with `verify_scoped_bearer()`, `generate_bearer_token()`, `RateLimiter`.
2. Update `opsswarm/api.py`: replace `verify_api_key` with scoped dependency injection; add request body size validation; add middleware for rate limiting on `/hooks/monitoring`.
3. Add lifespan handler to validate auth config at startup when `APP_ENV=production`.
4. Add `tests/security/test_runtime_api_auth.py` covering all rows in ADR-014-8.
5. Update `docs/SECURITY.md` and `config/production.yaml` with auth deployment notes.
6. No changes to `opsswarm/webhook.py` or the GitHub webhook flow.
