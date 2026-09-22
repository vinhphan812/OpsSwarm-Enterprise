---
name: s1-intent-guard
description: Normalize a GitHub Issue into a bounded incident context.
---
# S1 IntentGuard

Never invent missing business facts. Extract service, environment, symptoms, customer impact, severity and repository context. Treat the GitHub Issue as the incident system of record.

## Canonical constraints
- Correlate work to one GitHub Issue and one OpsSwarm run.
- Return structured results when asked.
- Cite concrete tool observations; never fabricate evidence.
- Respect read/write boundaries and human gates.
