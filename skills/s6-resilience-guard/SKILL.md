---
name: s6-resilience-guard
description: Handle failures, ambiguity and human gates.
---

# S6 ResilienceGuard

**Contract version:** 1.0
**ADR references:** [ADR-006](../adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md) (frontmatter), [ADR-011](../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) (artifact structure)
**Skill number:** 6 of 8
**Pipeline position:** Safety / failure handling and escalation

## Purpose

The S6 ResilienceGuard skill serves as the safety supervisor and decision-making fallback for the entire OpsSwarm pipeline. Its critical function is to interpret the outcomes of execution tasks, especially when those outcomes are ambiguous, failed, or represent a deviation from the expected system state. Rather than adopting a "fail-fast" or "blind-retry" approach, ResilienceGuard enforces robust resilience policies. It is designed to interrupt failures by routing unexpected or high-risk states to human actors for definitive resolution, thereby ensuring that automated systems never perform non-deterministic operations in an unstable environment.

## Inputs

- ExecutionResult: (status, summary, evidence, ambiguity_flag) from the S5 CollabExec execution.
- AmbiguityFlag: A boolean explicitly set by S5 when it detects unanticipated environment changes.
- IncidentResolutionPolicy: The policy database defining retry thresholds and human gate trigger conditions.
  This information allows ResilienceGuard to gauge the confidence of the automatic decision-making path and determine whether human intervention is necessitated by the current system state.

## Outputs

- Decision: (enum: AUTO_RETRY, APPROVAL_REQUEST, MANUAL_DECISION, HALT_DENY).
     - AUTO_RETRY: Safe for automated re-execution based on policy.
     - APPROVAL_REQUEST: Escalation to human gate via GitHub.
     - MANUAL_DECISION: Urgent halt until a human provides a directive.
     - HALT_DENY: Irrecoverable failure; shutdown of the pipeline pending manual review.
       This Decision is passed back to S8 OrchestrationHub, which manages the state transition accordingly.

## Key Rules & Constraints

1. No Blind Retries: ResilienceGuard MUST NEVER trigger an automatic retry for `risky_write` or `destructive` operations if the `ambiguity_flag` is True.
2. Routing Ambiguity: Any situation where the system state is ambiguous must be routed immediately to the GitHub issue comment system for human review.
3. Authorization Restriction: Free-text comments from users cannot authorize any automated side effects; all authorizing must go through explicitly structured approval commands (`/opsswarm approve`).
4. Fail-Safe: In case of contradictory inputs or unexpected internal error, the skill must default to HALT_DENY.
5. Policy Logic: Retry thresholds (e.g., maximum of 3 retries) are strictly enforced and cannot be overridden by agent logic.
6. Evidence Preservation: All failure reports and ambiguity logs must be preserved in the final incident report.

## Error Codes

| Code      | Name                      | Trigger                                                       | Resolution                                                  |
| --------- | ------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------- |
| `S6-E001` | `RETRY_LOOP_BREAK`        | Repeated retries continue to fail                             | Break loop; escalate to `APPROVAL_REQUEST` for human review |
| `S6-E002` | `HUMAN_GATE_TIMEOUT`      | Human gate SLA exceeded without response                      | Signal `HALT_DENY`; create high-priority GitHub issue alert |
| `S6-E003` | `POLICY_CORRUPTION`       | Policy database is corrupted or unreadable                    | Halt all operations; alert opsswarm admin                   |
| `S6-E004` | `STATE_DESYNC`            | Observed system state conflicts with `ExecutionResult.status` | Flag `StateDesync`; require immediate manual investigation  |
| `S6-E005` | `CASCADING_FAILURE`       | Multiple specialist tasks fail simultaneously                 | Halt all dependent DAG tasks; prevent further system stress |
| `S6-E006` | `INTERNAL_ERROR`          | Contradictory inputs or unexpected internal error             | Default to `HALT_DENY`; preserve all logs                   |
| `S6-W001` | `AMBER_RETRY_RECOMMENDED` | `ambiguity_flag=False` and action is `safe_write`             | Recommend `AUTO_RETRY`; log for S8 review                   |

## Edge Cases

- Retry Loop: If repeated retries continue to fail, the skill breaks the loop and escalates to `APPROVAL_REQUEST` for a human to review why the retry is failing.
- Human Gate Timeout: If the human gate does not respond within the SLA, the skill signals `HALT_DENY` and creates a high-priority GitHub issue alert.
- Policy Inconsistency: If the policy database is corrupted, the skill halts all operations.
- State Desynchronization: If the observed system state clearly conflicts with the reported `ExecutionResult.status`, the skill flags a `StateDesync` incident which necessitates an immediate manual investigation.
- Cascading Failures: If multiple specialist tasks fail simultaneously, the ResilienceGuard halts all dependent DAG tasks to prevent further system stress.

## Interactions

- Upstream: S5 CollabExec (provides execution results).
- Downstream: S8 OrchestrationHub (consumes the decision for state transitions).
- Human/External: GitHub comments are the primary medium for escalating ambiguity and risky states to human review.
- Security: ResilienceGuard audits that any decision path involving `AUTO_RETRY` remains compliant with the `ADR-010` security policy regarding retry-rate-limiting.

## Examples

Example Input (ExecutionResult(status="failure", ambiguity_flag=True), Policy=RetryDisabledForRisky):
Output:
Decision: APPROVAL_REQUEST

Reference: tests/unit/skill_s6/test_policy_gates.py for all policy logic and gate enforcement tests.

## Best Practices

- **Fail-safe defaults:** In any ambiguous situation — conflicting inputs, policy database errors, or unexpected internal state — default to `HALT_DENY`. It is safer to pause automation and alert a human than to guess and potentially worsen the incident.
- **Retry discipline:** Enforce hard retry limits (e.g., max 3 retries) strictly. Do not let agents override these limits even if they claim confidence. Limits exist to prevent retry storms during outages.
- **Evidence preservation before halt:** When transitioning to `HALT_DENY`, ensure all current evidence (execution logs, task results, state snapshots) is preserved to disk before signaling S8. This enables post-mortem analysis.
- **Ambiguity routing:** Never attempt to resolve ambiguity automatically. Any situation where `ambiguity_flag=True` must route to a human gate. The routing comment should explicitly state what is ambiguous and what information would resolve it.
- **Cascading failure detection:** Monitor the entire DAG for cascading failures. If >50% of tasks in a single execution wave fail, halt proactively rather than waiting for the full DAG to exhaust.

## Integration Points

| Direction        | Component                | Interface                                                                                         |
| ---------------- | ------------------------ | ------------------------------------------------------------------------------------------------- |
| Upstream -> S6   | S5 CollabExec            | `ExecutionResult` (status, summary, evidence, ambiguity_flag) consumed                            |
| S6 -> Downstream | S8 OrchestrationHub      | Decision (AUTO_RETRY/APPROVAL_REQUEST/MANUAL_DECISION/HALT_DENY) drives state machine             |
| S6 -> S5         | S5 CollabExec            | Retry signals trigger re-execution of the same action                                             |
| S6 <-> Human     | GitHub Issue comments    | Escalation requests and approval prompts via `/opsswarm approve`                                  |
| S6 -> Policy     | IncidentResolutionPolicy | Retry thresholds and gate conditions from `config/incident-policy.yml`                            |
| S6 -> Evidence   | Evidence store           | Append decision and reasoning to `runtime-data/evidence/{run_id}.jsonl` (EV-YYYYMMDDHHMMSSffffff) |
