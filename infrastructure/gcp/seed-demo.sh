#!/usr/bin/env bash
# Seed all GCP services for the deterministic end-to-end demo.
# See infrastructure/gcp/README.md and docs/DEMO_AND_ACCEPTANCE.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load environment
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  source "${ROOT}/.env"
  set +a
fi

PROJECT="${GCP_PROJECT_ID:-retailtwin-ai-511002}"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"

die() {
  echo "error: $*" >&2
  exit 1
}

echo "=============================================="
echo "RetailTwin AI - Demo Data Seeder"
echo "=============================================="
echo "Project: $PROJECT"
echo ""

# Check arguments
DRY_RUN=""
RESET_FLAG=""
PUBLISH_FLAG=""
FIRESTORE_ONLY=""
BIGQUERY_ONLY=""
PUBSUB_ONLY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN="--dry-run" ;;
    --reset) RESET_FLAG="--reset" ;;
    --publish-events) PUBLISH_FLAG="--publish-events" ;;
    --firestore-only) FIRESTORE_ONLY="--firestore-only" ;;
    --bigquery-only) BIGQUERY_ONLY="--bigquery-only" ;;
    --pubsub-only) PUBSUB_ONLY="--pubsub-only" ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

# Determine mode
if [[ -n "$DRY_RUN" ]]; then
  echo "Mode: DRY RUN (no changes will be made)"
  CONFIRM_SEED="dry"
elif [[ -z "${CONFIRM_SEED:-}" ]]; then
  die "Set CONFIRM_SEED=yes to seed, or use --dry-run to preview."
else
  echo "Mode: LIVE (changes will be made to GCP)"
fi

if [[ -n "$RESET_FLAG" && "$CONFIRM_SEED" != "yes" ]]; then
  die "Use CONFIRM_RESET=yes --reset to reset and seed."
fi

export CONFIRM_SEED

echo ""
echo "Seeding GCP services..."

cd "$ROOT"
python infrastructure/gcp/seed_gcp.py \
  $DRY_RUN \
  $RESET_FLAG \
  $PUBLISH_FLAG \
  $FIRESTORE_ONLY \
  $BIGQUERY_ONLY \
  $PUBSUB_ONLY
