# API

Python FastAPI application/integration boundary.

## Current status

The API implementation is **not yet merged on `main`**. PR #57 is the current implementation work for issue #8. Until that PR is reconciled and merged, this directory on `main` is documentation/target scope only.

The immediate scaffold boundary is expected to provide:
- `GET /health`
- `GET /store`
- `GET /inventory/{sku}`
- `POST /events`

PR #57 currently uses the committed store fixture as a typed read model so frontend/API integration can be tested before Firestore issue #6 lands. That fixture is not the Live Twin.

## Target responsibility

The API is the browser-facing application boundary. The frontend must not write Firestore or other Live Twin storage directly.

Later action flow is:

```text
Frontend / Agent
      ↓
submit action/decision
      ↓
Decision Context Guard
      ↓
commit authorization
      ↓
Executor
      ↓
Live Twin
```

Endpoints such as action submission/guard validation are target contracts and must not be documented as available until their implementing issues land.

## Safety invariant

**No general-purpose API endpoint may bypass Simulation-before-Live, DCG, authorization, or Executor for a live mutation.**

See `docs/CURRENT_STATUS.md` for current repository maturity and `docs/ARCHITECTURE.md` for target architecture.
