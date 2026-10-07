# RetailTwin AI

**Context-Guarded Autonomous 3D Retail Digital Twin**

RetailTwin AI is an autonomous retail operations prototype for the Google Cloud AI Builder Cup 2026.

Core loop:

`OBSERVE → DETECT → INVESTIGATE → PLAN → SIMULATE → GUARD → ACT → VERIFY`

The system combines a 3D retail digital twin, Gemini on Vertex AI, Google ADK, event-driven store telemetry, simulation, and a deterministic Decision Context Guard (DCG) before any live-state commit.

## Architecture

- Frontend: React + TypeScript + React Three Fiber / Three.js
- Backend: Python + FastAPI
- AI: Gemini on Vertex AI + Google ADK
- Live twin state: Firestore
- Historical/analytical data: BigQuery
- Events: Pub/Sub
- Compute/tools: Cloud Run
- Assets: Cloud Storage
- Authentication: Firebase Auth
- Guard layer: Decision Context Guard

## Repository layout

```
apps/
  web/
  api/
agents/
  orchestrator/
  observer/
  investigator/
  planner/
  simulator/
  executor/
  verifier/
guard/
  decision-context-guard/
services/
  twin/
  simulation/
  optimizer/
  forecasting/
data/
  schemas/
  synthetic/
  seed/
infrastructure/
  gcp/
  firebase/
assets/
  3d/
docs/
  architecture/
  competition/
  demo/
tests/
.github/
  workflows/
```

## MVP target

A store event autonomously triggers the agent, which investigates a retail anomaly, generates and simulates a candidate action, passes Decision Context Guard validation, commits an allowed action to the live twin, and visibly updates the 3D store.

## Safety principle

> The LLM never owns the store state. The Digital Twin owns the truth; Gemini reasons over that truth and acts only through constrained tools.

Live actions must never bypass Decision Context Guard.
