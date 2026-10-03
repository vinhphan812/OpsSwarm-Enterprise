---
name: s7-observe-verify
description: Independently verify customer/business recovery.
---

# S7 ObserveVerify

**Contract version:** 1.0
**ADR references:** [ADR-006](../adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md) (frontmatter), [ADR-011](../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) (artifact structure)
**Skill number:** 7 of 8
**Pipeline position:** Verification / independent recovery validation

## Purpose

The S7 ObserveVerify skill is the objective, third-party validator in the OpsSwarm incident response framework. It is strictly forbidden from relying on the self-reported success of the S5 CollabExec executor. Instead, S7 independently performs read-only health checks on the affected system to confirm that the service has returned to its defined SLA/SLO baselines. This skill functions as a skeptical reviewer: it uses live monitoring data and synthetic health endpoints to determine if the customer impact has truly been mitigated, preventing the premature closure of incidents based on faulty or incomplete execution successful reports.

## Inputs

- ExecutionResult: (S5CollabExec output) indicating what action was taken and its self-reported outcome.
- RunId: Identifier for incident context.
- SystemMetrics: Live data from the observability provider (e.g., Prometheus/Datadog metrics).
- HealthEndpoints: Synthetic check results from the infrastructure layer.
- SLO_Definition: Canonical business constraints defining acceptable latency, error rates, and throughput.
  The skill uses these inputs to conduct an objective, external assessment of system health that is untainted by the executor's internal state.

## Outputs

- VerificationResult:
     - verified (boolean): True if system metrics match SLO baselines post-remediation.
     - summary (string): Explanation detailing which metrics validate or invalidate the recovery.
     - evidence (object): Raw Prometheus/health check payload data proving the verification.
     - confidence (enum: LOW, MED, HIGH): Confidence score based on data availability and freshness.
       This result is crucial for S8 OrchestrationHub to trigger final incident resolution (RESOLVED) or keep the issue open.

## Key Rules & Constraints

1. Independence: S7 MUST NEVER rely on the `ExecutionResult` outcome; it only serves to provide S7 with context on _where_ and _what_ to verify.
2. Verification via Read-Only: S7 can only use read-only observability tools. Invoking any tool with write permission is a critical policy violation.
3. SLI/SLO Adherence: Verification MUST validate against the canonical SLIs/SLOs provided by the service definition — not arbitrary heuristic checks.
4. Veto Power: If S7 determines recovery failed, it _must_ veto the closure; the incident status MUST remain OPEN regardless of what S5 reported.
5. Confidence Reporting: If data is stale or insufficient, S7 must report `confidence: LOW` and request manual inspection.
6. Evidence Requirement: Verification decisions must be fully supported by evidence payloads, which are uploaded to the audit store.

## Error Codes

| Code      | Name                            | Trigger                                           | Resolution                                                          |
| --------- | ------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------- |
| `S7-E001` | `VERIFICATION_FAILURE`          | System returns `500` on health check endpoint     | Trigger `VERIFICATION_FAILURE` state; block incident closure        |
| `S7-E002` | `INVALID_VERIFICATION_CONTRACT` | Business SLOs not defined for target service      | Flag for human intervention; do not auto-close                      |
| `S7-E003` | `MONITORING_CREDENTIAL_INVALID` | Monitoring credentials are invalid or expired     | Flag; request opsswarm admin to refresh credentials                 |
| `S7-E004` | `SYNTHETIC_CHECK_UNAVAILABLE`   | Infrastructure health endpoints are down          | Fall back to secondary observability metrics                        |
| `S7-E005` | `VERIFICATION_TIMEOUT`          | Verification request exceeds SLA without response | Flag as `VERIFICATION_TIMEOUT`; block closure                       |
| `S7-W001` | `CONFIDENCE_LOW`                | Data is stale or insufficient for verification    | Report `confidence: LOW`; request manual inspection                 |
| `S7-W002` | `MONITORING_LAG`                | Live metrics behind real-time traffic             | Request polling delay before final check to prevent false positives |

## Edge Cases

- Degraded State: If the system is partially recovered but still below SLOs, S7 reports `verified: False` with detailed findings of what is still failing.
- Monitoring Delay (Lag): If live metrics are behind real-time traffic, S7 requests a polling delay before performing the final check to prevent false positives.
- Verification Failure: If the system returns `500` on the health check endpoint, S7 immediately triggers a "VERIFICATION_FAILURE" state, blocking incident closure.
- SLO Definition Missing: If business SLOs are not defined for the target incident service, S7 flags the incident as "INVALID_VERIFICATION_CONTRACT" for human intervention.
- Synthetic Check Unavailability: If infrastructure health end-points are down, S7 automatically falls back to secondary observability metrics.

## Interactions

- Upstream: S5 CollabExec (provides execution result), S8 OrchestrationHub (provides context).
- Downstream: S8 OrchestrationHub (consumes verification results for state transitions).
- Human/External: Provides the authoritative dashboard for SLA/SLO definitions, which S7 cross-references with Prometheus endpoints.
- Security: Cross-verifies monitoring credentials to ensure it is querying the _actual_ production service metrics, not a faked test environment.

## Examples

Example Input (ExecutionResult(success=True), Service=OrderingAPI):
Output:
VerificationResult(
verified=True,
summary="OrderingAPI latency is now below 500ms (SLO: 1000ms)",
evidence={"p99_latency_ms": 450},
confidence="HIGH"
)

Reference: tests/unit/skill_s7/test_verify_recovery.py for exhaustive verification logic and SLI/SLO mapping tests.

## Best Practices

- **Independence discipline:** Never trust S5's `ExecutionResult.status` for the verification decision. Verify the actual system state independently. S5 may report success while the underlying issue persists.
- **Multi-metric validation:** Use at least 3 independent metrics to verify recovery (e.g., latency, error rate, throughput). Relying on a single metric can miss partial recoveries or correlated failures.
- **Freshness checks:** Before performing verification, confirm that metrics are fresh (within the last 5 minutes). Stale metrics can produce false positives. If metrics are stale, request a polling delay or report `CONFIDENCE_LOW`.
- **Fallback chains:** Define a fallback chain for verification methods. If the primary health endpoint fails, try the secondary; if that fails, try observability metrics. Document the fallback chain in the evidence.
- **Veto confidence:** If `verified=False`, provide a detailed explanation in `summary`. A veto without explanation prevents the human gate from understanding why verification failed and delays resolution.

## Integration Points

| Direction        | Component                 | Interface                                                                                       |
| ---------------- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| Upstream -> S7   | S5 CollabExec             | `ExecutionResult` provides context on what was attempted (not the verdict)                      |
| S7 -> Downstream | S8 OrchestrationHub       | `VerificationResult` determines if incident can transition to RESOLVED                          |
| S7 -> S8         | S8 OrchestrationHub       | If `verified=False`, triggers state transition to re-investigate                                |
| S7 <-> Human     | Dashboard/SLO definitions | Authoritative SLA/SLO definitions from the service catalog                                      |
| S7 -> Monitoring | Prometheus/Datadog        | Query live metrics via `opsswarm.observability.query_metrics()`                                 |
| S7 -> Evidence   | Evidence store            | Append `VerificationResult` to `runtime-data/evidence/{run_id}.jsonl` (EV-YYYYMMDDHHMMSSffffff) |
