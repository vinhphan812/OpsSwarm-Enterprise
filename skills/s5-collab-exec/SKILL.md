---
name: s5-collab-exec
description: Aggregate specialist results and execute an explicitly authorized recovery.
---

# S5 CollabExec

**Contract version:** 1.0
**ADR references:** [ADR-006](../adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md) (frontmatter), [ADR-011](../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) (artifact structure)
**Skill number:** 5 of 8
**Pipeline position:** Execution / authorized recovery action

## Purpose

The S5 CollabExec skill functions as the operational executor within the OpsSwarm framework. Its fundamental role is to bridge the gap between planning and action. After specialists (via S4 RoleDispatch) investigate different facets of an incident and S3 HorizonPlan generates recovery options, S5 CollabExec aggregates these outputs. It does not decide what to do based on speculation; it executes only the specific recovery action that has been formally selected and authorized. By performing this aggregation and execution with strict authorization checks, S5 acts as the central point for controlled incident resolution and results reporting.

## Inputs

This skill consumes the prioritized diagnostic data and the approved remediation action plan.

- TaskResults[]: A list of findings, logs, and evidence sets from the agents dispatched by S4.
- SelectedOptionId: The unique identifier of the remediation option selected by the orchestrator.
- run_id: The current incident execution identifier.
- AuthorizationManifest: A signed token confirming the specific action has been authorized (either automatically by policy or manually by a human).
  These inputs flow through the S8 OrchestrationHub, ensuring that this execution skill is never operating without verifiable context or formal authority.

## Outputs

S5 CollabExec returns the formal record of the executed recovery.

- ExecutionResult:
     - status (enum: success, failure, partial_success): The outcome of the action.
     - summary (string): A concise, human-readable account of action steps taken.
     - evidence (object): Raw output from the command execution (e.g., CLI exit codes, log excerpts, diffs).
     - ambiguity_flag (boolean): Flag indicating if unexpected behavior occurred during execution that requires human review.
       This result is then passed back to S8 OrchestrationHub to trigger either verification (S7) or incident closure.

## Key Rules & Constraints

1. Authorization Enforcement: Execution MUST strictly enforce authorization policies — AUTO for safe-write, APPROVAL for risky-write/destructive.
2. Explicit Action: The skill MUST ONLY execute the SelectedOptionId. It cannot perform any side-effect-generating action that is not strictly contained within the option definition.
3. No Inference: It must not infer how to perform the remedial action; it follows an explicit instruction set provided with the action ID.
4. Atomicity: Actions must be designed to be atomic; if execution fails partially, it must be capable of reporting the failed state accurately without causing further system drift.
5. Recordkeeping: Every action side effect (any file change, service call, or API request made) must be logged in the ExecutionResult.evidence.
6. Policy-based Authorization: Any destructive action requires a cryptographic reference to an approval event signed by the S8 hub or the human gate.

## Error Codes

| Code      | Name                     | Trigger                                                   | Resolution                                                         |
| --------- | ------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------ |
| `S5-E001` | `EXECUTION_TIMEOUT`      | Remediation action hangs beyond hard-coded limit          | Kill process; flag failure; pass to S6 ResilienceGuard             |
| `S5-E002` | `PERMISSION_DENIED`      | Agent profile lacks rights to execute command             | Return `ExecutionResult(failure, "Permission Denied")` immediately |
| `S5-E003` | `UNEXPECTED_STATE_DRIFT` | Environment state differs from plan expectations          | Pause; set `ambiguity_flag=True`; await human inspection           |
| `S5-E004` | `COMMAND_FAILURE`        | Command returns non-zero exit code                        | Capture stderr in evidence; flag failure                           |
| `S5-E005` | `NETWORK_PARTITION`      | Execution agent loses connectivity mid-action             | Report failure with `summary="Connectivity loss during execution"` |
| `S5-E006` | `UNAUTHORIZED_ACTION`    | Execution attempted without valid `AuthorizationManifest` | Halt; reject execution; notify S8 OrchestrationHub                 |
| `S5-W001` | `PARTIAL_SUCCESS`        | Action partially succeeded before failing                 | Report `partial_success`; include partial evidence                 |

## Edge Cases

- Execution Timeout: If the remediation action hangs, the skill kills the process after a hard-coded limit and flags a failure in the result object for S6.
- Permission Denial: If the underlying agent profile lacks the rights to execute a command, it returns ExecutionResult(failure, "Permission Denied") immediately.
- Unexpected System Drift: If the environment state is not what was expected by the plan, the skill automatically pauses and sets ambiguity_flag=True for human inspection.
- Command Failure: If a command returns a non-zero exit code, the skill captures stderr in evidence and flags failure.
- Network Partitioning: If the execution agent loses connectivity during action, it reports failure with summary="Connectivity loss during execution".

## Interactions

- Upstream: S3 HorizonPlan (provides options), S4 RoleDispatch (provides agents for execution).
- Downstream: S7 ObserveVerify (consumes the result for health verification), S6 ResilienceGuard (handles failures).
- S8 OrchestrationHub: Provides the authorization manifest and holds the run state machine.
- Human/External: Human approval of destructive actions is communicated through GitHub comments, which the S8 hub propagates as authorization to this skill.

## Examples

Example Input (SelectedOptionId="revert-db-cache", AuthorizationManifest={"id": "auth-123"}):
Output:
ExecutionResult(
status="success",
summary="Cache cleared on 3/3 OrderingAPI nodes",
evidence={"stdout": "success", "stderr": ""},
ambiguity_flag=False
)

Reference: tests/unit/skill_s5/test_execute_recovery.py contains the tests for execution authorization enforcement and action mapping.

## Best Practices

- **Explicit action mapping:** Only execute the `SelectedOptionId` provided in the input. Do not infer alternative actions, even if they seem obvious. If the action is wrong, the issue must go back to S3 for re-planning.
- **Atomic design:** Design recovery actions to be as atomic as possible. If a multi-step action fails partway through, the evidence must clearly show what succeeded and what failed so S6 can determine the next step.
- **Evidence capture:** Log every command executed, its stdout/stderr, and the system state before and after. This evidence is critical for post-incident review and for S7 verification to correlate.
- **Ambiguity handling:** Set `ambiguity_flag=True` if ANY system state deviation is detected during execution — even if the command technically succeeded. Better to pause for human review than to proceed on incorrect assumptions.
- **Authorization pre-check:** Verify the `AuthorizationManifest` before executing ANY action. A missing or invalid manifest must halt execution immediately with `S5-E006`.

## Integration Points

| Direction        | Component             | Interface                                                                                    |
| ---------------- | --------------------- | -------------------------------------------------------------------------------------------- |
| Upstream -> S5   | S3 HorizonPlan        | `RecoveryPlan` with `RemediationOption[]` consumed for execution                             |
| Upstream -> S5   | S4 RoleDispatch       | Agent workspaces and task envelopes passed to execution                                      |
| S5 -> Downstream | S7 ObserveVerify      | `ExecutionResult` passed for independent verification                                        |
| S5 -> S6         | S6 ResilienceGuard    | Failure events trigger retry or escalation logic                                             |
| S5 -> S8         | S8 OrchestrationHub   | Authorization manifest validated; state transitions triggered                                |
| S5 <-> Human     | GitHub Issue comments | Approval communicated through `/opsswarm approve` commands                                   |
| S5 -> Evidence   | Evidence store        | Append `ExecutionResult` to `runtime-data/evidence/{run_id}.jsonl` (EV-YYYYMMDDHHMMSSffffff) |
