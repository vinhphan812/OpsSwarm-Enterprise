---
name: s4-role-dispatch
description: Dispatch bounded tasks to canonical OpenClaw specialist profiles.
---

# S4 RoleDispatch

## Purpose
The S4 RoleDispatch skill acts as the automated talent management and delegation layer within the OpsSwarm framework. Once S2 TaskGraph defines *what* needs to be done, S4 RoleDispatch determines *who* best performs each task. It maintains a canonical map of OpenClaw specialist profiles, each with defined competencies, and maps tasks from the DAG to an appropriately skilled agent. This ensures that expert investigative tasks (e.g., database performance fine-tuning) are delegated to the specialist profile (e.g., `database-investigator`) that possesses the necessary tools and environment access to execute them efficiently, thereby maximizing the success rate of each sub-investigation.

## Inputs
This skill consumes the prioritized and structured Task DAG.
- `Task[]`: A list of validated Task objects from S2 TaskGraph containing `task_type` and `assignee_profile`.
- `run_id`: The incident identifier.
- `AvailableAgentProfiles`: A real-time registry of currently authenticated agent profiles in the `OpsSwarm-Enterprise` tenant.
- `CapabilityCatalog`: A mapping of profile to authorized capabilities in the environment.
These inputs guarantee that dispatch decisions are made based on the current availability and authority level of the agents within the tenant.

## Outputs
The outputs are "Task Envelopes" ready for dispatch to specific agent process environments.
- `TaskEnvelope[]`: A list of fully realized tasks containing:
  - `assigned_profile`: The canonical specialist name.
  - `task_payload`: The full diagnostic instructions, scoping context, and expected output format.
  - `agent_workspace_path`: The dedicated sandbox on the worker machine.
  - `capability_limitations`: The security context, constraining what tools the worker can invoke.
These envelopes are directly passed to the S5 CollabExec skill for execution orchestration.

## Key Rules & Constraints
1. Canonical Profile Compliance: Dispatch is strictly limited to: `observability-investigator`, `application-investigator`, `infrastructure-investigator`, `database-investigator`, `recovery-responder`, or `communications-postmortem`.
2. Encapsulation: The task envelope MUST be complete. It must include all IncidentContext needed to understand the scope; agents are forbidden from querying the central hub for missing context during task execution.
3. Scope Enforcement: The task payload MUST limit the agent's operations to the service identified in the task, using the security credentials mapped to the `assigned_profile`.
4. Authentication: All dispatched envelopes must be signed by S4 to prevent unauthorized agent process injection.
5. Determinism: A task requiring an `application-investigator` MUST ALWAYS be sent to the same profile for the same incident run, maintaining consistent access patterns.
6. Capability Matching: The task *type* (e.g., DIAGNOSE) must have a corresponding permission set in the `CapabilityCatalog` matched with the `assigned_profile`.

## Edge Cases
- Profile Unavailable: If the required specialist profile is not in the registry, S4 raises a `DISPATCH_SECURITY_CRITICAL_ERROR` and halts, notifying S8 OrchestrationHub to request a manual assignment.
- Incorrect Mapping: If an `OBSERVE` task accidentally lands on a `recovery-responder` (which lacks observability tools), S4 detects the capability mismatch and pauses to prevent an execution failure.
- Malformed Payload: If a TaskEnvelope is too large, exceeding the transport limit for the messaging system, it is split or rejected with an error for the S2 builder to re-optimize.
- Agent Crash/Non-responsive: Upon failure to acknowledge dispatch, S4 generates a "DISPATCH_FAILED" notice, triggering the S6 ResilienceGuard for re-dispatch logic.
- Policy Denial: If an agent tries to modify a service not in its scope (detected via runtime audit), the entire TaskEnvelope is immediately revoked.

## Interactions
- Upstream: S2 TaskGraph (provides the tasks).
- Downstream: S5 CollabExec (executes the dispatched task).
- S8 OrchestrationHub: Governs the overall status of dispatched tasks and monitors for dispatch failure alerts.
- Human/External: Provides the authoritative registry of specialist agents and their capabilities through the `config/skill-gates.yml` file.
- Security: Forces a re-check of the agent's identity and capabilities in the repo’s `AGENTS.md` before dispatching any sensitive diagnostic tasks.

## Examples
Example Input (Task(task_id="t5", assignee="database-investigator")):
Output:
TaskEnvelope(
  profile="database-investigator",
  payload={"task_id": "t5", "instructions": "Analyze Query Latency", "scope": "OrderingDB"},
  workspace="/d/workspaces/db-investigator-01",
  auth_token="...",
  capabilities=["SQL_READ_ONLY"]
)

Reference: `tests/unit/skill_s4/test_execute_task.py` and `tests/unit/skill_s4/test_profile_selection.py` for comprehensive dispatch logic and permission-based routing tests.
