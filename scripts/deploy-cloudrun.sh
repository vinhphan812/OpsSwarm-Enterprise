#!/usr/bin/env bash
# Deploy the fixture API to Cloud Run.
#
# Matches ADR 0004: project retailtwin-ai-511002, region us-central1,
# Artifact Registry repository retailtwin, minimum instances 0, and the
# retailtwin-api runtime identity. The image contains the committed store
# fixture, so this script does not read Secret Manager.
#
# Usage, from the repository root, with Docker running:
#   scripts/deploy-cloudrun.sh
#   VERIFY=false scripts/deploy-cloudrun.sh
#
# Rollback:
#   gcloud run services update-traffic retailtwin-api \
#     --to-revisions=REVISION=100 --region=us-central1 --project=retailtwin-ai-511002

set -euo pipefail

PROJECT="${PROJECT:-retailtwin-ai-511002}"
REGION="${REGION:-us-central1}"
SERVICE="retailtwin-api"
REPOSITORY="retailtwin"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}"
IMAGE="${REGISTRY}/${SERVICE}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
VERIFY="${VERIFY:-true}"
API_SA="retailtwin-api@${PROJECT}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${PROJECT}" != "retailtwin-ai-511002" ]]; then
  echo "ERROR: PROJECT must be retailtwin-ai-511002, got '${PROJECT}'" >&2
  exit 1
fi

if [[ "${REGION}" != "us-central1" ]]; then
  echo "ERROR: REGION must be us-central1, got '${REGION}'" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker Desktop, then run this script again." >&2
  exit 1
fi

echo "=== RetailTwin API — Cloud Run Deployment ==="
echo "  Project : ${PROJECT}"
echo "  Region  : ${REGION}"
echo "  Service : ${SERVICE}"
echo "  Image   : ${IMAGE}:${TAG}"
echo "  Account : ${API_SA}"

echo ""
echo "[1/5] Checking Artifact Registry credentials..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo ""
echo "[2/5] Building ${IMAGE}:${TAG}"
docker build \
  --platform linux/amd64 \
  --tag "${IMAGE}:${TAG}" \
  --file "${ROOT}/Dockerfile" \
  "${ROOT}"

echo ""
echo "[3/5] Pushing image"
docker push "${IMAGE}:${TAG}"

echo ""
echo "[4/5] Deploying with minimum instances 0"
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}:${TAG}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --service-account "${API_SA}" \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60 \
  --concurrency 80 \
  --set-env-vars "^|^APP_ENV=production|LOG_LEVEL=INFO|CORS_ORIGINS=https://retailtwin-ai-511002.web.app,https://retailtwin-ai-511002.firebaseapp.com,http://localhost:5173,http://127.0.0.1:5173"

REVISION="$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format='value(status.latestCreatedRevisionName)')"
SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format='value(status.url)')"

echo ""
echo "Revision ${REVISION}"
echo "URL      ${SERVICE_URL}"

if [[ "${VERIFY}" != "true" ]]; then
  echo "[5/5] Skipped verification"
  exit 0
fi

echo ""
echo "[5/5] Verifying deployment..."
HEALTH_BODY="$(curl -sf "${SERVICE_URL}/health")"
printf '%s\n' "${HEALTH_BODY}" | grep -q '"app_env":"production"'
printf '%s\n' "${HEALTH_BODY}" | grep -q '"fixture_loaded":true'
READY_STATUS="$(curl -sf -o /dev/null -w '%{http_code}' "${SERVICE_URL}/ready")"
if [[ "${READY_STATUS}" != "200" ]]; then
  echo "ERROR: /ready returned ${READY_STATUS}" >&2
  exit 1
fi
STORE_STATUS="$(curl -sf -o /dev/null -w '%{http_code}' "${SERVICE_URL}/store")"
if [[ "${STORE_STATUS}" != "200" ]]; then
  echo "ERROR: /store returned ${STORE_STATUS}" >&2
  exit 1
fi

echo "Health, readiness, and /store passed."
echo "This revision is ${REVISION}. To roll back, send traffic to the previous revision:"
echo "  gcloud run services update-traffic ${SERVICE} \\"
echo "    --to-revisions=PREVIOUS_REVISION=100 --region=${REGION} --project=${PROJECT}"
