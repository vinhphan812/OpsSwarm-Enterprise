---
name: s2-task-graph
description: Create a bounded read-only investigation DAG.
---
# S2 TaskGraph

Allowed task classes are OBSERVE, INVESTIGATE and DIAGNOSE before remediation. Prefer parallel independent evidence gathering. Never prescribe restart as the default diagnosis.

## Canonical constraints
- Correlate work to one GitHub Issue and one OpsSwarm run.
- Return structured results when asked.
- Cite concrete tool observations; never fabricate evidence.
- Respect read/write boundaries and human gates.
