#!/usr/bin/env bash
# Create the day-0 store-events subscription and BigQuery tables for issue #7.
# Idempotent. Does not create keys, change IAM, buy a reservation, or stream inserts.
# See infrastructure/gcp/store-events.md and docs/adr/0005-land-each-normalized-store-event-once.md.

set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-retailtwin-ai-511002}"
REGION="${GCP_REGION:-us-central1}"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
SUBSCRIPTION="${STORE_EVENTS_SUBSCRIPTION:-store-events-analytics}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="${ROOT}/infrastructure/gcp/schemas/normalized-event.json"

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"

die() {
  echo "error: $*" >&2
  exit 1
}

if [[ "${CONFIRM_GCP_STORE_EVENTS:-}" != "yes" ]]; then
  die "Set CONFIRM_GCP_STORE_EVENTS=yes to create the store-events tables and subscription on ${PROJECT}."
fi

if [[ "$PROJECT" != "retailtwin-ai-511002" ]]; then
  die "Refusing ${PROJECT}. Store events stay on retailtwin-ai-511002."
fi
if [[ "$REGION" != "us-central1" ]]; then
  die "Refusing region ${REGION}. Store events stay in us-central1."
fi
if [[ "$TOPIC" != "store-events" || "$SUBSCRIPTION" != "store-events-analytics" || "$DATASET" != "retailtwin" ]]; then
  die "Refusing a renamed topic, subscription, or dataset."
fi

echo "Project:      ${PROJECT}"
echo "Region:       ${REGION}"
echo "Topic:        ${TOPIC}"
echo "Subscription: ${SUBSCRIPTION}"
echo "Dataset:      ${DATASET}"
echo "Account:      $(gcloud config get-value account 2>/dev/null)"
echo
echo "This creates three BigQuery tables and one pull subscription if they are missing."
echo "It does not create service-account keys, change IAM, or start a streaming insert."
echo

billing_enabled="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)')" \
  || die "Cannot read billing for ${PROJECT}."
if [[ "$billing_enabled" != "True" ]]; then
  die "Billing is disabled on ${PROJECT}."
fi

if gcloud pubsub topics describe "$TOPIC" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Topic already exists"
else
  echo "Creating topic ${TOPIC}"
  gcloud pubsub topics create "$TOPIC" \
    --project="$PROJECT" \
    --message-storage-policy-allowed-regions="$REGION" \
    --labels=app=retailtwin,cost=free-tier
fi

if gcloud pubsub subscriptions describe "$SUBSCRIPTION" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Subscription already exists"
else
  echo "Creating subscription ${SUBSCRIPTION}"
  gcloud pubsub subscriptions create "$SUBSCRIPTION" \
    --project="$PROJECT" \
    --topic="$TOPIC" \
    --ack-deadline=60 \
    --enable-message-ordering \
    --expiration-period=never \
    --message-retention-duration=7d \
    --labels=app=retailtwin,component=store-events \
    --quiet
fi

if bq --project_id="$PROJECT" show --dataset "${PROJECT}:${DATASET}" >/dev/null 2>&1; then
  echo "Dataset already exists"
else
  echo "Creating dataset ${DATASET}"
  bq --project_id="$PROJECT" --location="$REGION" mk \
    --dataset \
    --description="RetailTwin analytical history. On-demand only. No reservation." \
    --label=app:retailtwin \
    --label=cost:free-tier \
    "${PROJECT}:${DATASET}"
fi

table_description() {
  case "$1" in
    sales_events) echo "sale.completed events. One row per event_id." ;;
    inventory_events) echo "inventory events. One row per event_id." ;;
    agent_actions) echo "agent events. One row per event_id." ;;
    *) die "Unknown table ${1}." ;;
  esac
}

for table in sales_events inventory_events agent_actions; do
  if bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.${table}" >/dev/null 2>&1; then
    echo "Table already exists: ${table}"
    continue
  fi
  echo "Creating table ${table}"
  bq --project_id="$PROJECT" --location="$REGION" mk \
    --table \
    --description="$(table_description "$table")" \
    --schema="$SCHEMA" \
    --time_partitioning_field=occurred_at \
    --time_partitioning_type=DAY \
    --clustering_fields=store_id,sku \
    --label=app:retailtwin \
    "${PROJECT}:${DATASET}.${table}"
done

echo
echo "Checking the resources"
"${ROOT}/infrastructure/gcp/verify-store-events.sh"
