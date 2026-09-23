---
name: s5-collab-exec
description: Aggregate specialist results and execute an explicitly authorized recovery.
---

# S5 CollabExec

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
6. Policy-based Authorization: Any action requires a cryptographic reference to an approval event signed by the S8 hub or the human gate.

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
