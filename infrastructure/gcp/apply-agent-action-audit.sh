#!/usr/bin/env bash
# Create retailtwin.agent_action_audit for issue #35. Idempotent.
# Does not alter sales_events, inventory_events, or agent_actions.
# Does not create keys, change IAM, or buy a reservation.

set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-retailtwin-ai-511002}"
REGION="${GCP_REGION:-us-central1}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
TABLE="agent_action_audit"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="${ROOT}/infrastructure/gcp/schemas/agent-action-audit.json"

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"

die() {
  echo "error: $*" >&2
  exit 1
}

if [[ "${CONFIRM_GCP_AGENT_AUDIT:-}" != "yes" ]]; then
  die "Set CONFIRM_GCP_AGENT_AUDIT=yes to create ${TABLE} on ${PROJECT}."
fi
if [[ "$PROJECT" != "retailtwin-ai-511002" ]]; then
  die "Refusing ${PROJECT}. The audit table stays on retailtwin-ai-511002."
fi
if [[ "$REGION" != "us-central1" ]]; then
  die "Refusing region ${REGION}. The audit table stays in us-central1."
fi
if [[ "$DATASET" != "retailtwin" ]]; then
  die "Refusing dataset ${DATASET}."
fi

if bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.${TABLE}" >/dev/null 2>&1; then
  echo "Table already exists: ${TABLE}"
  exit 0
fi

echo "Creating table ${TABLE}"
bq --project_id="$PROJECT" --location="$REGION" mk \
  --table \
  --description="One stage of an autonomous run. One correlation_id is one trace. Not the Live Twin." \
  --schema="$SCHEMA" \
  --time_partitioning_field=recorded_at \
  --time_partitioning_type=DAY \
  --clustering_fields=store_id,correlation_id \
  --label=app:retailtwin \
  "${PROJECT}:${DATASET}.${TABLE}"
