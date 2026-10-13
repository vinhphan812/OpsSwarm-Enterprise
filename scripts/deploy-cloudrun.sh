#!/usr/bin/env bash
# =============================================================================
# deploy-cloudrun.sh — Production Cloud Run deployment for retailtwin-api
# =============================================================================
# Prerequisites (must run once before first deploy):
#   1. gcloud auth configure-docker gcr.io
#   2. gcloud services enable run.googleapis.com  --project=retailtwin-ai-511002
#   3. WORKLOAD_IDENTITY_FEDERATION configured for CI (see GitHub Actions)
#
# Usage:
#   PROJECT=retailtwin-ai-511002 REGION=us-central1 ./deploy-cloudrun.sh [--verify]
#
# Production flags used:
#   --min-instances=1          Prevents cold-start latency for user-facing API
#   --max-instances=10         Caps cost; adjust per actual load testing
#   --port=8080               Cloud Run sets PORT; uvicorn reads it
#   --memory=512Mi             Verified sufficient for day-0 fixture load
#   --cpu=1                    Default; burst CPU OK with Cloud Run billing
#   --timeout=60               Matches gcloud --timeout (startup probe limit)
#   --concurrency=80           Max one request per instance at a time
#   --set-env-vars=APP_ENV=production
#
# Rollback:
#   gcloud run services update-traffic retailtwin-api \
#     --to-revisions=<previous-revision>=100 --region=us-central1
# =============================================================================

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
PROJECT="${PROJECT:-retailtwin-ai-511002}"
REGION="${REGION:-us-central1}"
SERVICE="retailtwin-api"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
VERIFY="${VERIFY:-true}"

# ── Guards ───────────────────────────────────────────────────────────────────
if [[ ! "${PROJECT}" =~ ^retailtwin-ai-511002$ ]]; then
  echo "ERROR: PROJECT must be 'retailtwin-ai-511002', got '${PROJECT}'" >&2
  exit 1
fi

if [[ ! "${REGION}" =~ ^us-central1$ ]]; then
  echo "ERROR: REGION must be 'us-central1', got '${REGION}'" >&2
  exit 1
fi

echo "=== RetailTwin API — Cloud Run Deployment ==="
echo "  Project  : ${PROJECT}"
echo "  Region   : ${REGION}"
echo "  Service  : ${SERVICE}"
echo "  Image    : ${IMAGE}:${TAG}"
echo "  Time     : $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── 1. Build ─────────────────────────────────────────────────────────────────
echo ""
echo "[1/5] Building container image..."
docker build \
  --tag "${IMAGE}:${TAG}" \
  --tag "${IMAGE}:latest" \
  --progress=plain \
  .

# ── 2. Push ──────────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Pushing to Artifact Registry..."
docker push "${IMAGE}:${TAG}"
docker push "${IMAGE}:latest"

# ── 3. Deploy ────────────────────────────────────────────────────────────────
echo ""
echo "[3/5] Deploying to Cloud Run (min-instances=1 for production)..."
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}:${TAG}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 1 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60 \
  --concurrency 80 \
  --set-env-vars "APP_ENV=production,LOG_LEVEL=INFO" \
  --set-secrets "STORE_FIXTURE_PATH=store-fixture:latest" \
  --no-csek-key-file

# ── 4. Capture revision ──────────────────────────────────────────────────────
REVISION=$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --format="value(status.latestCreatedRevisionName)" \
  --project "${PROJECT}")

echo ""
echo "[4/5] Deployed revision: ${REVISION}"

# ── 5. Verify ────────────────────────────────────────────────────────────────
if [[ "${VERIFY}" == "true" ]]; then
  echo ""
  echo "[5/5] Verifying deployment..."
  SERVICE_URL=$(gcloud run services describe "${SERVICE}" \
    --region "${REGION}" \
    --format="value(status.url)" \
    --project "${PROJECT}")

  # Health check
  HEALTH_STATUS=$(curl -sf "${SERVICE_URL}/health" -o /dev/null -w "%{http_code}" || echo "000")
  if [[ "${HEALTH_STATUS}" == "200" ]]; then
    echo "  ✓ /health returned 200"
  else
    echo "  ✗ /health returned ${HEALTH_STATUS} — DEPLOYMENT MAY BE UNSTABLE" >&2
    exit 1
  fi

  # Readiness check
  READY_STATUS=$(curl -sf "${SERVICE_URL}/ready" -o /dev/null -w "%{http_code}" || echo "000")
  if [[ "${READY_STATUS}" == "200" ]]; then
    echo "  ✓ /ready returned 200"
  else
    echo "  ✗ /ready returned ${READY_STATUS} — NOT READY FOR TRAFFIC" >&2
    exit 1
  fi

  # Verify response contains production env flag
  HEALTH_BODY=$(curl -sf "${SERVICE_URL}/health")
  if echo "${HEALTH_BODY}" | grep -q '"app_env":"production"'; then
    echo "  ✓ APP_ENV=production confirmed in /health response"
  else
    echo "  ✗ APP_ENV not set to 'production' — check env var injection" >&2
    echo "  Health body: ${HEALTH_BODY}" >&2
    exit 1
  fi

  echo ""
  echo "=== Deployment successful ==="
  echo "  Service URL : ${SERVICE_URL}"
  echo "  Revision    : ${REVISION}"
  echo ""
  echo "Rollback command:"
  echo "  gcloud run services update-traffic ${SERVICE} \\"
  echo "    --to-revisions=${REVISION}=100 --region=${REGION} --project=${PROJECT}"
else
  echo ""
  echo "[5/5] Skipped verification (VERIFY=false)"
fi
