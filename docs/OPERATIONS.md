# Operations

## Human-created incident

Open a GitHub Issue using the supplied incident template. Keep the `opsswarm` label. OpsSwarm starts after the
`issues.opened` webhook.

## Machine-created incident

```bash
curl -X POST http://localhost:8088/hooks/monitoring \
  -H 'Content-Type: application/json' \
  -d '{
    "title":"[SEV2] booking-api failures",
    "service":"booking-api",
    "symptom":"HTTP 5xx > 30%",
    "customer_impact":"customers cannot confirm bookings",
    "environment":"production",
    "severity_label":"sev:2"
  }'
```

## Human decision

When the Issue has `state:waiting-approval`, `state:waiting-decision`, or `state:waiting-input`, reply in the Issue.

```text
/opsswarm approve rollback
/opsswarm investigate check pending database transactions first
/opsswarm provide settlement has completed; downtime up to 5 minutes is allowed
/opsswarm abort
```

Only explicit `/opsswarm` commands carry decision authority. A comment such as "rollback looks fine" is stored as
information and cannot authorize a side effect.

## Evidence

```text
runtime-data/runs/*.json
runtime-data/evidence/*.jsonl
```

The GitHub Issue remains the user-visible system of record; local evidence provides machine-readable provenance.

## Telemetry

```bash
curl -H "Authorization: Bearer $OPSWARM_RUNTIME_TOKEN" http://localhost:8088/metrics
```

`GET /metrics` returns Prometheus text-format metrics. It requires `opsswarm:admin`
bearer authentication. Expose only behind a reverse proxy or network policy; the
endpoint exposes internal operational state and must not be world-readable in
production.

The `/health` endpoint (`GET /health`) requires no authentication and always
returns `{"ok": true, "version": "<version>"}` — safe for liveness probes and load
balancers.

For the production integration boundary, Prometheus scrape configuration, metric definitions, and
external operations ownership (dashboards, alerts, tracing, persistence), see the
[Metrics Integration Guide](guides/METRICS_INTEGRATION.md).

## Dependency failures (GitHub API)

When GitHub API calls fail, OpsSwarm raises typed exceptions so the failure mode is
immediately identifiable.  These are visible in logs and the `/metrics` endpoint.

### Failure taxonomy

| Error slug | HTTP / transport cause | Retry? | Operator action |
|---|---|---|---|
| `auth_denied` | 401 / 403 | Never | Check `GITHUB_TOKEN` is valid and has `repo` scope |
| `rate_limited` | 429 | After `Retry-After` delay | Check `opsswarm_github_api_remaining` in metrics; wait |
| `dependency_timeout` | ConnectTimeout / ReadTimeout / pool exhausted | Bounded (3x) for GETs only | Check GitHub status page; circuit may open |
| `dependency_unavailable` | 5xx | Bounded (3x) for GETs only | Check GitHub status page; circuit may open |
| `invalid_response` | 4xx (non-auth), malformed JSON | Never | Likely a code bug — check logs for correlation ID |
| `ambiguous_write` | Write response lost (network drop mid-response) | Never | Check GitHub directly; issue may be open |
| `circuit_open` | Consecutive failures exceeded threshold | Automatic after TTL | Check `opsswarm_circuit_state_transitions` metric |

### Circuit-breaker

The GitHub client has a per-repo circuit-breaker.  After 5 consecutive failures the circuit
opens (fail-fast) for 30 seconds.  While open, every API call immediately raises
`circuit_open`.  The circuit half-opens after 30 seconds and closes on the first
successful probe call.

Monitor circuit state in Prometheus:

```
opsswarm_circuit_state_transitions{dependency="github:owner/repo",state="OPEN"}
```

### Ambiguous writes

When a write (POST / PATCH / PUT) fails with network loss, OpsSwarm raises
`ambiguous_write` instead of retrying.  The write may or may not have succeeded.
Check GitHub directly to determine the actual state, then update or close the issue manually.

### Metrics to watch

```bash
# Rate-limit occurrences
opsswarm_rate_limited_total

# Circuit-breaker transitions
opsswarm_circuit_state_transitions{state="OPEN"}
opsswarm_circuit_state_transitions{state="HALF_OPEN"}

# Retry exhaustion (all attempts failed — investigate)
opsswarm_dependency_retry_exhausted_total{operation="GET:/repos/..."}

# Ambiguous writes (writes whose outcome is unknown — check GitHub)
opsswarm_execution_ambiguous_total

## Container deployment

OpsSwarm ships as an OCI image (`Dockerfile` at repo root). The image is built
from the canonical wheel, runs as non-root (uid 10001), and supports a read-only
root filesystem with explicit write targets.

### Building the image

```bash
docker build -f Dockerfile -t opsswarm:local .
```

### Running with a read-only root filesystem

```bash
docker run --read-only \
  --tmpfs /tmp:rw \
  --tmpfs /var/run:rw \
  -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw \
  -p 8080:8080 \
  opsswarm:local
```

The pre-created `/app/runtime-data/` and `/var/lib/opsswarm/` directories inside the
image are owned by `appuser` and survive on the read-only root. For persistent evidence
store, bind a host volume:

```bash
docker run --read-only \
  --tmpfs /tmp:rw --tmpfs /var/run:rw \
  -v /data/opsswarm:/var/lib/opsswarm:rw \
  -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw \
  -p 8080:8080 \
  opsswarm:local
```

### Environment variables

| Variable                  | Default | Description                                          |
|---------------------------|---------|------------------------------------------------------|
| `PORT`                    | `8080`  | Port uvicorn binds                                  |
| `OPSWARM_OPENCLAW_BIN`    | empty   | Absolute path to OpenClaw binary (required at runtime) |

### OpenClaw runtime

OpenClaw is NOT embedded in the image layers. Set `OPSWARM_OPENCLAW_BIN` to the
absolute path of the OpenClaw binary on the host (bind mount) or in a Kubernetes
sidecar volume. This allows OpenClaw to be upgraded independently of the OpsSwarm
image without rebuilding the container.

### Health endpoint

`GET /health` returns `{"ok": true, "version": "2.2.0", "architecture": "openclaw+github"}`.
The Docker `HEALTHCHECK` instruction probes this endpoint every 30 s. For Kubernetes,
use an HTTP `GET` readiness probe on port 8080 path `/health` with a 10 s timeout.

### Graceful shutdown

The container entrypoint uses `exec "$@"` so that SIGTERM sent by `docker stop` or
`kubectl delete pod` reaches uvicorn directly (PID 1). Set
`--graceful-shutdown-timeout` on uvicorn or configure the pod's
`terminationGracePeriodSeconds` if in-flight requests need more than the
default 30 s Kubernetes termination grace period.
```
