#!/usr/bin/env bash
# Deterministic local harness for ci.yml's detect-changes path classification.
# Keep API_PATTERNS, WEB_PATTERNS, and CONTRACT_PATHS synchronized with ci.yml.
set -euo pipefail

API_PATTERNS="apps/api services/forecasting tests/e2e .github/workflows/api.yml"
WEB_PATTERNS="apps/web .github/workflows/web.yml"
CONTRACT_PATHS="contracts/"

classify() {
  local changed_files="$1"
  local file pattern path
  API_CHANGED="false"
  WEB_CHANGED="false"
  CONTRACTS_CHANGED="false"

  for file in $changed_files; do
    for pattern in $API_PATTERNS; do
      if [[ "$file" == $pattern* ]]; then
        API_CHANGED="true"
        break
      fi
    done

    for pattern in $WEB_PATTERNS; do
      if [[ "$file" == $pattern* ]]; then
        WEB_CHANGED="true"
        break
      fi
    done

    for path in $CONTRACT_PATHS; do
      if [[ "$file" == $path* ]]; then
        API_CHANGED="true"
        WEB_CHANGED="true"
        CONTRACTS_CHANGED="true"
        break
      fi
    done
  done
}

run_case() {
  local name="$1"
  local files="$2"
  local expected_api="$3"
  local expected_web="$4"
  local expected_contracts="$5"

  classify "$files"
  local actual="api=$API_CHANGED web=$WEB_CHANGED contracts=$CONTRACTS_CHANGED"
  local expected="api=$expected_api web=$expected_web contracts=$expected_contracts"

  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL $name: expected $expected; got $actual" >&2
    return 1
  fi
  echo "PASS $name: $actual"
}

run_case "API-only change" \
  "apps/api/retailtwin_api/main.py" \
  true false false
run_case "Web-only change" \
  "apps/web/src/App.tsx" \
  false true false
run_case "mixed API+Web change" \
  "apps/api/retailtwin_api/main.py apps/web/src/App.tsx" \
  true true false
run_case "non-contract API/Web change" \
  "apps/api/retailtwin_api/services/orders.py apps/web/src/pages/Dashboard.tsx" \
  true true false
run_case "genuine contract change" \
  "contracts/openapi/orders.yaml" \
  true true true
run_case "contract plus both surfaces" \
  "contracts/openapi/orders.yaml apps/api/retailtwin_api/routes.py apps/web/src/api/orders.ts" \
  true true true

echo "All change-detector cases passed."
