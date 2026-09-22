# Architecture — FROZEN v2.1

## Decisions

1. OpenClaw is the only AI/agent runtime.
2. GitHub Issues are the incident system of record.
3. GitHub Issue comments are the only human input/decision channel.
4. One incident maps to one issue and one OpsSwarm run.
5. Investigation is read-only by default.
6. Side effects require policy authorization; risky writes require an explicit `/opsswarm approve <option>` command.
7. Free text is information only and never authorization.
8. S7 independently verifies recovery before the issue may close.

## Agent profiles

- incident-manager
- observability-investigator
- application-investigator
- infrastructure-investigator
- database-investigator
- recovery-responder
- communications-postmortem

## Task taxonomy

- OBSERVE
- INVESTIGATE
- DIAGNOSE
- REMEDIATE
- VERIFY

S2 creates only read-only OBSERVE/INVESTIGATE/DIAGNOSE work before root-cause synthesis. REMEDIATE is created only after a recovery plan and policy/human gate. VERIFY is always independent of the executor.

## Human gates

- WAITING_APPROVAL: one clear risky action, policy requires authorization.
- WAITING_DECISION: multiple materially different choices, or ambiguous write state.
- WAITING_INPUT: missing business/operational knowledge.

The GitHub comment command parser is deliberately narrow. Only the first line is parsed, and only `/opsswarm ...` commands carry authority.
