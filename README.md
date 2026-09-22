# OpsSwarm Enterprise v2.1.0
## OpenClaw + GitHub Incident Control Architecture

This release deliberately narrows OpsSwarm to one operational architecture:

- **OpenClaw is the only AI/agent runtime.**
- **One GitHub Issue is the system of record for one incident.**
- **GitHub Issue comments are the only human decision/input channel.**
- **OpsSwarm S1-S8 remains the governed control plane.**
- **An incident is never closed until S7 independently verifies recovery.**

### Canonical flow

```text
Monitoring/User
    -> GitHub Issue
    -> OpsSwarm webhook
    -> S1 triage
    -> S2 investigation TaskGraph
    -> S4 OpenClaw specialist dispatch
    -> S5 evidence aggregation
    -> Root-cause synthesis
    -> S3 remediation plan
    -> policy
       -> auto, or
       -> GitHub comment: WAITING_DECISION / WAITING_APPROVAL / WAITING_INPUT
    -> S5 recovery execution through OpenClaw
    -> S6 resilience control
    -> S7 independent verification
    -> final GitHub comment + postmortem
    -> close issue
```

### Architecture documentation

The repository includes implementation-aligned architecture and flow documentation with Mermaid diagrams:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system context, control plane vs OpenClaw agent plane, S1-S8 responsibility map, policy/human authority, evidence/persistence, trust boundaries, and architecture invariants.
- [`docs/FLOWS.md`](docs/FLOWS.md) — human and machine incident ingress, investigation, planning, approval/decision/input gates, execution, ambiguous-write handling, exact `RunState` state machine, S7 verification, and issue closure.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — operator-facing incident creation, human commands, and runtime evidence locations.
- [`docs/SECURITY.md`](docs/SECURITY.md) — security and authority boundaries.

The diagrams describe **implemented behavior**. Planned hardening such as stronger distributed idempotency or additional runtime states must not be represented as current behavior until code and tests exist.

### Human commands

Only explicit commands carry authority for side effects:

```text
/opsswarm approve <option-id>
/opsswarm reject
/opsswarm investigate <request>
/opsswarm provide <information>
/opsswarm abort
/opsswarm resume
```

Free-text comments are treated as information only; they are never interpreted as approval.

### Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e '.[dev]'
cp .env.example .env
pytest -q
```

Install/configure OpenClaw, then apply the supplied patch:

```bash
openclaw setup --baseline
openclaw config patch --file openclaw/openclaw.patch.json5 --dry-run
openclaw config patch --file openclaw/openclaw.patch.json5
openclaw config validate
openclaw gateway start
openclaw agents list
```

Set the repository-specific absolute paths in `openclaw/openclaw.patch.json5` before applying it.

Run OpsSwarm:

```bash
export OPSWARM_CONFIG=config/production.yaml
uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088
```

Configure the GitHub repository webhook to POST to:

```text
https://<your-opsswarm-host>/webhooks/github
```

Subscribe to **Issues** and **Issue comments**. Use the same secret as `GITHUB_WEBHOOK_SECRET`.

For machine incidents, send normalized monitoring events to:

```text
POST /hooks/monitoring
```

See `docs/INSTALLATION.md`, `docs/ARCHITECTURE.md`, `docs/FLOWS.md`, and `docs/OPERATIONS.md`.