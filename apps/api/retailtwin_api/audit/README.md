# Agent-action audit

ADR 0019. Import `record_trace` and `records_from_decision` from `retailtwin_api.audit.trail`.

The day-0 `agent_actions` table is unchanged. This log appends stage rows to `retailtwin.agent_action_audit`: trigger, evidence, decision, guard, execution, and observed. One `correlation_id` is one trace. A denial has no execution row and no observed row.

`predicted_impact` is the decision's `kpi_score`. `-1.0` is unscored. The reason summary is short text already on the decision, not a prompt. Evidence refs are bundle ids and entity versions. A repeated payload is a duplicate. A different payload for the same record id is a conflict.

`InMemoryAuditLog` is the test stand-in. `BigQueryAuditLog` runs a query job on `retailtwin-ai-511002` and does not stream. No route calls this module. It does not write the Live Twin.

The table is created only by `infrastructure/gcp/apply-agent-action-audit.sh` after `CONFIRM_GCP_AGENT_AUDIT=yes`. This repository does not run that command.
