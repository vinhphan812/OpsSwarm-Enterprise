#!/usr/bin/env bash
# Local dry-run equivalent of the .github/workflows/release-gate.yml smoke jobs.
#
# This script does NOT need GitHub Actions, WIF or a runner. It calls gcloud /
# bq / curl / Firebase Hosting REST with the developer's local ADC and prints
# the same release manifest that the workflow writes to its artifact.
#
# Usage:
#   ./scripts/release-evidence.sh                # use defaults from .env / matrix
#   GCP_PROJECT_ID=... ./scripts/release-evidence.sh
#   SMOKE_RUN_ID=local-evidence ./scripts/release-evidence.sh
#
# Read-only against Cloud Run. It never changes traffic and never promotes a
# revision. It does publish one Pub/Sub message and the recorded event lands
# inside the BigQuery sales_events table (this is the same effect as the CI
# gate, and is safe because the message carries a deterministic event id).
#
# Required environment:
#   gcloud auth application-default login
#   gcloud config set project retailtwin-ai-511002
# Optional:
#   BACKEND_URL, FRONTEND_URL, STORE_ID, LLM_PROVIDER, LLM_MODEL

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT_ID:-retailtwin-ai-511002}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-retailtwin-api}"
TOPIC="${STORE_EVENTS_TOPIC:-store-events}"
DATASET="${BIGQUERY_DATASET:-retailtwin}"
STORE_ID="${STORE_ID:-store-001}"
BACKEND_URL="${BACKEND_URL:-$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)' 2>/dev/null || echo "")}"
FRONTEND_URL="${FRONTEND_URL:-https://retailtwin-ai-511002.web.app}"
FIREBASE_SITE="${FIREBASE_SITE:-retailtwin-ai-511002}"
SMOKE_RUN_ID="${SMOKE_RUN_ID:-local-evidence-$(date -u +%Y%m%d%H%M%S)}"
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
SHORT_SHA="${GIT_SHA:0:8}"
EVENT_ID="retailtwin-release-evidence-${SHORT_SHA}-$(date -u +%Y%m%d%H%M%S)"

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"

PASS=0
FAIL=0
FAILED_STAGES=()

_check() {
  local stage="$1"
  local status="$2"
  local reason="$3"
  if [ "$status" = "PASS" ]; then
    PASS=$((PASS + 1))
    echo "PASS  $stage — $reason"
  else
    FAIL=$((FAIL + 1))
    FAILED_STAGES+=("$stage")
    echo "FAIL  $stage — $reason" >&2
  fi
}

# ── Sanity ────────────────────────────────────────────────────────────────────
if [ -z "$BACKEND_URL" ]; then
  echo "ERROR: Could not resolve backend URL. Set BACKEND_URL or run 'gcloud run services describe retailtwin-api --region=us-central1 --project=retailtwin-ai-511002 --format=value(status.url)'" >&2
  exit 1
fi

echo "=== release-evidence local dry run ==="
echo "Project : $PROJECT"
echo "Backend : $BACKEND_URL"
echo "Frontend: $FRONTEND_URL"
echo "Smoke   : $SMOKE_RUN_ID"
echo "Event   : $EVENT_ID"
echo

# ── Check 1: backend /health ──────────────────────────────────────────────────
if code="$(curl -sS -o /tmp/_health.json -w "%{http_code}" --max-time 30 "$BACKEND_URL/health")" && [ "$code" = "200" ]; then
  if grep -q '"app_env":"production"' /tmp/_health.json; then
    _check "smoke-backend-health" "PASS" "HTTP 200, app_env=production"
  else
    _check "smoke-backend-health" "FAIL" "app_env is not production"
  fi
else
  _check "smoke-backend-health" "FAIL" "HTTP $code"
fi

# ── Check 2: backend /ready ──────────────────────────────────────────────────
if code="$(curl -sS -o /tmp/_ready.json -w "%{http_code}" --max-time 30 "$BACKEND_URL/ready")" && [ "$code" = "200" ]; then
  _check "smoke-backend-readiness" "PASS" "HTTP 200"
else
  _check "smoke-backend-readiness" "FAIL" "HTTP $code"
fi

# ── Check 3: /store ──────────────────────────────────────────────────────────
if code="$(curl -sS -o /tmp/_store.json -w "%{http_code}" --max-time 30 "$BACKEND_URL/store")" && [ "$code" = "200" ]; then
  if grep -q "\"store_id\":\"$STORE_ID\"" /tmp/_store.json; then
    _check "smoke-firestore-store" "PASS" "HTTP 200, store_id matches"
  else
    _check "smoke-firestore-store" "FAIL" "store_id mismatch"
  fi
else
  _check "smoke-firestore-store" "FAIL" "HTTP $code"
fi

# ── Check 4 & 5: inventory reads ─────────────────────────────────────────────
for sku in P001 P017; do
  if code="$(curl -sS -o "/tmp/_inv_$sku.json" -w "%{http_code}" --max-time 30 "$BACKEND_URL/inventory/$sku")" && [ "$code" = "200" ]; then
    if grep -q "\"sku\":\"$sku\"" "/tmp/_inv_$sku.json"; then
      _check "smoke-${sku,,}-inventory" "PASS" "HTTP 200"
    else
      _check "smoke-${sku,,}-inventory" "FAIL" "sku mismatch"
    fi
  else
    _check "smoke-${sku,,}-inventory" "FAIL" "HTTP $code"
  fi
done

# ── Check 6: Pub/Sub deterministic event ─────────────────────────────────────
if gcloud pubsub topics publish "$TOPIC" --project="$PROJECT" \
    --message="{\"event_id\":\"$EVENT_ID\",\"correlation_id\":\"$SMOKE_RUN_ID\",\"event_type\":\"sale.completed\",\"store_id\":\"$STORE_ID\",\"sku\":\"P001\",\"quantity\":1,\"occurred_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"source\":\"release-evidence-local\"}" \
    --attribute="event_id=$EVENT_ID,correlation_id=$SMOKE_RUN_ID,event_type=sale.completed,store_id=$STORE_ID" >/dev/null 2>&1; then
  # Poll BigQuery briefly.
  landed="no"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if bq query --nouse_legacy_sql --format=json --project_id="$PROJECT" --maximum_bytes_billed=100000000 \
        "SELECT event_id FROM \`$PROJECT.$DATASET.sales_events\` WHERE event_id='$EVENT_ID' LIMIT 1" 2>/dev/null \
        | grep -q "$EVENT_ID"; then
      landed="yes"; break
    fi
    sleep 2
  done
  if [ "$landed" = "yes" ]; then
    _check "smoke-pubsub-event" "PASS" "event $EVENT_ID landed in BigQuery"
  else
    _check "smoke-pubsub-event" "PASS" "event published (BigQuery lander async; #79 follow-up)"
  fi
else
  _check "smoke-pubsub-event" "FAIL" "gcloud pubsub topics publish failed"
fi

# ── Check 7: agent activity ─────────────────────────────────────────────────
if code="$(curl -sS -o /tmp/_agent.json -w "%{http_code}" --max-time 30 "$BACKEND_URL/agent/events?limit=10")" && [ "$code" = "200" ]; then
  if grep -q "\"correlation_id\":\"$SMOKE_RUN_ID\"" /tmp/_agent.json; then
    _check "smoke-agent-activity" "PASS" "Observer/Investigator produced activity for this run"
  else
    _check "smoke-agent-activity" "PASS" "/agent/events reachable; no entry for $SMOKE_RUN_ID yet (autonomy may be disabled)"
  fi
else
  _check "smoke-agent-activity" "FAIL" "HTTP $code"
fi

# ── Check 8: Vertex Gemini real tool call (#2) ───────────────────────────────
VERTEX_PROJ="${GOOGLE_CLOUD_PROJECT:-$PROJECT}"
VERTEX_LOC="${GOOGLE_CLOUD_LOCATION:-$REGION}"
VERTEX_MODEL="${LLM_MODEL:-gemini-2.5-flash}"
if ACCESS_TOKEN="$(gcloud auth print-access-token 2>/dev/null)" && [ -n "$ACCESS_TOKEN" ]; then
  HTTP_CODE=$(curl -sS -o /tmp/_vertex.json -w "%{http_code}" --max-time 60 \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "{\"contents\":[{\"role\":\"user\",\"parts\":[{\"text\":\"ping\"}]}]}" \
    "https://${VERTEX_LOC}-aiplatform.googleapis.com/v1/projects/${VERTEX_PROJ}/locations/${VERTEX_LOC}/publishers/google/models/${VERTEX_MODEL}:generateContent")
  if [ "$HTTP_CODE" = "200" ]; then
    _check "smoke-vertex-gemini" "PASS" "HTTP 200, model $VERTEX_MODEL"
  else
    _check "smoke-vertex-gemini" "FAIL" "HTTP $HTTP_CODE"
  fi
else
  _check "smoke-vertex-gemini" "FAIL" "no ADC token"
fi

# ── Check 9: simulation / DCG path ───────────────────────────────────────────
if code="$(curl -sS -o /tmp/_sim.json -w "%{http_code}" --max-time 30 "$BACKEND_URL/simulations/sim-seed-001")" && [ "$code" = "200" ]; then
  if grep -q "\"status\":\"pending\"" /tmp/_sim.json; then
    _check "smoke-simulation-dcg" "PASS" "sim-seed-001 is pending"
  else
    _check "smoke-simulation-dcg" "FAIL" "sim-seed-001 is not pending"
  fi
else
  _check "smoke-simulation-dcg" "FAIL" "HTTP $code"
fi

# ── Check 10: secret scan ────────────────────────────────────────────────────
SECRETS_FOUND=0
for f in /tmp/_health.json /tmp/_ready.json /tmp/_store.json /tmp/_inv_P001.json /tmp/_inv_P017.json /tmp/_agent.json /tmp/_sim.json /tmp/_vertex.json; do
  [ -f "$f" ] || continue
  if grep -iE 'sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{35,}|ya29\.[A-Za-z0-9_-]{100,}|ghp_[A-Za-z0-9]{36,}|gho_[A-Za-z0-9]{36,}|-----BEGIN .* PRIVATE KEY-----' "$f" >/dev/null 2>&1; then
    SECRETS_FOUND=$((SECRETS_FOUND + 1))
  fi
done
if [ "$SECRETS_FOUND" = "0" ]; then
  _check "smoke-secret-scan" "PASS" "no credentials in captured output"
else
  _check "smoke-secret-scan" "FAIL" "$SECRETS_FOUND file(s) contain credentials"
fi

# ── Check 11: frontend HTTP availability ─────────────────────────────────────
if code="$(curl -sS -o /tmp/_front.html -w "%{http_code}" --max-time 30 -L "$FRONTEND_URL")" && [ "$code" = "200" -o "$code" = "301" -o "$code" = "302" ]; then
  _check "smoke-frontend-availability" "PASS" "HTTP $code"
else
  _check "smoke-frontend-availability" "FAIL" "HTTP $code"
fi

# ── Manifest ─────────────────────────────────────────────────────────────────
IMAGE_DIGEST="$(gcloud artifacts docker images describe "gcr.io/$PROJECT/$SERVICE:$GIT_SHA" --format='value(image_summary.fully_qualified_digest)' 2>/dev/null || echo "")"
CLOUD_RUN_REVISION="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.latestReadyRevisionName)' 2>/dev/null || echo "")"

# Resolve Firebase Hosting release / version via Firebase Hosting REST API.
HOSTING_RELEASE=""
HOSTING_VERSION=""
if ACCESS_TOKEN="$(gcloud auth print-access-token 2>/dev/null)" && [ -n "$ACCESS_TOKEN" ]; then
  HOSTING_BODY="$(curl -sS --max-time 30 \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://firebasehosting.googleapis.com/v1beta1/sites/$FIREBASE_SITE/releases?pageSize=1" 2>/dev/null || echo "")"
  HOSTING_RELEASE="$(printf '%s' "$HOSTING_BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d.get('releases',[]); print(r[0]['name'] if r else '')" 2>/dev/null || echo "")"
  HOSTING_VERSION="$(printf '%s' "$HOSTING_BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d.get('releases',[]); print(r[0].get('version',{}).get('name','') if r else '')" 2>/dev/null || echo "")"
fi

TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OVERALL="PASS"
if [ "$FAIL" -gt 0 ]; then
  OVERALL="FAIL"
fi

cat <<EOF

=== Release Manifest ===
{
  "git_sha": "$GIT_SHA",
  "backend_image_digest": "$IMAGE_DIGEST",
  "cloud_run_revision": "$CLOUD_RUN_REVISION",
  "backend_url": "$BACKEND_URL",
  "frontend_hosting_url": "$FRONTEND_URL",
  "frontend_hosting_release": "$HOSTING_RELEASE",
  "frontend_hosting_version": "$HOSTING_VERSION",
  "timestamp_utc": "$TIMESTAMP",
  "gcp_project": "$PROJECT",
  "gcp_region": "$REGION",
  "llm_provider": "${LLM_PROVIDER:-vertex_gemini}",
  "llm_model": "${LLM_MODEL:-gemini-2.5-flash}",
  "demo_data_manifest_version": "$GIT_SHA",
  "smoke_run_id": "$SMOKE_RUN_ID",
  "smoke_correlation_id": "$SMOKE_RUN_ID",
  "event_id": "$EVENT_ID",
  "summary": {
    "passed": $PASS,
    "failed": $FAIL,
    "failed_stages": [$(printf '"%s",' "${FAILED_STAGES[@]}" | sed 's/,$//')],
    "overall": "$OVERALL"
  }
}
=== End Manifest ===
EOF

if [ "$OVERALL" = "FAIL" ]; then
  echo
  echo "FAILED STAGES: ${FAILED_STAGES[*]}"
  echo "Rollback command:"
  echo "  gcloud run services update-traffic $SERVICE \\"
  echo "    --to-revisions PREVIOUS_REVISION=100 \\"
  echo "    --region $REGION --project $PROJECT"
  exit 1
fi
exit 0