#!/usr/bin/env bash
# Check the day-0 Google Cloud foundation. Read-only.
# Exit 0: foundation and budget match.
# Exit 2: foundation matches and the budget alert is missing.
# Exit 1: something else does not match.

set -euo pipefail

CANONICAL_PROJECT="retailtwin-ai-511002"
PROJECT="${GCP_PROJECT_ID:-$CANONICAL_PROJECT}"
REGION="${GCP_REGION:-us-central1}"
DATABASE="${FIRESTORE_DATABASE:-(default)}"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
BUCKET="${GCS_BUCKET:-retailtwin-ai-511002-assets}"
REPO="${ARTIFACT_REGISTRY_REPO:-retailtwin}"
BUDGET_NAME="retailtwin-dev-guard"
API_SA="retailtwin-api@${PROJECT}.iam.gserviceaccount.com"
AGENT_SA="retailtwin-agent@${PROJECT}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ "$PROJECT" != "$CANONICAL_PROJECT" ]]; then
  echo "FAIL  Refusing project ${PROJECT}. Verification applies only to ${CANONICAL_PROJECT}." >&2
  exit 1
fi

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$PROJECT"

failures=0
budget_blocked=0

pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*" >&2; failures=$((failures + 1)); }
note() { echo "NOTE  $*"; }

require_enabled() {
  local api="$1"
  if gcloud services list --enabled --project="$PROJECT" --filter="config.name=${api}" --format='value(config.name)' | grep -qx "$api"; then
    pass "API ${api}"
  else
    fail "API ${api} is not enabled"
  fi
}

require_disabled() {
  local api="$1"
  if gcloud services list --enabled --project="$PROJECT" --filter="config.name=${api}" --format='value(config.name)' | grep -qx "$api"; then
    fail "API ${api} is enabled. This foundation does not use it."
  else
    pass "API ${api} stays off"
  fi
}

yaml_has() {
  local yaml="$1"
  local expected="$2"
  printf '%s\n' "$yaml" | grep -qix "$expected"
}

echo "Verifying ${PROJECT} in ${REGION}"

billing_enabled="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' || true)"
if [[ "$billing_enabled" == "True" ]]; then
  pass "Billing is enabled"
else
  fail "Billing is not enabled (got '${billing_enabled}')"
fi

require_enabled aiplatform.googleapis.com
require_enabled run.googleapis.com
require_enabled cloudbuild.googleapis.com
require_enabled artifactregistry.googleapis.com
require_enabled firestore.googleapis.com
require_enabled bigquery.googleapis.com
require_enabled pubsub.googleapis.com
require_enabled storage.googleapis.com
require_enabled secretmanager.googleapis.com
require_enabled logging.googleapis.com

require_disabled compute.googleapis.com
require_disabled container.googleapis.com
require_disabled sqladmin.googleapis.com
require_disabled redis.googleapis.com
require_disabled spanner.googleapis.com

policy_file="$(mktemp)"
gcloud projects get-iam-policy "$PROJECT" --format=json >"$policy_file"
while IFS="$(printf '\t')" read -r status message; do
  [[ -z "${status:-}" ]] && continue
  if [[ "$status" == "PASS" ]]; then
    pass "$message"
  else
    fail "$message"
  fi
done < <(python3 - "$policy_file" "$API_SA" "$AGENT_SA" <<'PY'
import json, sys
path, api_sa, agent_sa = sys.argv[1:]
policy = json.load(open(path))
roles = {}
for binding in policy.get("bindings", []):
    for member in binding.get("members", []):
        roles.setdefault(member, set()).add(binding.get("role"))

def members():
    for binding in policy.get("bindings", []):
        for member in binding.get("members", []):
            yield member

public = [m for m in members() if m in ("allUsers", "allAuthenticatedUsers")]
api = roles.get("serviceAccount:" + api_sa, set())
agent = roles.get("serviceAccount:" + agent_sa, set())
checks = []

def need(ok, message):
    checks.append(("PASS" if ok else "FAIL", message))

need(public == [], "Project IAM has no allUsers or allAuthenticatedUsers")
need(bool(api), "retailtwin-api has project roles")
need("roles/datastore.user" in api, "retailtwin-api has roles/datastore.user")
need("roles/logging.logWriter" in api, "retailtwin-api has roles/logging.logWriter")
need("roles/aiplatform.user" not in api, "retailtwin-api does not have roles/aiplatform.user")
need("roles/editor" not in api and "roles/owner" not in api, "retailtwin-api is not editor or owner")
need(bool(agent), "retailtwin-agent has project roles")
need("roles/aiplatform.user" in agent, "retailtwin-agent has roles/aiplatform.user")
for forbidden in (
    "roles/datastore.user",
    "roles/datastore.owner",
    "roles/editor",
    "roles/owner",
    "roles/viewer",
    "roles/pubsub.publisher",
    "roles/pubsub.admin",
):
    need(forbidden not in agent, "retailtwin-agent does not have " + forbidden)
for status, message in checks:
    sys.stdout.write("%s\t%s\n" % (status, message))
PY
)
rm -f "$policy_file"

for sa in "$API_SA" "$AGENT_SA"; do
  if gcloud iam service-accounts describe "$sa" --project="$PROJECT" >/dev/null 2>&1; then
    pass "Service account ${sa} exists"
  else
    fail "Service account ${sa} is missing"
    continue
  fi
  key_count="$(gcloud iam service-accounts keys list --iam-account="$sa" --managed-by=user --format='value(name)' | wc -l | tr -d ' ')"
  if [[ "$key_count" == "0" ]]; then
    pass "No user-managed key for ${sa}"
  else
    fail "User-managed key exists for ${sa}"
  fi
done

db_file="$(mktemp)"
if gcloud firestore databases list --project="$PROJECT" --format=json >"$db_file" 2>/dev/null; then
  db_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$db_file")"
  if [[ "$db_count" == "1" ]]; then
    pass "One Firestore database"
  else
    fail "Expected one Firestore database, found ${db_count}. The free tier covers one."
  fi
else
  fail "Firestore databases list did not respond"
fi
rm -f "$db_file"

if db_yaml="$(gcloud firestore databases describe --project="$PROJECT" --database="$DATABASE" --format=yaml 2>/dev/null)"; then
  yaml_has "$db_yaml" "locationId: us-central1" && pass "Firestore location is us-central1" || fail "Firestore location is not us-central1"
  yaml_has "$db_yaml" "type: FIRESTORE_NATIVE" && pass "Firestore type is native" || fail "Firestore type is not native"
  yaml_has "$db_yaml" "databaseEdition: STANDARD" && pass "Firestore edition is standard" || fail "Firestore edition is not standard"
  yaml_has "$db_yaml" "freeTier: true" && pass "Firestore free tier is on this database" || fail "Firestore free tier is not on this database"
  yaml_has "$db_yaml" "pointInTimeRecoveryEnablement: POINT_IN_TIME_RECOVERY_DISABLED" && pass "Firestore PITR is off" || fail "Firestore PITR is on. PITR is billed."
  yaml_has "$db_yaml" "deleteProtectionState: DELETE_PROTECTION_ENABLED" && pass "Firestore delete protection is on" || fail "Firestore delete protection is off"
else
  fail "Firestore database ${DATABASE} did not respond"
fi

if topic_yaml="$(gcloud pubsub topics describe "$TOPIC" --project="$PROJECT" --format=yaml 2>/dev/null)"; then
  regions="$(printf '%s\n' "$topic_yaml" | awk '/allowedPersistenceRegions:/{flag=1; next} flag && /^[^ ]/{flag=0} flag && $1=="-"{print $2}')"
  if [[ "$regions" == "us-central1" ]]; then
    pass "Pub/Sub ${TOPIC} stores messages only in us-central1"
  else
    fail "Pub/Sub ${TOPIC} storage regions are '${regions}'"
  fi
else
  fail "Pub/Sub topic ${TOPIC} did not respond"
fi

topic_policy="$(mktemp)"
# No Google-managed publisher is required. The only allowed member is the API runtime account.
if gcloud pubsub topics get-iam-policy "$TOPIC" --project="$PROJECT" --format=json >"$topic_policy" 2>/dev/null; then
  publisher_result="$(python3 -c '
import json, sys
policy = json.load(open(sys.argv[1]))
api = sys.argv[2]
allowed = {"serviceAccount:" + api}
actual = set()
for binding in policy.get("bindings", []):
    if binding.get("role") == "roles/pubsub.publisher":
        actual.update(binding.get("members", []))
if actual == allowed:
    print("PASS")
else:
    print("FAIL\t" + ", ".join(sorted(actual)))
' "$topic_policy" "$API_SA")"
  if [[ "$publisher_result" == "PASS" ]]; then
    pass "Topic ${TOPIC} publishers are exactly ${API_SA}"
  else
    fail "Topic ${TOPIC} publishers are not exactly ${API_SA} (${publisher_result})"
  fi
else
  fail "Could not read IAM for topic ${TOPIC}"
fi
rm -f "$topic_policy"

dataset_file="$(mktemp)"
if bq --project_id="$PROJECT" show --format=prettyjson "${PROJECT}:${DATASET}" >"$dataset_file" 2>/dev/null; then
  location="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("location",""))' "$dataset_file")"
  location_lc="$(printf '%s' "$location" | tr '[:upper:]' '[:lower:]')"
  if [[ "$location_lc" == "us-central1" ]]; then
    pass "BigQuery dataset ${DATASET} is in us-central1"
  else
    fail "BigQuery dataset location is '${location}'"
  fi
else
  fail "BigQuery dataset ${DATASET} did not respond"
fi
rm -f "$dataset_file"

if bucket_yaml="$(gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT" --format=yaml 2>/dev/null)"; then
  yaml_has "$bucket_yaml" "location: US-CENTRAL1" && pass "Bucket is in us-central1" || fail "Bucket is not in us-central1"
  yaml_has "$bucket_yaml" "default_storage_class: STANDARD" && pass "Bucket storage class is STANDARD" || fail "Bucket storage class is not STANDARD"
  yaml_has "$bucket_yaml" "public_access_prevention: enforced" && pass "Bucket public access prevention is enforced" || fail "Bucket is not private"
  yaml_has "$bucket_yaml" "uniform_bucket_level_access: true" && pass "Bucket uses uniform access" || fail "Bucket does not use uniform access"
  printf '%s\n' "$bucket_yaml" | grep -q "retentionDurationSeconds: '0'" && pass "Bucket soft delete is off" || fail "Bucket soft delete would keep deleted objects billable"
else
  fail "Bucket gs://${BUCKET} did not respond"
fi

repo_format="$(gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT" --format='value(format)' 2>/dev/null || true)"
if [[ "$repo_format" == "DOCKER" ]]; then
  pass "Artifact Registry ${REPO} is a Docker repository in ${REGION}"
else
  fail "Artifact Registry ${REPO} is missing or not a Docker repository in ${REGION} (got '${repo_format}')"
fi

secret_count="$(gcloud secrets list --project="$PROJECT" --format='value(name)' | wc -l | tr -d ' ')"
if [[ "$secret_count" == "0" ]]; then
  pass "Secret Manager has no secrets"
elif [[ "$secret_count" -le 6 ]]; then
  note "Secret Manager has ${secret_count} secret(s), inside the free 6 versions"
else
  fail "Secret Manager has ${secret_count} secrets, past the free 6 versions"
fi

run_count="$(gcloud run services list --project="$PROJECT" --format='value(metadata.name)' | wc -l | tr -d ' ')"
if [[ "$run_count" == "0" ]]; then
  pass "No Cloud Run service is deployed"
else
  fail "Cloud Run already has ${run_count} service(s). Issue #9 deploys the scale-to-zero service."
fi

tracked="$(git -C "$ROOT" ls-files | grep -E '(^|/)\.env$|service-account.*\.json$|credentials.*\.json$|\.pem$|\.key$' || true)"
if [[ -z "$tracked" ]]; then
  pass "Git tracks no credential file"
else
  fail "Git tracks credential files:"
  printf '%s\n' "$tracked" >&2
fi

account="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' || true)"
budget_id="${account#billingAccounts/}"
errfile="$(mktemp)"
if [[ -z "$budget_id" ]]; then
  fail "Could not read the linked billing account"
elif list_output="$(gcloud billing budgets list --billing-account="$budget_id" --billing-project="$PROJECT" --format='value(displayName)' 2>"$errfile")"; then
  if printf '%s\n' "$list_output" | grep -qx "$BUDGET_NAME"; then
    pass "Budget ${BUDGET_NAME} exists"
  else
    budget_blocked=1
    note "Budget ${BUDGET_NAME} is missing. A billing administrator still needs to create the 25000 VND alert."
  fi
else
  if grep -q 'does not have permission' "$errfile"; then
    budget_blocked=1
    note "This account cannot manage billing account ${budget_id}. The 25000 VND alert is not confirmed from here."
  else
    fail "Budget list failed"
    cat "$errfile" >&2
  fi
fi
rm -f "$errfile"

echo
if [[ "$failures" -gt 0 ]]; then
  echo "${failures} check(s) failed"
  exit 1
fi
if [[ "$budget_blocked" -ne 0 ]]; then
  echo "Foundation matches. Budget alert is still blocked."
  exit 2
fi
echo "Foundation matches, including the budget alert."
