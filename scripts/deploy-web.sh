#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ID="retailtwin-ai-511002"
readonly SITE_ID="retailtwin-ai-511002"
readonly API_ORIGIN="https://retailtwin-api-537192856637.us-central1.run.app"

if ! command -v firebase >/dev/null 2>&1; then
  echo "firebase-tools is required (https://firebase.google.com/docs/cli)." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required." >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/apps/web"

npm ci
VITE_API_BASE_URL="${API_ORIGIN}" npm run build

if grep -R -F "http://127.0.0.1:8000" dist >/dev/null 2>&1 || \
   grep -R -F "http://localhost" dist >/dev/null 2>&1; then
  echo "Refusing to deploy: the production bundle contains a localhost API origin." >&2
  exit 1
fi

grep -R -F "${API_ORIGIN}" dist >/dev/null || {
  echo "Refusing to deploy: the production bundle does not contain ${API_ORIGIN}." >&2
  exit 1
}

cd "${repo_root}"
firebase deploy \
  --only "hosting:${SITE_ID}" \
  --project "${PROJECT_ID}" \
  --non-interactive

echo "Frontend: https://${SITE_ID}.web.app"
echo "API:      ${API_ORIGIN}"
