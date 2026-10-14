# 0019. Record agent-action provenance in BigQuery

Date: 2026-10-14

## Status

Accepted

## Context

Issue #35 requires a correlated trace of one autonomous run: the trigger, the evidence refs, the decision, the guard result, the execution, and the observed result. A failure has to be visible after the fact. Hidden chain-of-thought and credentials must not be stored.

`retailtwin.agent_actions` already exists. ADR 0005 gives it the same eight-field envelope as `sales_events`, because it lands `agent.*` store events. That envelope has no decision id, evidence ref, guard verdict, or verifier status. Widening it would change the day-0 event contract and mix sale rows with audit columns. Keeping the trace only in the process-memory guard and verifier sinks loses it when the process exits. Recomputing the #33 KPI inside the audit would be a second formula.

## Decision

`record_trace` in `apps/api/retailtwin_api/audit/trail.py` appends one row per stage to `retailtwin.agent_action_audit`. The stages are `trigger`, `evidence`, `decision`, `guard`, `execution`, and `observed`. Rows from one run share `correlation_id`. A run that stops at the guard has no execution row and no observed row.

The decision row copies `expected_impact.kpi_score` as its predicted impact. `-1.0` stays the unscored sentinel. The reason summary is the decision's short description, capped, and it is not a prompt. Tool parameters are the canonical action JSON already hashed by the guard. Evidence is stored as bundle id plus entity version, not the evidence payload.

A second write of the same payload is a duplicate. A different payload for the same `record_id` is a conflict and does not replace the row. Writes are BigQuery query jobs on `retailtwin-ai-511002` in `us-central1`, with `NOT EXISTS` on `record_id`. There is no streaming insert and no route. The Live Twin is not written. `agent_actions` is unchanged.

## Consequences

One flagship correlation id can be queried back in stage order, including a denial that never executed. The table is not created by this record; `infrastructure/gcp/apply-agent-action-audit.sh` creates it only when `CONFIRM_GCP_AGENT_AUDIT=yes`. The in-memory log is the test stand-in and is not durable. Gates G02–G06 and foundation gate #10 stay unpassed. Issue #6 still owns the Firestore Live Twin.

- Pull request:
- Issue: #35
- Supersedes:
- Superseded by:
