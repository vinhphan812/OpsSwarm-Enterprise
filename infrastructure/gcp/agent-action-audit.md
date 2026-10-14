# Agent-action audit

Issue #35. ADR [0019](../../docs/adr/0019-record-agent-action-provenance-in-bigquery.md).

`retailtwin.agent_actions` still lands thin `agent.*` store events. Provenance for one autonomous run is a separate append-only table, `retailtwin.agent_action_audit`. A row is one stage: `trigger`, `evidence`, `decision`, `guard`, `execution`, or `observed`. `correlation_id` is the trace. The table is not the Live Twin, and it does not store a prompt or a chain of thought.

Create it only with `CONFIRM_GCP_AGENT_AUDIT=yes ./infrastructure/gcp/apply-agent-action-audit.sh`. That command refuses any project other than `retailtwin-ai-511002` and any region other than `us-central1`. It does not change `agent_actions`.

Query one run:

```sql
SELECT record_id, correlation_id, decision_id, action_id, stage, trigger_ref,
       evidence_refs, reason_summary, tool_params, simulation_id, predicted_impact,
       guard_verdict, guard_reason, execution_status, observed_status, recorded_at
FROM `retailtwin-ai-511002.retailtwin.agent_action_audit`
WHERE correlation_id = @correlation_id
ORDER BY CASE stage
  WHEN 'trigger' THEN 1
  WHEN 'evidence' THEN 2
  WHEN 'decision' THEN 3
  WHEN 'guard' THEN 4
  WHEN 'execution' THEN 5
  WHEN 'observed' THEN 6
  ELSE 7 END,
  action_id, record_id
```

`predicted_impact` of `-1.0` is the planner's unscored sentinel. It is not a KPI this table calculated.
