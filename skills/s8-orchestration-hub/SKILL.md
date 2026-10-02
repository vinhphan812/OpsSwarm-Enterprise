---
name: s8-orchestration-hub
description: Own the incident lifecycle and checkpoints.
---

# S8 OrchestrationHub

**Contract version:** 1.0
**ADR references:** [ADR-006](../adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md) (frontmatter), [ADR-011](../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) (artifact structure)
**Skill number:** 8 of 8
**Pipeline position:** Control plane / lifecycle orchestration

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
3. Sole Control Surface: GitHub is the _exclusive_ human-machine control interface. No secondary UI or command channel exists for triggering incident resolution steps.
4. Checkpoint Enforcement: The orchestrator requires a signed VerificationResult before moving to a RESOLVED state.
5. Auditable Transitions: Every state transition and authorization decision is logged in an immutable event store for post-incident audit.
6. Safety Stop: If an incident remains stuck in an unverified state for longer than the defined SLA, S8 escalates the incident state to `STALE` and flags it for human investigation.

## Error Codes

| Code      | Name                    | Trigger                                                     | Resolution                                                      |
| --------- | ----------------------- | ----------------------------------------------------------- | --------------------------------------------------------------- |
| `S8-E001` | `EMERGENCY_HALT`        | OrchestrationHub loses track of pipeline status             | Suspend to `EMERGENCY_HALT`; alert human admins                 |
| `S8-E002` | `VERIFICATION_VETO`     | S7 verification failed; closure blocked                     | Refuse `RESOLVED` state; revert incident to `INVESTIGATING`     |
| `S8-E003` | `AUTHORIZATION_MISSING` | `AuthorizationManifest` absent for risky/destructive action | Reject execution request; require human approval                |
| `S8-E004` | `STATE_DESYNC`          | Incident closed manually in GitHub while hub still tracking | Force-transition to `RESOLVED` with `manual_closure` audit flag |
| `S8-E005` | `STALE_INCIDENT`        | Incident stuck in unverified state beyond SLA               | Escalate to `STALE`; flag for human investigation               |
| `S8-E006` | `COMMAND_CONFLICT`      | Multiple conflicting commands issued concurrently           | Process in order; reject obsolete commands                      |
| `S8-W001` | `REVIEW_REQUIRED`       | Non-risky action detected with unusual pattern              | Flag for human review before proceeding                         |

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

## Best Practices

- **State machine integrity:** The state must be single-valued and deterministic. Before any transition, validate that the current state permits the requested transition. A request to transition from PENDING directly to RESOLVED must be rejected.
- **Authorization guard:** Reject any command that lacks a valid cryptographic signature, even if the user is authorized. The signature proves intent, not just identity.
- **Event immutability:** Append-only logging for all state transitions. Never overwrite or delete log entries. The audit trail must be reconstructable even if the database is corrupted.
- **Graceful degradation:** If the state machine loses track of the incident (e.g., database unavailable), transition to `EMERGENCY_HALT` and alert humans. Do not attempt to recover state automatically — that risks data corruption.
- **Checkpoint enforcement:** Never allow RESOLVED without a verified `VerificationResult` from S7. The S7 veto is absolute and cannot be overridden by S8 or by human command.

## Integration Points

| Direction           | Component                | Interface                                                                                                                |
| ------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Upstream -> S8      | All skills (S1-S7)       | Central hub receives events from all pipeline skills                                                                     |
| S8 -> Downstream    | All skills (S1-S7)       | Triggers skill execution based on state machine logic                                                                    |
| S8 <-> Human        | GitHub Issue comments    | `/opsswarm approve`, `/opsswarm resolution` commands interpreted                                                         |
| S8 -> Human         | GitHub Issue comments    | Status updates and escalation notifications                                                                              |
| S8 -> Authorization | AuthorizationManifest    | Issues cryptographic delegations for S5 execution                                                                        |
| S8 -> Evidence      | Evidence store           | Append state transitions and authorization decisions to `runtime-data/evidence/{run_id}.jsonl` (EV-YYYYMMDDHHMMSSffffff) |
| S8 -> Policy        | IncidentResolutionPolicy | SLA timeouts and escalation thresholds from config                                                                       |
