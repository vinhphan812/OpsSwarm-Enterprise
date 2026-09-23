---
name: s8-orchestration-hub
description: Own the incident lifecycle and checkpoints.
---

# S8 OrchestrationHub

## Purpose
The S8 OrchestrationHub is the authoritative brain of the entire OpsSwarm automated incident response system. Its role is to own the definitive state machine of the incident lifecycle, ensuring that the system transitions through well-defined stages (PENDING → INVESTIGATING → WAITING_APPROVAL → RESOLVED) only when appropriate conditions are met. It centralizes all communication with human operators via GitHub issues, acting as the sole command interpreter for directives like `/opsswarm approve`. By controlling the state transitions and enforcing checkpoints, S8 ensures that the system is fully auditable, deterministic, and safe, never taking an unverified step forward in the remediation path.

## Inputs
- GitHub Issue Events: Triggered by user interaction, labeling, or commenting.
- System Commands: Specifically the `/opsswarm approve` or `/opsswarm resolution` directives posted in GitHub issues.
- VerificationResult: The final feedback from the S7 ObserveVerify skill.
- IncidentContext: Current state data and run history forwarded by upstream skills.
These inputs provide the OrchestrationHub with the necessary observability to make high-level decisions regarding incident flow and state progression.

## Outputs
- RunState transitions: Formal updates to the incident state machine (`PENDING` → `INVESTIGATING` → `WAITING_APPROVAL` → `RESOLVED`).
- AuthorizationManifests: Cryptographic delegation of permission (e.g., authorization for S5 to perform a destructive recovery action).
- Human Notifications: Structured status updates posted back to the GitHub issue.
- IncidentClosureReport: A comprehensive post-incident summation of all findings, actions, and verification results.

## Key Rules & Constraints
1. Authority Enforcement: Any operation requiring human authority MUST exclusively use the `/opsswarm approve` command. Free-text comments in GitHub cannot authorize any structural change or remediation action.
2. State Determinism: The state machine MUST be deterministic; it is impossible for the incident to be in two states simultaneously. Transitions occur only if the preconditions are verified by the required downstream skills.
3. Sole Control Surface: GitHub is the *exclusive* human-machine control interface. No secondary UI or command channel exists for triggering incident resolution steps.
4. Checkpoint Enforcement: The orchestrator requires a signed VerificationResult before moving to a RESOLVED state.
5. Auditable Transitions: Every state transition and authorization decision is logged in an immutable event store for post-incident audit.
6. Safety Stop: If an incident remains stuck in an unverified state for longer than the defined SLA, S8 escalates the incident state to `STALE` and flags it for human investigation.

## Edge Cases
- Desync Loop: If the OrchestrationHub loses track of the incident pipeline status, it suspends itself into `EMERGENCY_HALT` and alerts human admins.
- Conflicting Commands: If multiple conflicting commands are issued concurrently, the S8 Hub processes them in order and rejects obsolete commands.
- Authorization Missing: If S7 verification fails, the orchestrator refuses to move to the RESOLVED state even if all other preconditions (like diagnostic completion) are met.
- Unexpected Lifecycle Exit: If an incident is closed manually in GitHub (e.g., resolved by human), the OrchestrationHub detects it and force-transitions the state to `RESOLVED` with a "manual_closure" audit flag.
- Verification Veto: If verification (S7) vetoes the closure, S8 must revert the incident to the `INVESTIGATING` phase, forcing a re-plan.

## Interactions
- Upstream: Incident reporter (via GitHub issues).
- Downstream: All other skills (S1-S7) are triggered, orchestrated, and aggregated by S8.
- Human/External: GitHub issue comments are the only channel for user input (commands, clarification requests).
- Security: S8 is the only component that can issue `AuthorizationManifests`, acting as the security gate for all downstream actions taken by S5.

## Examples
Example Input (Command="/opsswarm approve", VerificationResult(verified=True)):
Output:
RunState transition: WAITING_APPROVAL → RESOLVED

Reference: tests/unit/skill_s8/test_orchestrator_hub.py for all state machine transition and command interpreter tests.
