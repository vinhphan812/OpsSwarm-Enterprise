#!/usr/bin/env bash
# Read-only check of the store-events subscription and BigQuery tables.
# Creates nothing. See infrastructure/gcp/store-events.md.

set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-retailtwin-ai-511002}"
REGION="${GCP_REGION:-us-central1}"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
SUBSCRIPTION="${STORE_EVENTS_SUBSCRIPTION:-store-events-analytics}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="${ROOT}/infrastructure/gcp/schemas/normalized-event.json"
FAILURES=0

if [[ "$PROJECT" != "retailtwin-ai-511002" || "$REGION" != "us-central1" ]]; then
  echo "FAIL  Refusing ${PROJECT} in ${REGION}" >&2
  exit 1
fi
if [[ "$TOPIC" != "store-events" || "$SUBSCRIPTION" != "store-events-analytics" || "$DATASET" != "retailtwin" ]]; then
  echo "FAIL  Refusing a renamed topic, subscription, or dataset" >&2
  exit 1
fi

pass() { echo "PASS  $*"; }
fail() {
  echo "FAIL  $*" >&2
  FAILURES=$((FAILURES + 1))
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

echo "Verifying store events on ${PROJECT}"

if ! gcloud pubsub topics describe "$TOPIC" --project="$PROJECT" --format=json >"${tmpdir}/topic.json" 2>"${tmpdir}/topic.err"; then
  fail "Pub/Sub topic ${TOPIC} did not respond"
  echo '{}' >"${tmpdir}/topic.json"
fi

if gcloud pubsub subscriptions describe "$SUBSCRIPTION" --project="$PROJECT" --format=json >"${tmpdir}/subscription.json" 2>"${tmpdir}/subscription.err"; then
  :
else
  fail "Subscription ${SUBSCRIPTION} did not respond"
  echo '{}' >"${tmpdir}/subscription.json"
fi

if bq --project_id="$PROJECT" show --format=prettyjson "${PROJECT}:${DATASET}" >"${tmpdir}/dataset.json" 2>"${tmpdir}/dataset.err"; then
  :
else
  fail "BigQuery dataset ${DATASET} did not respond"
  echo '{}' >"${tmpdir}/dataset.json"
fi

for table in sales_events inventory_events agent_actions; do
  if ! bq --project_id="$PROJECT" show --format=prettyjson "${PROJECT}:${DATASET}.${table}" >"${tmpdir}/${table}.json" 2>"${tmpdir}/${table}.err"; then
    fail "Table ${table} did not respond"
    echo '{}' >"${tmpdir}/${table}.json"
  fi
done

if python3 - "$SCHEMA" "$tmpdir" >"${tmpdir}/checks.tsv" 2>"${tmpdir}/check.err" <<'PY'
import json
import sys
from pathlib import Path

schema_path, tmp = sys.argv[1:]
root = Path(tmp)

def load(name):
    path = root / name
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text())

def emit(ok, message):
    sys.stdout.write("%s\t%s\n" % ("PASS" if ok else "FAIL", message))

aliases = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL"}

def norm_type(value):
    text = str(value or "")
    return aliases.get(text, text)

def columns(table):
    fields = ((table.get("schema") or {}).get("fields")) or []
    return {
        field.get("name"): (norm_type(field.get("type")), field.get("mode") or "NULLABLE")
        for field in fields
    }

expected_fields = json.loads(Path(schema_path).read_text())
expected = {
    field["name"]: (norm_type(field["type"]), field.get("mode") or "NULLABLE")
    for field in expected_fields
}

topic = load("topic.json")
regions = ((topic.get("messageStoragePolicy") or {}).get("allowedPersistenceRegions")) or []
emit(regions == ["us-central1"], "Pub/Sub store-events stores messages only in us-central1")

subscription = load("subscription.json")
topic_name = subscription.get("topic") or ""
emit(topic_name.endswith("/topics/store-events"), "Subscription store-events-analytics is attached to store-events")
emit(subscription.get("enableMessageOrdering") is True, "Subscription message ordering is on")
emit(int(subscription.get("ackDeadlineSeconds") or 0) == 60, "Subscription ack deadline is 60 seconds")
push = (subscription.get("pushConfig") or {}).get("pushEndpoint")
emit(not push, "Subscription has no push endpoint")
expiration = subscription.get("expirationPolicy")
never = expiration == {} or (isinstance(expiration, dict) and not expiration.get("ttl"))
emit(bool(subscription) and never, "Subscription does not expire")

dataset = load("dataset.json")
location = str(dataset.get("location") or "").lower()
emit(location == "us-central1", "BigQuery dataset retailtwin is in us-central1")

for name in ("sales_events", "inventory_events", "agent_actions"):
    table = load(name + ".json")
    emit(columns(table) == expected, "Table %s has the normalized event columns" % name)
    partitioning = table.get("timePartitioning") or {}
    partitioned = partitioning.get("type") == "DAY" and partitioning.get("field") == "occurred_at"
    emit(partitioned, "Table %s is partitioned by occurred_at day" % name)
    clustered = (table.get("clustering") or {}).get("fields") == ["store_id", "sku"]
    emit(clustered, "Table %s is clustered by store_id and sku" % name)
    require_filter = partitioning.get("requirePartitionFilter")
    emit(require_filter in (None, False, "false", "FALSE"), "Table %s does not require a partition filter" % name)
PY
then
  :
else
  fail "Resource check could not read the describe output"
  cat "${tmpdir}/check.err" >&2
  : >"${tmpdir}/checks.tsv"
fi

while IFS="$(printf '\t')" read -r status message; do
  [[ -z "${status:-}" ]] && continue
  if [[ "$status" == "PASS" ]]; then
    pass "$message"
  else
    fail "$message"
  fi
done <"${tmpdir}/checks.tsv"

if [[ "$FAILURES" -ne 0 ]]; then
  echo "${FAILURES} check(s) failed" >&2
  exit 1
fi
echo "Store events match"
