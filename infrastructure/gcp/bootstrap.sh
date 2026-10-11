#!/usr/bin/env bash
# Apply the day-0 Google Cloud foundation for issue #5.
# Idempotent. Creates no keys, documents, subscriptions, secrets, or model calls.
# See infrastructure/gcp/README.md and docs/adr/0004-keep-the-cloud-foundation-on-free-tier.md.

set -euo pipefail

CANONICAL_PROJECT="retailtwin-ai-511002"
PROJECT="${GCP_PROJECT_ID:-$CANONICAL_PROJECT}"
REGION="${GCP_REGION:-us-central1}"
DATABASE="${FIRESTORE_DATABASE:-(default)}"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
BUCKET="${GCS_BUCKET:-retailtwin-ai-511002-assets}"
REPO="${ARTIFACT_REGISTRY_REPO:-retailtwin}"
API_SA_ID="retailtwin-api"
AGENT_SA_ID="retailtwin-agent"
BUDGET_NAME="retailtwin-dev-guard"

API_SA="${API_SA_ID}@${PROJECT}.iam.gserviceaccount.com"
AGENT_SA="${AGENT_SA_ID}@${PROJECT}.iam.gserviceaccount.com"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIRED_APIS_FILE="${SCRIPT_DIR}/required-apis.txt"

die() {
  echo "error: $*" >&2
  exit 1
}

if [[ ! -r "$REQUIRED_APIS_FILE" ]]; then
  die "Required API manifest is unreadable: ${REQUIRED_APIS_FILE}."
fi
mapfile -t REQUIRED_APIS < <(grep -Ev '^[[:space:]]*(#|$)' "$REQUIRED_APIS_FILE")
if [[ "${#REQUIRED_APIS[@]}" -eq 0 ]]; then
  die "Required API manifest is empty: ${REQUIRED_APIS_FILE}."
fi

if [[ "${CONFIRM_GCP_BOOTSTRAP:-}" != "yes" ]]; then
  die "Set CONFIRM_GCP_BOOTSTRAP=yes to apply the foundation to ${PROJECT}."
fi

if [[ "$PROJECT" != "$CANONICAL_PROJECT" ]]; then
  die "Refusing project ${PROJECT}. This foundation applies only to ${CANONICAL_PROJECT}."
fi

if [[ "$REGION" != "us-central1" ]]; then
  die "Refusing region ${REGION}. Cloud Storage free tier and this foundation use us-central1."
fi

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_BILLING_QUOTA_PROJECT="$PROJECT"

echo "Project:  ${PROJECT}"
echo "Region:   ${REGION}"
echo "Account:  $(gcloud config get-value account 2>/dev/null || true)"
echo
echo "This will not create service-account keys, Firestore documents, Pub/Sub"
echo "subscriptions, Secret Manager versions, Cloud Run services, or Vertex calls."
echo

billing_enabled="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)')" \
  || die "Cannot read billing for ${PROJECT}."
if [[ "$billing_enabled" != "True" ]]; then
  die "Billing is disabled on ${PROJECT}. Free tier still requires a linked billing account. retailtwin-ai is the project without billing."
fi

echo "Enabling ${#REQUIRED_APIS[@]} required APIs"
gcloud services enable --project="$PROJECT" "${REQUIRED_APIS[@]}"

# IAM changes below name retailtwin-api and retailtwin-agent only.
# Do not remove roles from other service accounts in this project.
ensure_service_account() {
  local sa_id="$1"
  local display="$2"
  local description="$3"
  local email="${sa_id}@${PROJECT}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "$email" --project="$PROJECT" >/dev/null 2>&1; then
    echo "Service account exists: ${email}"
  else
    echo "Creating service account: ${email}"
    gcloud iam service-accounts create "$sa_id" \
      --project="$PROJECT" \
      --display-name="$display" \
      --description="$description"
  fi
}

bind_project_role() {
  local member="$1"
  local role="$2"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="$member" \
    --role="$role" \
    --quiet >/dev/null
}

ensure_service_account "$API_SA_ID" \
  "RetailTwin API runtime" \
  "Writes Firestore and publishes store events. No key is created."
ensure_service_account "$AGENT_SA_ID" \
  "RetailTwin Vertex caller" \
  "Calls Vertex AI only. Must not write Firestore. No key is created."

echo "Binding runtime roles"
bind_project_role "serviceAccount:${API_SA}" "roles/datastore.user"
bind_project_role "serviceAccount:${API_SA}" "roles/logging.logWriter"
bind_project_role "serviceAccount:${AGENT_SA}" "roles/aiplatform.user"

echo "Firestore database ${DATABASE}"
if gcloud firestore databases describe --project="$PROJECT" --database="$DATABASE" >/dev/null 2>&1; then
  echo "Firestore database already exists"
else
  # Standard edition gets the one free database. PITR and backups are billed.
  gcloud firestore databases create \
    --project="$PROJECT" \
    --database="$DATABASE" \
    --location="$REGION" \
    --edition=standard \
    --type=firestore-native \
    --delete-protection
fi

echo "Pub/Sub topic ${TOPIC}"
if gcloud pubsub topics describe "$TOPIC" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Topic already exists"
else
  gcloud pubsub topics create "$TOPIC" \
    --project="$PROJECT" \
    --message-storage-policy-allowed-regions="$REGION" \
    --labels=app=retailtwin,cost=free-tier
fi
topic_updated=0
for _try in 1 2 3 4 5; do
  if gcloud pubsub topics update "$TOPIC" \
      --project="$PROJECT" \
      --message-storage-policy-allowed-regions="$REGION" \
      >/dev/null; then
    topic_updated=1
    break
  fi
  echo "Topic update raced (attempt ${_try}). Waiting."
  sleep 5
done
if [[ "$topic_updated" -ne 1 ]]; then
  die "Could not limit ${TOPIC} message storage to ${REGION}."
fi
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --project="$PROJECT" \
  --member="serviceAccount:${API_SA}" \
  --role="roles/pubsub.publisher" \
  --quiet >/dev/null

echo "BigQuery dataset ${DATASET}"
if bq --project_id="$PROJECT" show --dataset "${PROJECT}:${DATASET}" >/dev/null 2>&1; then
  echo "Dataset already exists"
else
  bq --project_id="$PROJECT" --location="$REGION" mk \
    --dataset \
    --description="RetailTwin analytical history. On-demand only. Empty day-0 dataset stays inside the 10 GiB free tier." \
    --label=app:retailtwin \
    --label=cost:free-tier \
    "${PROJECT}:${DATASET}"
fi

echo "Cloud Storage bucket ${BUCKET}"
if gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Bucket already exists"
else
  # This gcloud build has no --labels flag on bucket create.
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="$PROJECT" \
    --location="$REGION" \
    --default-storage-class=STANDARD \
    --uniform-bucket-level-access \
    --public-access-prevention \
    --soft-delete-duration=0s
fi

echo "Artifact Registry repository ${REPO}"
if gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Repository already exists"
else
  gcloud artifacts repositories create "$REPO" \
    --project="$PROJECT" \
    --repository-format=docker \
    --location="$REGION" \
    --description="RetailTwin images. Keep this repository under the 0.5 GB free tier." \
    --labels=app=retailtwin,cost=free-tier
fi

budget_blocked=0
configure_budget() {
  local account id errfile list_output
  account="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)')"
  id="${account#billingAccounts/}"
  errfile="$(mktemp)"
  if list_output="$(gcloud billing budgets list \
      --billing-account="$id" \
      --billing-project="$PROJECT" \
      --format='value(displayName)' 2>"$errfile")"; then
    if printf '%s\n' "$list_output" | grep -qx "$BUDGET_NAME"; then
      echo "Budget ${BUDGET_NAME} already exists"
      rm -f "$errfile"
      return 0
    fi
    echo "Creating budget ${BUDGET_NAME} for 25000 VND"
    if ! gcloud billing budgets create \
        --billing-account="$id" \
        --billing-project="$PROJECT" \
        --display-name="$BUDGET_NAME" \
        --budget-amount=25000VND \
        --calendar-period=month \
        --filter-projects="projects/${PROJECT}" \
        --threshold-rule=percent=0.5 \
        --threshold-rule=percent=0.9 \
        --threshold-rule=percent=1.0 \
        2>"$errfile"; then
      echo "Could not create the 25000 VND budget." >&2
      cat "$errfile" >&2
      rm -f "$errfile"
      return 1
    fi
    rm -f "$errfile"
    return 0
  fi
  echo "BLOCKED: this account cannot manage billing account ${id}." >&2
  echo "A billing administrator creates the 25000 VND alert with:" >&2
  cat <<EOF >&2

gcloud billing budgets create \\
  --billing-account=${id} \\
  --billing-project=${PROJECT} \\
  --display-name=${BUDGET_NAME} \\
  --budget-amount=25000VND \\
  --calendar-period=month \\
  --filter-projects=projects/${PROJECT} \\
  --threshold-rule=percent=0.5 \\
  --threshold-rule=percent=0.9 \\
  --threshold-rule=percent=1.0

EOF
  cat "$errfile" >&2
  rm -f "$errfile"
  return 1
}

echo "Budget alert"
if ! configure_budget; then
  budget_blocked=1
fi

echo
echo "Foundation applied on ${PROJECT} in ${REGION}."
echo "API identity:   ${API_SA}"
echo "Agent identity: ${AGENT_SA}"
if [[ "$budget_blocked" -ne 0 ]]; then
  echo "Budget alert is not configured."
  exit 2
fi
echo "Budget alert ${BUDGET_NAME} is configured."
