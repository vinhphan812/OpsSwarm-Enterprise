# Architecture

Canonical autonomous control loop:

`STORE EVENTS → OBSERVE → DETECT → INVESTIGATE → PLAN → SIMULATE → DECISION CONTEXT GUARD → ACT → LIVE TWIN → VERIFY`

Rules:
- Gemini cannot write to live Firestore state directly.
- Simulated actions are separated from live state.
- Every live commit passes DCG.
- stale context fails closed.
- quantitative impact must come from models/simulation, not fabricated LLM output.

Decision log: `docs/adr/`. A pull request that changes one of these rules links the ADR it tracks, or adds a superseding record in the same change.
