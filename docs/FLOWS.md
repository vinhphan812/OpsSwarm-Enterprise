# OpsSwarm Enterprise Runtime Flows

This document describes the **implemented v2.1 runtime flow** used as the baseline for v2.2 quality hardening. It complements [ARCHITECTURE.md](./ARCHITECTURE.md) by showing event ordering, state transitions, human gates, evidence production, and failure branches.

A core rule for this document is: **the diagrams follow production code, not an aspirational design**. Runtime state names therefore match `RunState` in `opsswarm/models.py` exactly.

## 1. Canonical flow at a glance

```text
Monitoring/User
    -> GitHub Issue
    -> OpsSwarm webhook / monitoring ingress
    -> S8 lifecycle control
    -> S1 incident normalization
    -> S2 read-only investigation DAG
    -> S4 specialist OpenClaw dispatch
    -> structured findings + evidence
    -> root-cause synthesis
    -> S3 recovery planning
    -> policy
       -> AUTO, or
       -> WAITING_APPROVAL, or
       -> WAITING_DECISION, or
       -> WAITING_INPUT, or
       -> FAILED
    -> S5 authorized recovery execution
    -> S6 ambiguity / resilience control when required
    -> S7 independent verification
    -> RESOLVED + final comments + issue close
       OR
       FAILED / ABORTED with issue left open
```

The Skill labels above are architectural capabilities. The current implementation concentrates orchestration in `opsswarm/orchestrator.py` and delegates structured OpenClaw calls through `opsswarm/skill_logic.py`.

## 2. Canonical end-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    participant SRC as Monitoring / User
    participant GH as GitHub Issue
    participant API as OpsSwarm API
    participant S8 as S8 OrchestrationHub
    participant S1 as S1 IntentGuard
    participant S2 as S2 TaskGraph
    participant S4 as S4 RoleDispatch
    participant OC as OpenClaw Agents
    participant S3 as S3 HorizonPlan
    participant P as Policy Engine
    participant H as Human Operator
    participant S5 as S5 CollabExec
    participant S6 as S6 ResilienceGuard
    participant S7 as S7 ObserveVerify

    SRC->>GH: Open incident or monitoring ingress creates Issue
    GH->>API: issues.opened webhook
    API->>S8: start_issue(issue_number)
    S8->>S1: Parse bounded incident context
    S1-->>S8: IncidentContext
    S8->>S2: Build read-only investigation DAG
    S2->>OC: Incident-manager planning session
    OC-->>S2: OBSERVE / INVESTIGATE / DIAGNOSE tasks
    S8->>S4: Dispatch dependency-ready tasks by profile
    S4->>OC: Bounded read-only specialist tasks
    OC-->>S4: Findings + concrete evidence refs
    S4-->>S8: Structured findings
    S8->>OC: Root-cause synthesis
    OC-->>S8: RootCauseArtifact

    alt root cause uncertain or below threshold
        S8->>GH: WAITING_INPUT + question
        H->>GH: /opsswarm provide ... or /opsswarm investigate ...
        GH->>API: issue_comment webhook
        API->>S8: Resume investigation path
    else diagnosis sufficiently certain
        S8->>S3: Build recovery plan
        S3->>OC: Planning session
        OC-->>S3: RecoveryPlan + risk per option
        S3->>P: classify_plan()

        alt AUTO
            P-->>S8: AUTO
        else risky write
            P-->>S8: APPROVAL
            S8->>GH: WAITING_APPROVAL
            H->>GH: /opsswarm approve option-id
            GH->>API: issue_comment webhook
            API->>S8: Authorized approval
        else multiple options
            P-->>S8: DECISION
            S8->>GH: WAITING_DECISION
            H->>GH: Explicit /opsswarm command
            GH->>API: issue_comment webhook
            API->>S8: Decision / investigation request
        else missing business context
            P-->>S8: INPUT
            S8->>GH: WAITING_INPUT
            H->>GH: /opsswarm provide ...
            GH->>API: issue_comment webhook
            API->>S8: Provided input
        else denied
            P-->>S8: DENY
            S8->>GH: FAILED, issue remains open
        end

        S8->>S5: Execute selected authorized option
        S5->>OC: Recovery responder session
        OC-->>S5: ExecutionResult + evidence

        alt ambiguous write outcome
            S5->>S6: Ambiguity control
            S6->>GH: WAITING_DECISION, blind retry prohibited
        else definite execution failure
            S5->>GH: FAILED, issue remains open
        else successful execution result
            S5->>S7: Request independent verification
            S7->>OC: Read-only verification session
            OC-->>S7: VerificationResult + evidence
            alt verified above confidence threshold
                S7-->>S8: verified=true
                S8->>GH: RESOLVED + summary + postmortem + close
            else not verified / below threshold
                S7-->>S8: verification failure
                S8->>GH: FAILED, issue remains open
            end
        end
    end
```

### Important implementation note

S6 is currently an **architectural resilience capability**, not a standalone runtime object/state. Its behavior is implemented by policy/orchestrator branches such as ambiguous-write handling, fail-closed decisions, human gates, and safe continuation. There is no `RECOVERING` member in `RunState` today.

## 3. Human-created incident flow

Trigger: GitHub `issues.opened` webhook.

```mermaid
flowchart TD
    U[Human creates Issue from incident template] --> GH[GitHub emits issues.opened]
    GH --> SIG{Webhook signature valid?}
    SIG -->|No| REJECT[HTTP 401]
    SIG -->|Yes| START[Schedule start_issue]
    START --> LABEL{Required opsswarm label present?}
    LABEL -->|No| ERR[Reject start]
    LABEL -->|Yes| RUN[Create / reuse one active run]
    RUN --> TRIAGE[TRIAGE]
    TRIAGE --> INVEST[INVESTIGATING]
```

### Inputs

- Issue number/title/body
- labels, including the required OpsSwarm label
- Issue author
- structured incident-template fields such as service, symptoms, customer impact, and environment

### Evidence

S1 persists `S1.incident`. The Issue remains the human-visible system of record.

### Duplicate start behavior

Within one process, `start_issue()` uses a per-Issue asyncio lock and reuses an existing non-failed/non-aborted run. Persisted runs are loaded at startup. Stronger GitHub delivery-ID deduplication and cross-process idempotency are **not claimed here** and are tracked by reliability hardening work.

## 4. Machine-created monitoring incident flow

Trigger: `POST /hooks/monitoring`.

```mermaid
sequenceDiagram
    participant MON as Monitoring System
    participant API as /hooks/monitoring
    participant GH as GitHub
    participant S8 as Orchestrator

    MON->>API: Normalized monitoring event
    API->>GH: Create Issue with base + severity labels
    GH-->>API: Issue number
    API->>S8: schedule start_issue(issue_number)
    Note over GH,S8: GitHub may also emit issues.opened for the created Issue
    S8->>S8: Per-Issue in-process lock / existing-run reuse
```

The machine-created path intentionally converges on the same GitHub Issue and the same `start_issue()` workflow as human-created incidents.

## 5. Investigation and evidence-gathering flow

S2 creates only read-only work before remediation. The allowed task types are `OBSERVE`, `INVESTIGATE`, and `DIAGNOSE`.

```mermaid
flowchart TD
    CTX[IncidentContext] --> S2[S2 build investigation DAG]
    S2 --> VALID{Tasks returned?}
    VALID -->|No| FAIL[Runtime error / no investigation]
    VALID -->|Yes| READY[Find dependency-ready tasks]
    READY --> CYCLE{Any ready tasks?}
    CYCLE -->|No while pending exists| BAD[Unsatisfied / cyclic graph error]
    CYCLE -->|Yes| S4[S4 dispatch by specialist profile]
    S4 --> OC[OpenClaw read-only specialist]
    OC --> FIND[Finding + evidence refs]
    FIND --> SAVE[Persist S4.finding]
    SAVE --> MORE{Pending tasks?}
    MORE -->|Yes| READY
    MORE -->|No| RCA[Root-cause synthesis]
```

### Parallelism

Dependency-ready tasks are executed in waves with `asyncio.gather`. A task enters `RUNNING`, then `DONE` on success or `FAILED` on exception.

### Root-cause gate

After all investigation tasks finish, the incident-manager profile synthesizes a `RootCauseArtifact`.

- if `status=uncertain`, or confidence is below `root_cause_confidence_threshold`, the run moves to `WAITING_INPUT`;
- otherwise it moves through `DIAGNOSED` to planning.

## 6. Recovery planning and policy flow

```mermaid
flowchart TD
    RCA[DIAGNOSED root cause] --> PLAN[PLANNING: S3 recovery plan]
    PLAN --> POLICY{PolicyEngine.classify_plan}
    POLICY -->|AUTO| EXEC[EXECUTING]
    POLICY -->|APPROVAL| WA[WAITING_APPROVAL]
    POLICY -->|DECISION| WD[WAITING_DECISION]
    POLICY -->|INPUT| WI[WAITING_INPUT]
    POLICY -->|DENY / other failure| FAILED[FAILED]

    WA --> APPROVE[/opsswarm approve option-id/]
    APPROVE --> PERM{Permission sufficient and option not DENY?}
    PERM -->|Yes| EXEC
    PERM -->|No| REJECT[Reject command]

    WD --> INV[/opsswarm investigate request/]
    INV --> INVEST[INVESTIGATING]
    WI --> PROVIDE[/opsswarm provide information/]
    PROVIDE --> INVEST
```

### Safe automatic path

If policy returns `AUTO`, the current implementation selects the first recovery option and calls the recovery executor without a human approval step.

### Risky-write approval path

For `APPROVAL`, the run transitions to `WAITING_APPROVAL`. Only an explicit `/opsswarm approve <option-id>` from a user at or above the configured minimum permission can continue to execution.

### Decision path

For multiple materially different options or ambiguity, the run is placed in `WAITING_DECISION`. Human operators can request additional read-only investigation or provide explicit information/commands.

### Missing-input path

`WAITING_INPUT` is used when diagnosis/planning lacks business or operational context. `/opsswarm provide ...` stores the supplied information and re-enters investigation/root-cause synthesis.

## 7. Human command authority flow

```mermaid
flowchart TD
    C[GitHub Issue Comment] --> PARSE{Recognized /opsswarm command?}
    PARSE -->|No| FREE[Store as human.free_text]
    FREE --> INFO[authority = information-only]
    INFO --> NOAUTH[No side-effect authority]

    PARSE -->|Yes| PERM{GitHub permission sufficient?}
    PERM -->|No| DENIED[Command rejected]
    PERM -->|Yes| CMD{Command}

    CMD -->|provide| INPUT[Store provided input and reinvestigate]
    CMD -->|investigate| EXTRA[Create one extra read-only task]
    CMD -->|approve| OPT{Option exists and policy not DENY?}
    OPT -->|Yes| EXEC[Execute option]
    OPT -->|No| REJ[Reject]
    CMD -->|reject| WAIT[WAITING_DECISION]
    CMD -->|abort| ABORT[ABORTED]
    CMD -->|resume| SAFE{FAILED + successful execution checkpoint?}
    SAFE -->|Yes| VERIFY[VERIFYING]
    SAFE -->|No| MSG[Comment that resume is not accepted]
```

### Current state-guard nuance

The current handler strongly enforces **permissions and policy**, but not every command has an explicit state whitelist before it is processed. The diagrams show the intended operational use of commands from the relevant waiting states while documenting the current implementation truth. Tightening command/state guards belongs to v2.2 reliability hardening rather than being silently claimed as already implemented.

## 8. Side-effect execution and ambiguous-write flow

```mermaid
flowchart TD
    EXEC[S5 invokes authorized recovery through OpenClaw] --> RESULT{ExecutionResult}
    RESULT -->|success=true and ambiguous=false| VERIFY[S7 independent verification]
    RESULT -->|success=false and ambiguous=false| FAIL[FAILED]
    RESULT -->|ambiguous=true| AMB[WAITING_DECISION]
    AMB --> RULE[Blind retry prohibited]
    RULE --> HUMAN{Operator action}
    HUMAN -->|/opsswarm investigate ...| READ[Read-only reconciliation investigation]
    HUMAN -->|/opsswarm abort| ABORT[ABORTED]
    HUMAN -->|/opsswarm resume| SAFE{Safe checkpoint exists?}
    SAFE -->|Yes| VERIFY
    SAFE -->|No| STAY[Remain governed; ask for explicit next step]
```

The recovery prompt itself instructs the OpenClaw recovery responder to preserve idempotency where supported and not blindly repeat an operation when transport becomes ambiguous after a write.

## 9. Independent verification and closure

```mermaid
flowchart TD
    EXECOK[Execution success] --> VERIFYING[VERIFYING]
    VERIFYING --> S7[S7 uses observability-investigator]
    S7 --> READONLY[Read-only metrics / health / logs / service state]
    READONLY --> CHECK{verified=true and confidence >= threshold?}
    CHECK -->|No| FAILED[FAILED]
    FAILED --> OPEN[GitHub Issue remains open]
    CHECK -->|Yes| RESOLVED[RESOLVED]
    RESOLVED --> SUMMARY[Resolved comment]
    SUMMARY --> PM[Postmortem comment]
    PM --> CORR[Optional corrective-action Issues]
    CORR --> CLOSE[Close incident Issue]
```

S7 receives the execution result only as context. The verification prompt explicitly states that executor success is **not proof**.

## 10. Implemented state machine

The exact runtime states are:

```text
OPEN
TRIAGE
INVESTIGATING
DIAGNOSED
PLANNING
EXECUTING
VERIFYING
WAITING_APPROVAL
WAITING_DECISION
WAITING_INPUT
RESOLVED
FAILED
ABORTED
```

The transitions used by the implemented control flow are summarized below.

```mermaid
stateDiagram-v2
    [*] --> OPEN
    OPEN --> TRIAGE: start_issue
    TRIAGE --> INVESTIGATING: incident normalized

    INVESTIGATING --> DIAGNOSED: findings + root-cause synthesis complete
    DIAGNOSED --> WAITING_INPUT: uncertain / low-confidence RCA
    DIAGNOSED --> PLANNING: RCA above threshold

    PLANNING --> EXECUTING: policy AUTO
    PLANNING --> WAITING_APPROVAL: policy APPROVAL
    PLANNING --> WAITING_DECISION: policy DECISION
    PLANNING --> WAITING_INPUT: policy INPUT
    PLANNING --> FAILED: denied / planning failure path

    WAITING_APPROVAL --> EXECUTING: authorized approve
    WAITING_INPUT --> INVESTIGATING: provide / investigate
    WAITING_DECISION --> INVESTIGATING: investigate
    WAITING_DECISION --> EXECUTING: approved selected option when valid

    EXECUTING --> WAITING_DECISION: ambiguous write
    EXECUTING --> FAILED: definite execution failure
    EXECUTING --> VERIFYING: successful execution

    VERIFYING --> RESOLVED: S7 verified above threshold
    VERIFYING --> FAILED: verification failed / below threshold
    FAILED --> VERIFYING: resume only with successful execution checkpoint

    OPEN --> ABORTED: authorized abort
    TRIAGE --> ABORTED: authorized abort
    INVESTIGATING --> ABORTED: authorized abort
    DIAGNOSED --> ABORTED: authorized abort
    PLANNING --> ABORTED: authorized abort
    WAITING_APPROVAL --> ABORTED: authorized abort
    WAITING_DECISION --> ABORTED: authorized abort
    WAITING_INPUT --> ABORTED: authorized abort
    EXECUTING --> ABORTED: authorized abort command if processed
    VERIFYING --> ABORTED: authorized abort command if processed

    RESOLVED --> [*]
    ABORTED --> [*]
```

### State-machine caveat

`RunRecord.transition()` currently assigns a new state without an explicit transition table. The orchestrator determines valid operational sequencing. Strengthening state monotonicity/transition guards is part of reliability hardening and should be tested rather than assumed.

## 11. Failure and resume matrix

| Condition | Current state/result | Human-visible behavior | Evidence / next step |
| --- | --- | --- | --- |
| Required Issue label missing | start rejected | no governed run starts | correct Issue labels |
| S2 returns no tasks | runtime error | incident cannot progress | investigate orchestration failure |
| Task graph cannot make progress | runtime error | incident cannot progress | graph is unsatisfied/cyclic |
| RCA uncertain / low confidence | `WAITING_INPUT` | decision-request comment | provide context or request more investigation |
| Policy needs risky-write approval | `WAITING_APPROVAL` | approval request | `/opsswarm approve <option-id>` |
| Multiple options | `WAITING_DECISION` | decision request | explicit command / more investigation |
| Missing business constraint | `WAITING_INPUT` | question | `/opsswarm provide ...` |
| Policy denies plan | `FAILED` | failure comment | issue stays open |
| Write outcome ambiguous | `WAITING_DECISION` | blind-retry warning | reconcile/read/abort/safe resume |
| Recovery definite failure | `FAILED` | recovery-failed comment | issue stays open |
| S7 verification fails | `FAILED` | verification-failed comment | issue stays open |
| S7 verification succeeds | `RESOLVED` | summary + postmortem | issue closes |
| Authorized abort | `ABORTED` | aborted comment | issue stays open |

## 12. Evidence produced by the flow

The current orchestrator writes machine-readable evidence events including:

- `S1.incident`
- `S2.task_graph`
- `S4.finding`
- `RCA.root_cause`
- `S3.recovery_plan`
- `S6.human_gate`
- `human.free_text`
- `human.input`
- `human.approval`
- `S5.execution`
- `S7.verification`

Runtime storage locations are documented in [OPERATIONS.md](./OPERATIONS.md). These events complement the GitHub Issue, which remains the user-visible incident record.

## 13. Flow-to-code map

| Flow | Primary implementation |
| --- | --- |
| GitHub webhook ingress | `opsswarm/api.py::github_webhook` |
| Monitoring ingress | `opsswarm/api.py::monitoring_event` |
| Start / correlation | `Orchestrator.start_issue` |
| Investigation DAG | `Orchestrator._investigate`, `skill_logic.build_tasks` |
| Specialist dispatch | `_investigate`, `skill_logic.execute_task` |
| Root-cause synthesis | `skill_logic.synthesize_root_cause` |
| Recovery planning | `Orchestrator._plan`, `skill_logic.make_recovery_plan` |
| Policy | `PolicyEngine.classify_plan` |
| Recovery execution | `Orchestrator._execute_option`, `skill_logic.execute_recovery` |
| Verification | `Orchestrator._verify`, `skill_logic.verify_recovery` |
| Human comments/commands | `Orchestrator.handle_comment`, `commands.parse_command` |
| State definitions | `opsswarm/models.py::RunState` |

## 14. Documentation consistency rules

When runtime behavior changes, update this document in the same PR if the change affects:

- a `RunState` transition;
- a human command or authority boundary;
- a Skill handoff;
- a policy classification branch;
- the definition of successful recovery;
- evidence events;
- GitHub/OpenClaw trust boundaries.

New diagrams must distinguish **implemented behavior** from **planned hardening**. In particular, do not add a `RECOVERING` runtime state or claim distributed idempotency unless production code implements and tests it.

## 15. Related documents

- [Architecture](./ARCHITECTURE.md)
- [Operations](./OPERATIONS.md)
- [Security](./SECURITY.md)
- [Installation](./INSTALLATION.md)
- Issue #9 — persistence/idempotency/concurrency/restart hardening
- Issue #10 — architecture documentation
- Issue #11 — runtime flow documentation
