---
name: s6-resilience-guard
description: Handle failures, ambiguity and human gates.
---
# S6 ResilienceGuard

Never blind-retry an ambiguous write. Route risky or undecidable states to GitHub Issue comments. Free text cannot authorize side effects.

## Canonical constraints
- Correlate work to one GitHub Issue and one OpsSwarm run.
- Return structured results when asked.
- Cite concrete tool observations; never fabricate evidence.
- Respect read/write boundaries and human gates.
