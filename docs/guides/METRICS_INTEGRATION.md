# Metrics Integration Guide

> Scope: deployer-facing integration boundary for the OpsSwarm Enterprise `/metrics` endpoint.
> This document defines what OpsSwarm provides locally and what external owners must supply for
> production-grade observability.

---

## 1. What OpsSwarm Ships (Local MVP)

OpsSwarm exposes a **single, unauthenticated Prometheus-compatible metrics endpoint**:

```
GET http://<host>:8088/metrics
Content-Type: text/plain
```

No API key, no authentication, no TLS enforcement. The endpoint is defined in
`opsswarm/api.py:43-46`.

### 1.1 Exposed Metrics

| Metric name                    | Type    | Labels     | Cardinality                                                            |
|--------------------------------|---------|------------|------------------------------------------------------------------------|
| `opsswarm_runs_total`          | Counter | `state`    | Limited to RunState enum values (TRIAGE, PLANNING, EXECUTING, etc.)    |
| `opsswarm_commands_executed`   | Counter | `outcome`  | Limited to command outcomes (approved, denied, executed, failed, etc.) |
| `opsswarm_verifications_total` | Counter | `verified` | Boolean string: "True" / "False"                                       |
| `<name>_count`                 | Gauge   | —          | One entry per recorded duration name                                   |
| `<name>_sum`                   | Gauge   | —          | Sum of durations for each name                                         |

### 1.2 Implementation Notes

- `metrics.py:27-42` renders these as Prometheus text format (no `# HELP` / `# TYPE` comments).
- Counters reset on process restart (in-memory, no persistence).
- Duration metrics record only count and sum; no histogram buckets (minimal implementation).
- The `metrics` singleton is a module-level global — suitable for single-process deployments only.

---

## 2. Prometheus Scraper Integration

### 2.1 Network Access Model

| Concern        | Status                                                                           |
|----------------|----------------------------------------------------------------------------------|
| Authentication | None (unauthenticated endpoint)                                                  |
| Authorization  | None — network-level protection required                                         |
| TLS            | Not enforced by the application; terminate TLS at the scraper or a reverse proxy |
| Port           | 8088 (configurable via `uvicorn --host ... --port`)                              |
| Bind address   | 127.0.0.1 in the systemd unit; change to `0.0.0.0` only behind a network policy  |

### 2.2 Recommended Scrape Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'opsswarm'
    static_configs:
      - targets: ['localhost:8088']          # single-instance
      # Or, for multiple replicas:
      # - targets: ['opsswarm-1:8088', 'opsswarm-2:8088']
    scrape_interval: 30s
    scrape_timeout:  15s
    metrics_path: /metrics
    # No authentication — rely on network policy or a sidecar.
```

### 2.3 Scrape Interval

- **Recommended: 30 s** — sufficient for incident-response workloads where runs last minutes to hours.
- **Minimum useful: 15 s** — captures short-lived EXECUTING state transitions.
- **Below 15 s** yields diminishing returns; increases Prometheus cardinality with no observability gain.

### 2.4 Cardinality Constraints

The current metric schema is cardinality-safe:

| Metric                                    | Unique label values (expected maximum)                    |
|-------------------------------------------|-----------------------------------------------------------|
| `opsswarm_runs_total{state=}`             | ~8 (number of RunState enum values)                       |
| `opsswarm_commands_executed{outcome=}`    | ~6 (command outcome types)                                |
| `opsswarm_verifications_total{verified=}` | 2                                                         |
| `<name>_count / _sum`                     | Bounded by `max_tasks_per_run` (50) unique duration names |

**No user-controlled label values** are exposed. Label cardinality is fixed by the enum and
outcome types, not by external input.

### 2.5 Security Boundary

```
[Prometheus] ---- network policy ---- [OpsSwarm :8088/metrics]
```

- The `/metrics` endpoint MUST NOT be exposed to untrusted networks.
- Recommended: Prometheus scraper on the same host or in the same private network segment.
- If cross-network scraping is required, place a reverse proxy (nginx, Caddy) in front of OpsSwarm
  that terminates TLS and optionally enforces IP allow-listing.
- **Do not** pass `OPSWARM_API_KEY` to Prometheus — it is not used for `/metrics` and
  introducing it would create a misleading security signal.

---

## 3. External-Owner Interfaces

The following are **not provided by OpsSwarm**; they are the responsibility of the deploying
organisation's platform/infrastructure team.

### 3.1 Dashboards

| Owner               | Action                                                                    |
|---------------------|---------------------------------------------------------------------------|
| Platform / SRE team | Import `opsswarm_*` metrics into Grafana using Prometheus as data source. |

Example Grafana PromQL queries:

```promql
# Run state distribution
sum by (state) (opsswarm_runs_total)

# Command approval rate
sum(opsswarm_commands_executed{outcome="approved"}) / sum(opsswarm_commands_executed)

# Verification pass rate
sum(opsswarm_verifications_total{verified="True"})
  /
  (sum(opsswarm_verifications_total{verified="True"}) + sum(opsswarm_verifications_total{verified="False"}))

# Average command execution duration (if recorded)
sum(opsswarm_commands_duration_sum) / sum(opsswarm_commands_duration_count)
```

OpsSwarm does **not** ship a bundled Grafana dashboard. No ADR accepts a bundled dashboard,
so none exists in the repository.

### 3.2 Alerting

| Owner               | Action                                              |
|---------------------|-----------------------------------------------------|
| Platform / SRE team | Define alerting rules in Prometheus / Alertmanager. |

Suggested alerting rules (operator-defined, not shipped):

```yaml
# opsswarm-alerts.yml
groups:
  - name: opsswarm
    rules:
      - alert: OpsSwarmHighDenialRate
        expr: |
          sum(opsswarm_commands_executed{outcome="denied"})
          / sum(opsswarm_commands_executed) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High command denial rate in OpsSwarm"

      - alert: OpsSwarmNoRunsInWindow
        expr: |
          sum(increase(opsswarm_runs_total[1h])) == 0
        for: 4h
        labels:
          severity: info
        annotations:
          summary: "No OpsSwarm runs in the last hour — system may be idle or disconnected"

      - alert: OpsSwarmHighFailureRate
        expr: |
          sum(opsswarm_commands_executed{outcome="failed"})
          / sum(opsswarm_commands_executed) > 0.1
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Command failure rate exceeds 10%"
```

### 3.3 Tracing (Distributed)

| Owner         | Action                                                                          |
|---------------|---------------------------------------------------------------------------------|
| Platform team | Instrument the Python process with OpenTelemetry and export to a trace backend. |

OpsSwarm does **not** include an OpenTelemetry exporter. The codebase has no ADR proposing one,
and no trace backend is specified in the deployment configuration. To add tracing:

1. Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` to the runtime.
2. Initialise the SDK in `opsswarm/__init__.py` or `api.py`.
3. Configure `OTEL_SERVICE_NAME=opsswarm` and `OTEL_EXPORTER_OTLP_ENDPOINT` in the environment.

This is an external integration that requires an accepted ADR before merging.

### 3.4 Persistence and Retention

| Owner                | Action                                                         |
|----------------------|----------------------------------------------------------------|
| Platform / Data team | Scrape and store metrics in Prometheus (or a compatible TSDB). |

OpsSwarm provides **no persistent metrics store**:

- Metrics are in-process (in-memory `Counter` objects from `collections`).
- Counters reset on process restart.
- There is no metrics write-ahead log or durability guarantee.
- If Prometheus goes down, data is lost for that interval.

If long-term retention is required, configure `remote_write` in Prometheus or forward to a
Thanos/Gateway/Prometheus MTSCL endpoint.

---

## 4. Repository-Owned Contract Tests

The following tests validate repository-owned metric behaviour only. They live in
`tests/unit/test_metrics.py`.

### 4.1 Current Tests

```python
def test_metrics_endpoint():
    metrics.record_run("TRIAGE")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "opsswarm_runs_total" in body
    assert 'state="TRIAGE"' in body      # Corrected: Prometheus format uses quoted labels
    assert "1" in body
```

### 4.2 Recommended Additional Contract Tests

```python
def test_metrics_all_counters_present():
    """Verify all expected counter families are always present in the output."""
    response = client.get("/metrics")
    body = response.text
    assert "opsswarm_runs_total" in body
    assert "opsswarm_commands_executed" in body
    assert "opsswarm_verifications_total" in body


def test_metrics_label_format():
    """Verify label values are properly quoted per Prometheus text format."""
    metrics.record_run("PLANNING")
    metrics.record_command("approved")
    metrics.record_verification(True)
    response = client.get("/metrics")
    body = response.text
    assert 'state="PLANNING"' in body
    assert 'outcome="approved"' in body
    assert 'verified="True"' in body


def test_metrics_no_auth_required():
    """Confirm the /metrics endpoint is accessible without API key."""
    # No Depends(verify_api_key) on the route — this is a documentation contract.
    # The absence of a 403 is the observable evidence.
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_duration_summaries():
    """Verify duration count/sum pairs are rendered."""
    metrics.record_duration("command_execution", 1.5)
    metrics.record_duration("command_execution", 2.5)
    response = client.get("/metrics")
    body = response.text
    # Note: duration names become bare metric names without prefix
    assert "command_execution_count" in body
    assert "command_execution_sum" in body
    # Sum should reflect both recorded durations
    assert "4.0" in body
```

Run with:

```bash
pytest tests/unit/test_metrics.py -v
```

---

## 5. Evidence Required to Close Issue #30

### 5.1 Repository-Owned Evidence (OpsSwarm maintainer responsibility)

| #  | Evidence                                                                                                                          | Location                                                            |
|----|-----------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| 1  | `GET /metrics` returns HTTP 200 with Prometheus-formatted body                                                                    | `tests/unit/test_metrics.py::test_metrics_endpoint`                 |
| 2  | `Content-Type: text/plain` header present                                                                                         | `tests/unit/test_metrics.py::test_metrics_endpoint`                 |
| 3  | All three counter families (`opsswarm_runs_total`, `opsswarm_commands_executed`, `opsswarm_verifications_total`) appear in output | `tests/unit/test_metrics.py::test_metrics_all_counters_present`     |
| 4  | Label values are correctly quoted                                                                                                 | `tests/unit/test_metrics.py::test_metrics_label_format`             |
| 5  | `/metrics` does not require authentication (no 403 without API key)                                                               | `tests/unit/test_metrics.py::test_metrics_no_auth_required`         |
| 6  | Duration count/sum pairs render correctly                                                                                         | `tests/unit/test_metrics.py::test_metrics_duration_summaries`       |
| 7  | OPERATIONS.md documents `curl http://localhost:8088/metrics`                                                                      | `docs/OPERATIONS.md`                                                |
| 8  | This integration guide exists and accurately describes the boundary                                                               | `docs/guides/METRICS_INTEGRATION.md`                                |
| 9  | No dashboard, alerting, or tracing is claimed in documentation                                                                    | Reviewed: `README.md`, `docs/OPERATIONS.md`, `docs/ARCHITECTURE.md` |
| 10 | systemd unit binds to `127.0.0.1:8088` (local-only by default)                                                                    | `deploy/systemd/opsswarm.service`                                   |

### 5.2 External Deployment Follow-up (NOT part of #30 close criteria)

The following are operator/platform responsibilities and must not block #30:

- [ ] Prometheus scrape job configured against `/metrics`
- [ ] Grafana dashboard created (operator-defined PromQL, not shipped)
- [ ] Alerting rules defined and wired to Alertmanager
- [ ] TLS termination / reverse proxy in front of `/metrics` (if exposed)
- [ ] `remote_write` retention policy configured for long-term storage
- [ ] OpenTelemetry tracing exporter added (requires ADR and new dependency)

### 5.3 Close Criteria Summary

Issue #30 is **ready to close** when:

1. All 10 repository-owned evidence items above are verified and passing.
2. This document (`docs/guides/METRICS_INTEGRATION.md`) has been committed.
3. `docs/OPERATIONS.md` has been updated to reference this guide (optional but recommended).
4. The external deployment follow-up items above are tracked separately (Jira card, runbook, etc.)
   and **do not** block the issue close.

**Do not close the issue or push from this task.** The implementing agent produces the evidence;
a human or reviewer closes the issue after validating the checklist.

---

## 6. Change Log

| Date       | Change                            | Author |
|------------|-----------------------------------|--------|
| 2026-09-25 | Initial integration guide created | devops |
