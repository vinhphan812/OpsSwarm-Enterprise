# ADR-014-2: Proxy-Aware Ingress for /hooks/monitoring

**Status:** accepted
**Supersedes:** ADR-014 §D5 (partial)
**Parent ADR:** [ADR-014 Runtime API Authentication](./ADR-014_RUNTIME_API_AUTHENTICATION.md)
**Issue:** [#85](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/85)
**Date:** 2026-10-05

---

## Context

`POST /hooks/monitoring` used a naive IP extractor that trusted the
`X-Forwarded-For` and `X-Real-IP` headers unconditionally:

```python
# BEFORE (vulnerable — ADR-014 §D5)
source_ip = (
    request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    or request.headers.get("x-real-ip", "")
    or "anonymous"
)
```

A direct attacker (not behind a proxy) can rotate `X-Forwarded-For` on
every request, effectively bypassing the per-IP rate limit entirely.
In addition, `_SimpleRateLimiter._hits` had unbounded cardinality: once a
new key was added it was never evicted, allowing a memory-exhaustion vector
when the endpoint is flooded with random spoofed IPs.

---

## Decision

### D1 — Default: direct IP, no header trust

Without explicit configuration, the system **must not** trust any
`X-Forwarded-For` or `X-Real-IP` header.  `request.client.host` is used
directly as the rate-limit key.  This is the safest possible default and
matches the behaviour of a uvicorn process bound directly to the Internet.

### D2 — Trusted-proxy opt-in via config

An operator may add trusted proxies to the monitoring config:

```yaml
monitoring:
  trusted_proxies:
    - "10.0.0.0/8"      # internal network
    - "172.16.0.0/12"   # internal network
  max_proxy_hops: 4     # max X-Forwarded-For chain length to accept
```

When `trusted_proxies` is non-empty and the **immediate peer**
(`request.client.host`) belongs to one of the configured CIDR ranges, the
system parses the `X-Forwarded-For` chain (up to `max_proxy_hops` entries)
and returns the leftmost address that is **not itself** a trusted proxy.
If every address in the chain is a trusted proxy, the peer address is used.

If the immediate peer is **not** in the allowlist, headers are ignored —
the same as D1.  This prevents a "proxy chain spoofing" attack where an
attacker claims to be behind trusted proxies.

### D3 — Authenticated-identity rate-limit key as fallback

After successful bearer authentication, the verified `opsswarm:*` scope
is stored in `request.state.opsswarm_scope`.  The scope identity
(`scope:opsswarm:monitor`, etc.) is OR'd into the rate-limit bucket
alongside the IP identity.  Both share the same sliding window quota.
This gives authenticated callers a stable quota independent of network
origin or header spoofing.

### D4 — Bounded limiter state (N-bucket cap + LRU eviction)

`_SimpleRateLimiter` now accepts a `max_buckets` constructor parameter
(default 10 000).  When a new key arrives and the cap is reached, the
least-recently-used entry (smallest timestamp across all keys) is evicted
before the new entry is added.  Expired entries continue to be pruned
per-key on every `is_allowed()` call.

```yaml
monitoring:
  rate_limit_buckets_max: 10000  # cap on in-memory state cardinality
```

### D5 — Deployment documentation

| Deployment pattern | Configuration |
|---|---|
| **Direct uvicorn** (no reverse proxy) | `trusted_proxies: []` (default) — headers ignored, D1 applies |
| **nginx in front** | Add nginx's IP (or Docker network CIDR) to `trusted_proxies`; nginx strips and sets `X-Forwarded-For` |
| **Traefik v2** | Same as nginx; Traefik sets `X-Forwarded-For` from the incoming connection |
| **k8s with Ingress-NGINX** | Add the ingress controller pod CIDR (typically `10.244.0.0/16` or similar) to `trusted_proxies` |
| **Cloud load balancer** (AWS ALB, GCP Cloud Load Balancing) | Add the LB's egress CIDR to `trusted_proxies`; consult cloud provider docs for the specific range |

> **Warning:** Never add public IP ranges (e.g. `0.0.0.0/0`) to
> `trusted_proxies`.  Doing so would re-introduce the vulnerability this ADR
> closes.

---

## Consequences

### Positive
- `X-Forwarded-For` rotation attacks are neutralised for direct clients.
- Memory exhaustion via rate-limit state flooding is bounded.
- Authenticated callers have a stable quota regardless of network topology.
- Configuration is additive — no breaking API changes.

### Negative
- In multi-proxy deployments, the operator must keep `trusted_proxies`
  current as infrastructure changes.
- The in-process rate limiter is still single-process; multi-instance
  deployments require a shared backend (Redis) to share state.

### Migration path
1. Deploy with `trusted_proxies: []` (D1 default) — no behaviour change.
2. Identify the IP range of your reverse proxy / ingress controller.
3. Update `config/production.yaml` with the correct CIDR(s) and re-deploy.

---

## Configuration reference

```yaml
# config/production.yaml
monitoring:
  trusted_proxies:           # default: [] (D1, headers never trusted)
    - "10.0.0.0/8"
    - "172.16.0.0/12"
  max_proxy_hops: 4          # max X-Forwarded-For chain length (default: 4)
  rate_limit_buckets_max: 10000  # max distinct rate-limit keys (default: 10000)
```

---

## Implementation

| File | Change |
|---|---|
| `opsswarm/config.py` | `DEFAULT_MONITORING` + `get_monitoring()` |
| `opsswarm/auth.py` | `_SimpleRateLimiter` bounded; `_get_real_client_ip()` + helpers |
| `opsswarm/api.py` | `_peek_scope()`; `monitoring_event` uses `_get_real_client_ip` + scope key |
| `docs/adr/ADR-014-2_PROXY_AWARE_INGRESS.md` | This document |
| `tests/security/test_runtime_api_auth.py` | Security tests for #85 acceptance criteria |
