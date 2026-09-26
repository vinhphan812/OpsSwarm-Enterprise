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
curl http://localhost:8088/metrics
```

For the production integration boundary, Prometheus scrape configuration, metric definitions, and
external operations ownership (dashboards, alerts, tracing, persistence), see the
[Metrics Integration Guide](guides/METRICS_INTEGRATION.md).
