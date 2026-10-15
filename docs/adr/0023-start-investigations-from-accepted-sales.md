# 0023. Start investigations from accepted sales

Date: 2026-10-15

## Status

Accepted

## Context

Gate G03 (#50) requires a store event to start the agent with no user prompt, with correlated Agent Activity visible. The Observer (#12, ADR 0010) can turn a pulled `sale.completed` message into one `InvestigationStart`, with a ledger that refuses duplicates. Nothing called it. The investigator, planner, guard, Executor and re-plan (ADRs 0011–0018) were libraries without a runtime trigger.

`GET /agent/events` and `GET /simulations/{id}/candidates` returned 500 on `main`. The `SimulationRepository` wired by #151 implements neither `list_agent_events` nor `list_candidates`.

Two alternatives were set aside:

- **A Pub/Sub pull worker for `store-events`.** It cannot be exercised from CI or a workstation without GCP credentials. It can reuse the same starter later.
- **Committing autonomously after planning.** Commits stay behind the approve route, the Decision Context Guard and the guarded Executor (ADRs 0014–0016) until the autonomous-commit policy is decided.

## Decision

`POST /events` hands each newly accepted `sale.completed` to the Observer's `consume_available` through an in-process `MemoryPipe`, `MemoryActivationLedger` and `MemoryQuarantine`. Duplicates, conflicts and other event types start nothing. The receipt gains `investigation_id` when an investigation started.

The starter is `AutonomousInvestigations` (`agents/orchestrator/autonomy.py`). Its handoff only records `OBSERVE started` and queues the start, so the Observer commits and acknowledges at once. A FastAPI background task then drains the queue:

1. **INVESTIGATE.** `investigate` gathers versioned evidence. The status is `completed`, or `insufficient_evidence` when a mandatory source is missing.
2. **PLAN.** `plan` produces candidates at the current store context version.
3. **SIMULATE.** The planner-preferred candidate is recorded as a `pending` simulation with provenance `autonomous-investigation`, and its Decision is put in the `DecisionSource` for `POST /simulations/{id}/approve`.

Every step appends one `AgentActivityEntry` to `AgentActivityLog`, which now backs `GET /agent/events`. Each entry carries the event's correlation id, the investigation id as `run_id`, and the SKU as `focus`.

Failures are recorded as a `failed` entry and are never raised. That covers a provider failure, a planner error and a proposal store failure. The investigation never writes the Live Twin.

The feature is gated by `AUTONOMY_ENABLED` (default `false`). When enabled, the provider comes from `create_provider(llm_config_from_settings(...))` (ADR 0020). A provider that cannot be built leaves autonomy off and logs `autonomy.unavailable`; the other routes keep serving.

`SimulationRepository` gains `record`, `list_candidates` and `list_agent_events`. `list_candidates` returns an empty page for a known run, because scored candidates are not stored there yet.

## Consequences

- **Reproducible G03 run.** `tests/e2e/gates/g03_autonomous_gate.py` posts one sale and shows:
  - the Observer handoff;
  - a first model request that holds only the event handoff;
  - the four activity stages;
  - a duplicate that starts nothing;
  - an unchanged Live Twin;
  - an autonomous proposal that commits only through the guarded route;
  - a provider failure that is visible and harmless.
- **Process memory.** The pipe, ledger, activity, proposals and decisions live in process memory, so several instances do not share them.
- **Missing bindings in production.** The non-inventory mandatory sources (sales, forecast, promotions, planogram) need production read ports. Until those are bound, a real run stops at `INVESTIGATE insufficient_evidence` / `PLAN failed`.
- **Follow-up work.** Scoring with the simulator (#15) inside the run, a Pub/Sub trigger, and autonomous commit remain later decisions.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/199
- Issue: #50
- Supersedes:
- Superseded by:
