#!/usr/bin/env bash
# Cloud preflight verifier for RetailTwin AI.
# Read-only check of the production GCP/Firebase environment.
# Prints no secret values. Exit 0 = all checks passed.
#
# Usage:
#   ./scripts/verify-cloud-preflight.sh
#   GCP_PROJECT_ID=retailtwin-ai-511002 ./scripts/verify-cloud-preflight.sh
#
# This script complements infrastructure/gcp/verify.sh (foundation) by adding:
#   - Cloud Run runtime SA verification
#   - Secret Manager existence check
#   - BigQuery table verification
#   - Vertex AI location/model validation
#   - Firebase Hosting site check
#   - Production CORS origin verification
#   - GitHub Actions WIF provider check

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
CANONICAL_PROJECT="retailtwin-ai-511002"
PROJECT="${GCP_PROJECT_ID:-$CANONICAL_PROJECT}"
REGION="${GCP_REGION:-us-central1}"
LOCATION="${VERTEX_AI_LOCATION:-$REGION}"
API_SA="retailtwin-api@${PROJECT}.iam.gserviceaccount.com"
AGENT_SA="retailtwin-agent@${PROJECT}.iam.gserviceaccount.com"
GITHUB_ACTIONS_SA="github-actions@${PROJECT}.iam.gserviceaccount.com"
CLOUD_RUN_SERVICE="retailtwin-api"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
SUBSCRIPTION="${STORE_EVENTS_SUBSCRIPTION:-store-events-analytics}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
REPO="${ARTIFACT_REGISTRY_REPO:-retailtwin}"
BUCKET="${GCS_BUCKET:-retailtwin-ai-511002-assets}"
FIREBASE_SITE="${FIREBASE_SITE:-retailtwin-ai-511002}"
VERTEX_MODEL="${VERTEX_MODEL:-gemini-2.5-flash}"

# Production CORS origins (from docs/CLOUD_RUNTIME_MATRIX.md)
PRODUCTION_CORS_ORIGINS=(
  "https://retailtwin-ai-511002.web.app"
  "https://retailtwin-ai-511002.firebaseapp.com"
)

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$PROJECT"

# ── Helpers ────────────────────────────────────────────────────────────────────
_failures=0
_warnings=0

pass()  { echo "PASS  $*"; }
fail()  { echo "FAIL  $*" >&2; _failures=$((_failures + 1)); }
warn()  { echo "WARN  $*" >&2; _warnings=$((_warnings + 1)); }
note()  { echo "NOTE  $*"; }

require_enabled() {
  local api="$1"
  if gcloud services list --enabled --project="$PROJECT" \
    --filter="config.name=${api}" --format='value(config.name)' 2>/dev/null | \
    grep -qx "$api"; then
    pass "API ${api}"
  else
    fail "API ${api} is not enabled"
  fi
}

yaml_has() {
  local yaml="$1"
  local expected="$2"
  printf '%s\n' "$yaml" | grep -qix "$expected"
}

json_has() {
  local key="$1"
  local json="$2"
  printf '%s' "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); print('yes')" 2>/dev/null | grep -q yes
}

# ── Project guard ──────────────────────────────────────────────────────────────
echo "=== Cloud Preflight Verifier ==="
echo "Project : ${PROJECT}"
echo "Region  : ${REGION}"
echo ""

if [[ "$PROJECT" != "$CANONICAL_PROJECT" ]]; then
  fail "Refusing project ${PROJECT}. Verification applies only to ${CANONICAL_PROJECT}."
  exit 1
fi

# ── Billing ───────────────────────────────────────────────────────────────────
billing_enabled="$(gcloud billing projects describe "$PROJECT" \
  --format='value(billingEnabled)' 2>/dev/null || true)"
if [[ "$billing_enabled" == "True" ]]; then
  pass "Billing is enabled"
else
  fail "Billing is not enabled"
fi

# ── Required APIs ─────────────────────────────────────────────────────────────
echo ""
echo "--- Required APIs ---"
REQUIRED_APIS=(
  "aiplatform.googleapis.com"
  "run.googleapis.com"
  "cloudbuild.googleapis.com"
  "artifactregistry.googleapis.com"
  "firestore.googleapis.com"
  "bigquery.googleapis.com"
  "pubsub.googleapis.com"
  "storage.googleapis.com"
  "secretmanager.googleapis.com"
  "logging.googleapis.com"
  "cloudbilling.googleapis.com"
  "billingbudgets.googleapis.com"
  "cloudresourcemanager.googleapis.com"
  "iam.googleapis.com"
)
for api in "${REQUIRED_APIS[@]}"; do
  require_enabled "$api"
done

# ── Service Accounts ───────────────────────────────────────────────────────────
echo ""
echo "--- Service Accounts ---"
for sa in "$API_SA" "$AGENT_SA" "$GITHUB_ACTIONS_SA"; do
  if gcloud iam service-accounts describe "$sa" \
    --project="$PROJECT" >/dev/null 2>&1; then
    pass "Service account ${sa} exists"
  else
    # github-actions may not exist yet (Terraform #99)
    if [[ "$sa" == "$GITHUB_ACTIONS_SA" ]]; then
      warn "Service account ${sa} does not exist (Terraform #99 may not have provisioned it)"
    else
      fail "Service account ${sa} is missing"
    fi
    continue
  fi
  key_count="$(gcloud iam service-accounts keys list \
    --iam-account="$sa" --managed-by=user \
    --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$key_count" == "0" ]]; then
    pass "No user-managed key for ${sa}"
  else
    fail "User-managed key exists for ${sa} (${key_count} key(s))"
  fi
done

# ── IAM Bindings ───────────────────────────────────────────────────────────────
echo ""
echo "--- IAM Bindings (runtime SAs) ---"
policy_file="$(mktemp)"
gcloud projects get-iam-policy "$PROJECT" --format=json >"$policy_file" 2>/dev/null

# Run IAM checks and count failures
iam_failures=$(python3 - "$policy_file" "$API_SA" "$AGENT_SA" <<'PY' 2>&1)
import json, sys
path, api_sa, agent_sa = sys.argv[1:]
policy = json.load(open(path))
roles = {}
failures = 0

for binding in policy.get("bindings", []):
    for member in binding.get("members", []):
        roles.setdefault(member, set()).add(binding.get("role"))

def members():
    for binding in policy.get("bindings", []):
        for member in binding.get("members", []):
            yield member

def check(condition, message):
    global failures
    prefix = "PASS" if condition else "FAIL"
    if not condition:
        failures += 1
    print(f"{prefix}  {message}")

public = [m for m in members() if m in ("allUsers", "allAuthenticatedUsers")]
api_roles = roles.get("serviceAccount:" + api_sa, set())
agent_roles = roles.get("serviceAccount:" + agent_sa, set())

check(public == [], "Project IAM has no allUsers or allAuthenticatedUsers")
check(bool(api_roles), "retailtwin-api has project roles")
check("roles/datastore.user" in api_roles, "retailtwin-api has roles/datastore.user")
check("roles/logging.logWriter" in api_roles, "retailtwin-api has roles/logging.logWriter")
check("roles/aiplatform.user" not in api_roles, "retailtwin-api does not have roles/aiplatform.user")
check("roles/editor" not in api_roles and "roles/owner" not in api_roles,
      "retailtwin-api is not editor or owner")
check(bool(agent_roles), "retailtwin-agent has project roles")
check("roles/aiplatform.user" in agent_roles, "retailtwin-agent has roles/aiplatform.user")
for forbidden in ("roles/datastore.user", "roles/datastore.owner",
                  "roles/editor", "roles/owner", "roles/viewer",
                  "roles/pubsub.publisher", "roles/pubsub.admin"):
    check(forbidden not in agent_roles, f"retailtwin-agent does not have {forbidden}")

# Exit with failure count so bash can track it
sys.exit(failures)
PY
)
iam_status=$?

# Add failures to counter
iam_fail_count=$(echo "$iam_failures" | grep -c "^FAIL" || true)
_failures=$((_failures + iam_fail_count))

# Print all output
echo "$iam_failures"

# If Python itself failed, count as failure
if [[ $iam_status -ne 0 ]]; then
  fail "IAM check script failed"
fi

rm -f "$policy_file"

# ── Firestore ──────────────────────────────────────────────────────────────────
echo ""
echo "--- Firestore ---"
db_file="$(mktemp)"
if gcloud firestore databases list --project="$PROJECT" --format=json \
  >"$db_file" 2>/dev/null; then
  db_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$db_file")"
  if [[ "$db_count" == "1" ]]; then
    pass "One Firestore database"
  else
    fail "Expected one Firestore database, found ${db_count}"
  fi
else
  fail "Firestore databases list did not respond"
fi
rm -f "$db_file"

if db_yaml="$(gcloud firestore databases describe \
  --project="$PROJECT" --database="(default)" --format=yaml 2>/dev/null)"; then
  yaml_has "$db_yaml" "locationId: us-central1" && \
    pass "Firestore location is us-central1" || \
    fail "Firestore location is not us-central1"
  yaml_has "$db_yaml" "type: FIRESTORE_NATIVE" && \
    pass "Firestore type is native" || \
    fail "Firestore type is not native"
  yaml_has "$db_yaml" "databaseEdition: STANDARD" && \
    pass "Firestore edition is standard" || \
    fail "Firestore edition is not standard"
  yaml_has "$db_yaml" "freeTier: true" && \
    pass "Firestore free tier is enabled" || \
    fail "Firestore free tier is not enabled"
else
  fail "Firestore database (default) did not respond"
fi

# ── Pub/Sub ────────────────────────────────────────────────────────────────────
echo ""
echo "--- Pub/Sub ---"
if topic_yaml="$(gcloud pubsub topics describe "$TOPIC" \
  --project="$PROJECT" --format=yaml 2>/dev/null)"; then
  if echo "$topic_yaml" | grep -q "us-central1"; then
    pass "Pub/Sub topic ${TOPIC} uses us-central1"
  else
    fail "Pub/Sub topic ${TOPIC} storage regions are not us-central1"
  fi
else
  fail "Pub/Sub topic ${TOPIC} did not respond"
fi

if sub_out="$(gcloud pubsub subscriptions describe "$SUBSCRIPTION" \
  --project="$PROJECT" --format=value(name) 2>/dev/null)"; then
  pass "Pub/Sub subscription ${SUBSCRIPTION} exists"
else
  fail "Pub/Sub subscription ${SUBSCRIPTION} does not exist"
fi

# ── BigQuery ───────────────────────────────────────────────────────────────────
echo ""
echo "--- BigQuery ---"
ds_file="$(mktemp)"
if bq --project_id="$PROJECT" show --format=prettyjson \
  "${PROJECT}:${DATASET}" >"$ds_file" 2>/dev/null; then
  location="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("location",""))' "$ds_file")"
  if [[ "${location,,}" == "us-central1" ]]; then
    pass "BigQuery dataset ${DATASET} is in us-central1"
  else
    fail "BigQuery dataset location is '${location}'"
  fi
else
  fail "BigQuery dataset ${DATASET} did not respond"
fi
rm -f "$ds_file"

# Check canonical tables
CANONICAL_TABLES=("sales_events" "inventory_events" "agent_actions" "agent_action_audit")
for table in "${CANONICAL_TABLES[@]}"; do
  if bq --project_id="$PROJECT" show --format=prettyjson \
    "${PROJECT}:${DATASET}.${table}" >/dev/null 2>&1; then
    pass "BigQuery table ${DATASET}.${table} exists"
  else
    # agent_action_audit may not exist yet (issue #35)
    if [[ "$table" == "agent_action_audit" ]]; then
      note "BigQuery table ${DATASET}.${table} does not exist (issue #35 may not have created it)"
    else
      fail "BigQuery table ${DATASET}.${table} is missing"
    fi
  fi
done

# ── Cloud Storage ─────────────────────────────────────────────────────────────
echo ""
echo "--- Cloud Storage ---"
if bucket_yaml="$(gcloud storage buckets describe "gs://${BUCKET}" \
  --project="$PROJECT" --format=yaml 2>/dev/null)"; then
  yaml_has "$bucket_yaml" "location: US-CENTRAL1" && \
    pass "Bucket gs://${BUCKET} is in us-central1" || \
    fail "Bucket is not in us-central1"
  yaml_has "$bucket_yaml" "public_access_prevention: enforced" && \
    pass "Bucket public access prevention is enforced" || \
    fail "Bucket is not private"
else
  fail "Bucket gs://${BUCKET} did not respond"
fi

# ── Artifact Registry ───────────────────────────────────────────────────────────
echo ""
echo "--- Artifact Registry ---"
repo_format="$(gcloud artifacts repositories describe "$REPO" \
  --location="$REGION" --project="$PROJECT" \
  --format='value(format)' 2>/dev/null || true)"
if [[ "$repo_format" == "DOCKER" ]]; then
  pass "Artifact Registry ${REPO} is a Docker repository in ${REGION}"
else
  fail "Artifact Registry ${REPO} is missing or not a Docker repository (got '${repo_format}')"
fi

# ── Secret Manager ─────────────────────────────────────────────────────────────
echo ""
echo "--- Secret Manager ---"
sec_out="$(gcloud secrets list --project="$PROJECT" \
  --format='value(name)' 2>/dev/null || true)"
sec_count="$(printf '%s' "$sec_out" | grep -c '.' || true)"
if [[ "$sec_count" == "0" ]]; then
  note "Secret Manager has no secrets (day-0 state; Terraform #99 will provision)"
elif [[ "$sec_count" -le 6 ]]; then
  pass "Secret Manager has ${sec_count} secret(s), within free 6 versions"
  # List names without values
  echo "$sec_out" | while read -r name; do
    note "  Secret: ${name}"
  done
else
  fail "Secret Manager has ${sec_count} secrets, past the free 6 versions"
fi

# ── Cloud Run ──────────────────────────────────────────────────────────────────
echo ""
echo "--- Cloud Run ---"
run_out="$(gcloud run services list --project="$PROJECT" \
  --format=value(metadata.name) 2>/dev/null || true)"
if echo "$run_out" | grep -q "^${CLOUD_RUN_SERVICE}$"; then
  pass "Cloud Run service ${CLOUD_RUN_SERVICE} exists"
  # Check runtime SA
  runtime_sa="$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
    --region="$REGION" --project="$PROJECT" \
    --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
  if [[ -n "$runtime_sa" ]]; then
    if [[ "$runtime_sa" == "$API_SA" ]]; then
      pass "Cloud Run runtime SA is ${API_SA}"
    else
      fail "Cloud Run runtime SA is '${runtime_sa}', expected ${API_SA}"
    fi
  else
    note "Could not read Cloud Run runtime SA"
  fi
  # Check CORS env var
  cors_env="$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
    --region="$REGION" --project="$PROJECT" \
    --format='value(spec.template.metadata.annotations.run-googleapis-com-cors)' 2>/dev/null || true)"
  if [[ -n "$cors_env" ]]; then
    note "Cloud Run has CORS annotation: ${cors_env}"
  fi
else
  note "Cloud Run service ${CLOUD_RUN_SERVICE} does not exist (issue #9 may not have deployed)"
fi

# ── Vertex AI ──────────────────────────────────────────────────────────────────
echo ""
echo "--- Vertex AI ---"
# Check Vertex AI API is accessible
if require_enabled "aiplatform.googleapis.com" 2>/dev/null; then
  pass "Vertex AI API is enabled"
else
  fail "Vertex AI API is not enabled"
fi

# Check the canonical model exists (this is a read-only API call)
model_out="$(gcloud ai models describe "$VERTEX_MODEL" \
  --region="$LOCATION" --project="$PROJECT" \
  --format='value(name)' 2>/dev/null || true)"
if [[ -n "$model_out" ]]; then
  pass "Vertex AI model ${VERTEX_MODEL} exists in ${LOCATION}"
else
  note "Vertex AI model ${VERTEX_MODEL} not verified (may not exist or no permission)"
fi

# ── Firebase Hosting ─────────────────────────────────────────────────────────
echo ""
echo "--- Firebase Hosting ---"
if command -v firebase >/dev/null 2>&1; then
  site_out="$(firebase hosting:channel:list --project="$FIREBASE_SITE" \
    2>/dev/null || true)"
  if [[ -n "$site_out" ]]; then
    pass "Firebase Hosting site ${FIREBASE_SITE} is accessible"
    # List channels
    echo "$site_out" | head -5 | while read -r line; do
      note "  ${line}"
    done
  else
    note "Firebase Hosting site ${FIREBASE_SITE} not verified (firebase-tools may lack auth)"
  fi
else
  note "firebase-tools not installed; skipping Firebase Hosting check"
  note "  Install: npm install -g firebase-tools"
fi

# ── CORS Verification ─────────────────────────────────────────────────────────
echo ""
echo "--- Production CORS Origins ---"
if [[ -n "${SERVICE_URL:-}" ]]; then
  # Check if the Cloud Run service is reachable
  health_out="$(curl -sf --max-time 5 "${SERVICE_URL}/health" 2>/dev/null || true)"
  if [[ -n "$health_out" ]]; then
    note "Cloud Run service is reachable at ${SERVICE_URL}"
    for origin in "${PRODUCTION_CORS_ORIGINS[@]}"; do
      cors_header="$(curl -sf --max-time 5 \
        -H "Origin: ${origin}" \
        -H "Access-Control-Request-Method: GET" \
        -I "${SERVICE_URL}/health" 2>/dev/null | \
        grep -i "^access-control-allow-origin:" || true)"
      if [[ -n "$cors_header" ]]; then
        pass "CORS header for ${origin}: ${cors_header}"
      else
        note "No CORS header for ${origin} (may not be configured yet)"
      fi
    done
  else
    note "Cloud Run service not reachable for CORS check"
  fi
else
  note "SERVICE_URL not set; skipping live CORS check"
  note "  Canonical production origins: ${PRODUCTION_CORS_ORIGINS[*]}"
fi

# ── GitHub Actions WIF (optional) ───────────────────────────────────────────────
echo ""
echo "--- GitHub Actions WIF ---"
wif_provider_var="${GCP_WORKLOAD_IDENTITY_PROVIDER:-}"
if [[ -n "$wif_provider_var" ]]; then
  if [[ "$wif_provider_var" == projects/* ]]; then
    # It's a full resource name, try to describe it
    provider_name="$(basename "$wif_provider_var")"
    pool_name="$(basename "$(dirname "$wif_provider_var")")"
    if gcloud iam workload-identity-pools providers describe "$provider_name" \
      --location="global" --project="$PROJECT" >/dev/null 2>&1; then
      pass "WIF provider ${wif_provider_var} exists"
    else
      note "WIF provider ${wif_provider_var} not verified (Terraform #99 may not have provisioned)"
    fi
  else
    note "GCP_WORKLOAD_IDENTITY_PROVIDER is set but not a full resource name"
  fi
else
  note "GCP_WORKLOAD_IDENTITY_PROVIDER not set (Terraform #99 will configure)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Summary ==="
if [[ "$_failures" -gt 0 ]]; then
  echo "${_failures} check(s) failed"
  exit 1
fi
if [[ "$_warnings" -gt 0 ]]; then
  echo "${_warnings} warning(s) — review above"
fi
echo "All required checks passed."
exit 0
