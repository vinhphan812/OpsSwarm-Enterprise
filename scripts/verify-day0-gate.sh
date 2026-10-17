#!/usr/bin/env bash
# Day-0 Foundation Gate orchestrator for RetailTwin AI.
# Read-only smoke test that proves the production cloud path works end to end.
#
# Usage:
#   ./scripts/verify-day0-gate.sh                      # full PASS-required run
#   ./scripts/verify-day0-gate.sh --skip-vertex        # skip the billable Gemini call
#   ./scripts/verify-day0-gate.sh --skip-pubsub        # skip the sale.completed publish
#   CLOUD_RUN_URL=... ./scripts/verify-day0-gate.sh    # override the deployed URL
#
# Exit codes:
#   0  every check PASS
#   1  at least one check FAIL
#   2  precondition not met
#
# The script delegates to scripts/day0_evidence.py for the cloud-facing
# checks and to npm/jq/grep for the web build and repo hygiene checks.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE_SCRIPT="${REPO_ROOT}/scripts/day0_evidence.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ── Helpers ────────────────────────────────────────────────────────────────────
_failures=0
_pass()    { echo "PASS  $*"; }
_fail()    { echo "FAIL  $*" >&2; _failures=$((_failures + 1)); }
_warn()    { echo "WARN  $*"; }
_note()    { echo "NOTE  $*"; }
_section() { echo ""; echo "─── $* ───"; }

# ── Parse flags ───────────────────────────────────────────────────────────────
SKIP_VERTEX=0
SKIP_PUBSUB=0
REQUIRE_BQ_ROW=0
CLOUD_RUN_URL="${CLOUD_RUN_URL:-https://retailtwin-api-5rgtvr4gpa-uc.a.run.app}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-vertex) SKIP_VERTEX=1; shift;;
    --skip-pubsub) SKIP_PUBSUB=1; shift;;
    --require-bq-row) REQUIRE_BQ_ROW=1; shift;;
    --cloud-run-url) CLOUD_RUN_URL="$2"; shift 2;;
    --help|-h)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0;;
    *) _fail "Unknown flag: $1"; exit 1;;
  esac
done

# ── Preconditions ─────────────────────────────────────────────────────────────
_section "Preconditions"

if ! command -v gcloud >/dev/null 2>&1; then
  _fail "gcloud CLI is not on PATH"
  exit 2
fi
if ! command -v bq >/dev/null 2>&1; then
  _fail "bq CLI is not on PATH (part of gcloud SDK)"
  exit 2
fi
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  _fail "${PYTHON_BIN} is not on PATH"
  exit 2
fi
if [[ ! -f "${EVIDENCE_SCRIPT}" ]]; then
  _fail "Evidence script missing at ${EVIDENCE_SCRIPT}"
  exit 2
fi

active_account="$("${PYTHON_BIN}" -c "import subprocess,sys; r=subprocess.run(['gcloud','config','get-value','account'],capture_output=True,text=True); sys.stdout.write(r.stdout.strip())" 2>/dev/null || true)"
active_project="$("${PYTHON_BIN}" -c "import subprocess,sys; r=subprocess.run(['gcloud','config','get-value','project'],capture_output=True,text=True); sys.stdout.write(r.stdout.strip())" 2>/dev/null || true)"

# Project lock is mandatory; identity is capability-based (see
# scripts/day0_evidence.py). An optional DAY0_REQUIRED_ACCOUNTS env var
# pins execution to one or more specific accounts when set.
if [[ "${active_project}" != "retailtwin-ai-511002" ]]; then
  _fail "Active gcloud project is '${active_project}'. Day-0 Gate requires retailtwin-ai-511002."
  exit 2
fi
if [[ -n "${DAY0_REQUIRED_ACCOUNTS:-}" ]]; then
  IFS=',' read -ra expected_accounts <<< "${DAY0_REQUIRED_ACCOUNTS}"
  matched=0
  for acct in "${expected_accounts[@]}"; do
    if [[ "${active_account}" == "${acct// /}" ]]; then
      matched=1
      break
    fi
  done
  if [[ "${matched}" -eq 0 ]]; then
    _fail "Active gcloud account is '${active_account}'. DAY0_REQUIRED_ACCOUNTS=${DAY0_REQUIRED_ACCOUNTS}."
    exit 2
  fi
fi
echo "PASS  gcloud + bq + python available; account ${active_account} on retailtwin-ai-511002"

# ── 1. Web + 3D build ────────────────────────────────────────────────────────
_section "1. Web + 3D load"

if ! command -v node >/dev/null 2>&1; then
  _fail "node is not on PATH (required to build apps/web)"
  exit 2
fi
node_major="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [[ "${node_major}" -lt 20 ]]; then
  _fail "Node ${node_major} is too old; >= 20.17 is required (apps/web constraint)"
  exit 2
fi

if [[ ! -d "${REPO_ROOT}/apps/web/node_modules" ]]; then
  _warn "apps/web/node_modules is missing; running npm ci before the build"
  (cd "${REPO_ROOT}/apps/web" && npm ci)
fi

# A clean build is the cheapest reliable signal that the 3D entry point,
# scene tree, and StoreStatus panel still compile against the current code.
if (cd "${REPO_ROOT}/apps/web" && npm run build >/tmp/day0_web_build.log 2>&1); then
  if [[ -f "${REPO_ROOT}/apps/web/dist/index.html" ]]; then
    _pass "apps/web production bundle built (dist/index.html present)"
  else
    _fail "apps/web build returned 0 but dist/index.html is missing"
  fi
else
  _fail "apps/web production build failed (see /tmp/day0_web_build.log)"
fi

# ── 2-6. Cloud + repo checks (delegated to day0_evidence.py) ─────────────────
_section "2-6. Cloud + repository checks (day0_evidence.py)"

EVIDENCE_FLAGS=(--cloud-run-url "${CLOUD_RUN_URL}")
[[ "${SKIP_VERTEX}" -eq 1 ]] && EVIDENCE_FLAGS+=(--skip-vertex)
[[ "${SKIP_PUBSUB}" -eq 1 ]] && EVIDENCE_FLAGS+=(--skip-pubsub)
[[ "${REQUIRE_BQ_ROW}" -eq 1 ]] && EVIDENCE_FLAGS+=(--require-bq-row)

EVIDENCE_OUTPUT_DIR="${REPO_ROOT}/artifacts/day0-foundation"
mkdir -p "${EVIDENCE_OUTPUT_DIR}"

set +e
(cd "${REPO_ROOT}" && "${PYTHON_BIN}" "${EVIDENCE_SCRIPT}" "${EVIDENCE_FLAGS[@]}")
python_rc=$?
set -e

latest_evidence="${EVIDENCE_OUTPUT_DIR}/latest.json"
if [[ ! -s "${latest_evidence}" ]]; then
  _fail "day0_evidence.py did not write ${latest_evidence}"
else
  echo "PASS  evidence written to ${latest_evidence}"
  # Surface each check from the JSON so this script's output is self-contained.
  "${PYTHON_BIN}" - "${latest_evidence}" <<'PY'
import json, sys
evidence = json.load(open(sys.argv[1]))
for c in evidence.get("checks", []):
    marker = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}.get(c["status"], "????")
    print(f"  {marker:4} {c['id']:24}  {c['message']}")
summary = evidence.get("summary", {})
print(f"  summary: {summary['pass']} pass / {summary['fail']} fail / {summary['skipped']} skipped")
PY
fi

# ── Final summary ─────────────────────────────────────────────────────────────
_section "Day-0 Foundation Gate result"
if [[ "${python_rc}" -eq 0 && "${_failures}" -eq 0 ]]; then
  echo "ALL CHECKS PASSED."
  echo "Evidence: ${latest_evidence}"
  echo "Tag day0-foundation is now permitted on the current main commit."
  exit 0
fi

echo "${_failures} orchestrator-level check(s) failed."
echo "day0_evidence.py exit code: ${python_rc}"
echo "Evidence (if any): ${latest_evidence}"
exit 1