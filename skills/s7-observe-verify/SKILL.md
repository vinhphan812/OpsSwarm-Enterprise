---
name: s7-observe-verify
description: Independently verify customer/business recovery.
---

# S7 ObserveVerify

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
1. Independence: S7 MUST NEVER rely on the `ExecutionResult` outcome; it only serves to provide S7 with context on *where* and *what* to verify.
2. Verification via Read-Only: S7 can only use read-only observability tools. Invoking any tool with write permission is a critical policy violation.
3. SLI/SLO Adherence: Verification MUST validate against the canonical SLIs/SLOs provided by the service definition — not arbitrary heuristic checks.
4. Veto Power: If S7 determines recovery failed, it *must* veto the closure; the incident status MUST remain OPEN regardless of what S5 reported.
5. Confidence Reporting: If data is stale or insufficient, S7 must report `confidence: LOW` and request manual inspection.
6. Evidence Requirement: Verification decisions must be fully supported by evidence payloads, which are uploaded to the audit store.

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
- Security: Cross-verifies monitoring credentials to ensure it is querying the *actual* production service metrics, not a faked test environment.

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
