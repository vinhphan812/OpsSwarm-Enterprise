# OpsSwarm Enterprise

**Governed multi-agent incident response with OpenClaw as the AI runtime and GitHub Issues as the human control surface.
**

OpsSwarm Enterprise coordinates incident investigation, recovery planning, human authorization, bounded execution,
evidence capture, and independent verification through eight governed Skills (S1–S8). It is intentionally designed so
that AI agents can reason and use tools, while OpsSwarm retains workflow authority, policy enforcement, state, evidence
correlation, and terminal decisions.

> **Current status:** the runtime is version **2.1.0**. Documentation and quality hardening for **v2.2** are in
> progress. The repository currently has a working OpenClaw + GitHub control architecture and baseline tests, but the
> planned 192 Skill self-tests, full CI/security gates, stronger idempotency/restart guarantees, and reproducible
> release
> pipeline are not yet complete. See [v2.2 Quality & Skill Hardening](../../issues/1).

## Architecture principles

The current architecture is built around these boundaries:

1. **OpenClaw is the only AI/agent runtime.**
2. **One GitHub Issue is the system of record for one incident.**
3. **GitHub Issue comments are the only human input/decision channel.**
4. **OpsSwarm S1–S8 form the governed control plane.**
5. **Investigation is read-only by default.**
6. **Agent recommendations are not execution authority.**
7. **Risky writes require an explicit authorized GitHub command.**
8. **Free-text comments never authorize side effects.**
9. **Ambiguous writes are never blindly retried.**
10. **S7 must independently verify recovery before the Issue can close.**

```mermaid
flowchart LR
    SRC[Monitoring / User] --> GH[GitHub Issue]
    HUMAN[Human Operator] -->|comments / explicit commands| GH
    GH --> API[OpsSwarm API / Webhook]
    API --> S8[S8 OrchestrationHub]
    S8 --> SKILLS[S1–S7 Governed Skills]
    SKILLS --> OC[OpenClaw Runtime]
    OC --> AGENTS[Specialist Agent Profiles]
    AGENTS --> TOOLS[Enterprise Tools / APIs]
    TOOLS --> EVID[Observations / Receipts / Evidence]
    EVID --> S8
    S8 --> STORE[Run Store + Evidence Store]
    S8 --> GH
```

For the implementation-aligned architecture and trust boundaries, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
For runtime sequences and state transitions, see [`docs/FLOWS.md`](docs/FLOWS.md).

## Canonical incident lifecycle

```mermaid
flowchart TD
    SRC[Monitoring / User] --> GH[GitHub Issue]
    GH --> API[OpsSwarm webhook / monitoring ingress]
    API --> S8[S8 OrchestrationHub]
    S8 --> S1[S1 IntentGuard<br/>normalize and triage]
    S1 --> S2[S2 TaskGraph<br/>read-only investigation DAG]
    S2 --> S4[S4 RoleDispatch]
    S4 --> OC[OpenClaw specialist agents]
    OC --> S5A[S5 CollabExec<br/>structured findings and evidence]
    S5A --> RCA[Root-cause synthesis]
    RCA --> S3[S3 HorizonPlan<br/>remediation options]
    S3 --> POLICY{Policy classification}

    POLICY -->|AUTO| EXEC[S5 bounded recovery execution]
    POLICY -->|risky write| WA[WAITING_APPROVAL]
    POLICY -->|multiple options / ambiguous state| WD[WAITING_DECISION]
    POLICY -->|missing business context| WI[WAITING_INPUT]
    POLICY -->|DENY| FAIL[FAILED / fail closed]

    WA --> CMD[Explicit /opsswarm command in GitHub]
    WD --> CMD
    WI --> CMD
    CMD --> S8
    S8 -->|authorized approval / decision / input| EXEC

    EXEC --> RESULT{Execution result}
    RESULT -->|success| S7[S7 ObserveVerify<br/>independent recovery verification]
    RESULT -->|ambiguous write| S6[S6 ResilienceGuard<br/>reconcile; never blind retry]
    RESULT -->|definite failure| FAIL
    S6 --> WD

    S7 --> VERIFIED{Verified above threshold?}
    VERIFIED -->|yes| FINAL[Final GitHub summary + postmortem]
    FINAL --> CLOSE[Close Issue]
    VERIFIED -->|no| FAIL2[FAILED / Issue remains open]
```

The exact implemented runtime states are defined by `RunState` in `opsswarm/models.py` and documented in [
`docs/FLOWS.md`](docs/FLOWS.md).

## S1–S8 Skill model

| Skill                   | Responsibility                                                                                                              |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| **S1 IntentGuard**      | Normalize the GitHub Issue into bounded incident context without inventing missing facts.                                   |
| **S2 TaskGraph**        | Build the minimum read-only investigation DAG using OBSERVE / INVESTIGATE / DIAGNOSE tasks.                                 |
| **S3 HorizonPlan**      | Produce evidence-supported remediation options and risk-aware recovery plans.                                               |
| **S4 RoleDispatch**     | Dispatch dependency-ready tasks to bounded OpenClaw specialist profiles.                                                    |
| **S5 CollabExec**       | Aggregate structured evidence and execute only the selected/authorized recovery option.                                     |
| **S6 ResilienceGuard**  | Enforce fail-closed handling for policy gates, ambiguity, rejection, and human escalation.                                  |
| **S7 ObserveVerify**    | Independently verify service/business recovery using read-only evidence.                                                    |
| **S8 OrchestrationHub** | Own lifecycle, state transitions, cross-Skill ordering, GitHub synchronization, evidence correlation, and terminal outcome. |

The current implementation maps these architectural Skills across `opsswarm/orchestrator.py`, `opsswarm/skill_logic.py`,
`opsswarm/prompts.py`, `opsswarm/policy.py`, and the domain models. Not every Skill is a separate Python service/class
today.

## OpenClaw agent profiles

The supplied OpenClaw configuration defines these profiles:

- `opsswarm-incident-manager`
- `opsswarm-observability-investigator`
- `opsswarm-application-investigator`
- `opsswarm-infrastructure-investigator`
- `opsswarm-database-investigator`
- `opsswarm-recovery-responder`
- `opsswarm-communications-postmortem`

Investigation profiles are intended to operate read-only. Recovery execution is bounded by OpsSwarm policy and explicit
authorization rules.

## Human control through GitHub

Only explicit `/opsswarm` commands carry workflow authority:

```text
/opsswarm approve <option-id>
/opsswarm reject
/opsswarm investigate <request>
/opsswarm provide <information>
/opsswarm abort
/opsswarm resume
```

A comment such as `rollback looks fine` is stored as information only and **cannot** authorize a side effect.

Default authorization policy in `config/production.yaml`:

| Risk          | Default policy   |
|---------------|------------------|
| `read`        | `AUTO`           |
| `safe_write`  | `AUTO`           |
| `risky_write` | `HUMAN_APPROVAL` |
| `destructive` | `DENY`           |

By default, input requires at least GitHub `read` permission, while approval/abort requires `maintain` permission.

## Requirements

- Python **3.11+**
- Git
- A GitHub repository with Issues enabled
- A GitHub token with permissions sufficient to read/write Issues and read collaborator permission for the target
  repository
- A publicly/reversibly reachable HTTPS endpoint for GitHub webhooks in non-local deployments
- OpenClaw installed and configured with a model provider
- Enterprise tools/APIs exposed to the appropriate OpenClaw profiles according to least privilege

## Quick start

### 1. Clone and create a Python environment

```bash
git clone https://github.com/vinhphan812/OpsSwarm-Enterprise.git
cd OpsSwarm-Enterprise

python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e '.[dev]'
```

### 2. Prepare environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```text
GITHUB_TOKEN=...
GITHUB_REPO=owner/repository
GITHUB_WEBHOOK_SECRET=...
OPSWARM_OPENCLAW_BIN=openclaw
OPSWARM_CONFIG=config/production.yaml
OPSWARM_DATA_DIR=runtime-data
```

The current runtime reads environment variables from the process environment; it does **not** automatically load `.env`.
On a Unix-like shell you can load the file with:

```bash
set -a
source .env
set +a
```

For production, prefer your service manager, container runtime, or secret manager instead of storing production
credentials in a shell-loaded file.

### 3. Install and configure OpenClaw

Install OpenClaw separately and configure/authenticate the model provider you intend to use. Initialize a baseline
gateway:

```bash
openclaw setup --baseline
```

Edit `openclaw/openclaw.patch.json5` and replace every repository-path placeholder with the absolute path to this
checkout, then validate and apply it:

```bash
openclaw config patch --file openclaw/openclaw.patch.json5 --dry-run
openclaw config patch --file openclaw/openclaw.patch.json5
openclaw config validate
openclaw gateway start
openclaw agents list
```

Optional profile smoke check:

```bash
openclaw agent \
  --agent opsswarm-observability-investigator \
  --message "Return only: OK" \
  --json
```

### 4. Run local quality gates

Install the development extras, then use the Make targets that mirror the `CI` workflow:

```bash
make install
make lint        # Ruff lint plus the explicitly scoped format check
make typecheck   # Mypy over the opsswarm package
make test-unit   # Tests marked unit
make test        # Complete test suite
make coverage    # Complete suite with the required >=90% coverage gate
make build       # Wheel and source distribution
make ci          # Lint, type check, test, coverage, and build
```

The equivalent direct commands are:

```bash
python -m ruff check .
python -m ruff format --check opsswarm/commands.py opsswarm/policy.py opsswarm/webhook.py
python -m mypy
python -m pytest -q -m unit
python -m pytest -q
python -m pytest -q --cov=opsswarm --cov-report=term-missing --cov-fail-under=90
python -m build
```

The checked-in configuration for Ruff, Mypy, pytest, coverage, and build tooling is in `pyproject.toml`. The format gate
is deliberately scoped to the listed runtime modules while legacy formatting debt is retired; lint still checks the
repository for syntax and undefined-name failures. A local failure is expected whenever any enforced gate is unmet,
including coverage below 90%. These commands describe local parity only and do not assert that GitHub Actions has run.

### 5. Start OpsSwarm

```bash
export OPSWARM_CONFIG=config/production.yaml
uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088
```

Health check:

```bash
curl http://localhost:8088/health
```

Expected shape:

```json
{
  "ok": true,
  "version": "2.1.0",
  "architecture": "openclaw+github"
}
```

## GitHub webhook setup

Configure a repository webhook with:

```text
Payload URL:  https://<your-opsswarm-host>/webhooks/github
Content type: application/json
Secret:       same value as GITHUB_WEBHOOK_SECRET
Events:       Issues, Issue comments
```

OpsSwarm validates the GitHub webhook body with HMAC-SHA256 before accepting the event.

For a human-created incident, open an Issue using the supplied incident template and keep the required `opsswarm` label.
An `issues.opened` webhook starts the governed run.

## Machine-created monitoring incidents

Monitoring systems can create normalized incidents through:

```text
POST /hooks/monitoring
```

Example:

```bash
curl -X POST http://localhost:8088/hooks/monitoring \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "[SEV2] booking-api failures",
    "service": "booking-api",
    "symptom": "HTTP 5xx > 30%",
    "customer_impact": "customers cannot confirm bookings",
    "environment": "production",
    "severity_label": "sev:2"
  }'
```

OpsSwarm creates the GitHub Issue first and then starts the same Issue-centered orchestration flow.

## Runtime API

Current FastAPI endpoints include:

```text
GET  /health
GET  /runs
GET  /runs/{issue_number}
GET  /runs/{issue_number}/evidence
POST /webhooks/github
POST /hooks/monitoring
```

The runtime API is an operational interface; GitHub remains the user-visible incident system of record.

## Evidence and persistence

By default, machine-readable runtime data is stored under:

```text
runtime-data/runs/*.json
runtime-data/evidence/*.jsonl
```

The run store persists the current `RunRecord`; the evidence store appends structured provenance such as normalized
incident context, task graphs, findings, root-cause artifacts, plans, human gates/approvals, execution results, and S7
verification.

The current runtime reloads persisted run records at startup. Stronger distributed webhook deduplication, cross-process
concurrency control, and restart/reconciliation semantics are part of the v2.2 hardening work and are **not** claimed as
completed guarantees.

## Security and authority model

Key invariants:

- GitHub webhook signatures are verified.
- Human authority is derived from GitHub collaborator permission.
- Free-text comments never authorize side effects.
- Risky writes require explicit authorized approval.
- Destructive actions are denied by default even if a user attempts to approve them.
- Investigation prompts constrain specialist work to read-only scope.
- OpenClaw output is validated into typed Pydantic artifacts before use.
- Ambiguous write outcomes are not blindly retried.
- S7 independently verifies recovery; executor success is context, not proof.
- Failed or unverified recovery leaves the Issue open.

For production deployments, also apply OpenClaw sandbox/tool allowlists and least-privilege credentials for every
specialist profile, especially the recovery responder.

See [`docs/SECURITY.md`](docs/SECURITY.md).

## Testing and quality status

Run the current suite with:

```bash
pytest -q
```

Quality hardening is tracked in the v2.2 epic and child issues. Planned gates include:

- production-grade S1–S8 Skill contracts;
- 24 substantive self-tests per Skill (192 total);
- layered unit, contract, integration, E2E, fault, security, and smoke suites;
- GitHub Actions quality gates;
- Skill validation gates;
- dependency/security/secret/license/SBOM checks;
- reproducible wheel build and clean-install verification;
- stronger persistence/idempotency/concurrency/restart testing.

These are targets, not current PASS claims.

## Repository layout

```text
OpsSwarm-Enterprise/
├── opsswarm/                  # governed Python runtime
├── skills/                    # S1–S8 Skill definitions
├── openclaw/                  # OpenClaw patch and specialist workspaces
├── config/                    # test/production configuration
├── docs/                      # architecture, flows, installation, operations, security
├── tests/                     # current baseline test suite
├── scripts/                   # helper scripts
├── deploy/                    # deployment assets
├── .github/                   # Issue templates; CI workflows are v2.2 work
├── pyproject.toml
├── Makefile
└── LICENSE
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system context, S1–S8 responsibility map, authority, evidence, trust
  boundaries, invariants.
- [`docs/FLOWS.md`](docs/FLOWS.md) — end-to-end sequences, exact runtime state machine, human gates, ambiguous-write
  handling.
- [`docs/INSTALLATION.md`](docs/INSTALLATION.md) — installation and OpenClaw/GitHub setup.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — human-created and machine-created incident operation.
- [`docs/SECURITY.md`](docs/SECURITY.md) — security and authority model.
- [`openclaw/README.md`](openclaw/README.md) — OpenClaw-specific configuration notes.

## Current limitations

The following should be treated as open hardening areas rather than production guarantees:

- no complete 192-test Skill campaign yet;
- the repository includes a SHA-pinned GitHub Actions `CI` workflow for Python 3.11–3.13 quality gates; local commands
  are documented above, but no GitHub execution is claimed here;
- no strong multi-process transaction/locking model yet;
- persistence is currently file-based rather than a transactional database;
- restart/resume behavior is not yet proven for every state/fault combination;
- Skill folders are still being expanded into full production-grade contracts;
- external enterprise tool behavior depends on the capabilities and credentials configured for each OpenClaw profile.

See issues #1, #2, #3, #4, #5, #6, #7, #8, and #9 for the v2.2 hardening plan.

## License

OpsSwarm Enterprise is released under the **MIT License**. See [`LICENSE`](LICENSE).

The MIT license applies to the original project material covered by this repository's license. Third-party libraries,
tools, generated integrations, or vendored materials remain subject to their respective licenses and notices.

Copyright (c) 2026 Phan Thanh Vinh.
