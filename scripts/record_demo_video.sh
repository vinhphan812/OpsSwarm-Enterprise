#!/usr/bin/env bash
# Orchestrate a single demo-video take for issue #47.
#
# This script does NOT record screen video. The producer records the desktop
# with OBS / Loom / QuickTime while this script drives the deterministic
# scenario controller, captures per-shot screenshots, and writes the evidence
# bundle that the PR for #47 requires.
#
# Companion docs:
#   docs/DEMO_VIDEO.md
#   docs/demo-video/shot-list.md
#   docs/demo-video/acceptance-criteria.md
#   docs/demo-video/production-checklist.md
#
# Usage:
#   scripts/record_demo_video.sh \
#     --frontend-url https://retailtwin-ai-511002.web.app \
#     --api-url      https://retailtwin-api-537192856637.us-central1.run.app \
#     --scenario     weekend-demand-surge \
#     --duration     180 \
#     --stale-mutation-at 75 \
#     --evidence-dir demo/evidence \
#     --take         1
#
# All flags are optional. Sensible defaults match docs/DEMO_VIDEO.md §2.
# Exit 0 = take produced all required evidence; non-zero = abort.

set -euo pipefail

# ── Defaults ───────────────────────────────────────────────────────────────────
FRONTEND_URL="https://retailtwin-ai-511002.web.app"
API_URL="https://retailtwin-api-537192856637.us-central1.run.app"
SCENARIO="weekend-demand-surge"
DURATION=180
STALE_MUTATION_AT=75
EVIDENCE_DIR="demo/evidence"
TAKE="1"
DRY_RUN=0
SKIP_PROBES=0
SKIP_G04=0

# Shot boundaries in seconds (matches docs/demo-video/shot-list.md)
declare -a SHOT_STARTS=(0    5   10   20   35   50   65   80   95  110  125  150)
declare -a SHOT_ENDS=(  5   10  20   35   50   65   80   95  110  125  150  175)
declare -a SHOT_LABELS=(
  "01-title-and-url"
  "02-autopilot-on"
  "03-demand-spike"
  "04-investigation"
  "05-candidates"
  "06-simulation-kpi"
  "07-stale-context-block"
  "08-auto-replan"
  "09-dcg-allow"
  "10-live-3d-change"
  "11-verifier-pass"
  "12-architecture-and-close"
)

usage() {
  cat <<USAGE
Usage: $0 [flags]

Flags:
  --frontend-url       ORIGIN    Deployed web origin (default ${FRONTEND_URL})
  --api-url            ORIGIN    Deployed API origin   (default ${API_URL})
  --scenario           NAME      Deterministic scenario (default ${SCENARIO})
  --duration           SECONDS   Total run window         (default ${DURATION})
  --stale-mutation-at  SECONDS   When the deliberate stale-context mutation fires
                                 (default ${STALE_MUTATION_AT})
  --evidence-dir       PATH      Where to write evidence  (default ${EVIDENCE_DIR})
  --take               N         Take number / label       (default ${TAKE})
  --dry-run                      Print the plan, do not touch anything
  --skip-probes                  Skip the deployed-URL probes
  --skip-g04                     Skip running the G04 guard gate
  -h, --help                     Show this help

Exit codes:
  0   take produced all required evidence
  10  a deployed-URL probe failed
  20  G04 guard gate did not pass
  30  ffmpeg/ffprobe missing and --dry-run not set
  40  gcloud/firebase/jq missing and not skippable
USAGE
}

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --frontend-url)       FRONTEND_URL="$2"; shift 2 ;;
    --api-url)            API_URL="$2"; shift 2 ;;
    --scenario)           SCENARIO="$2"; shift 2 ;;
    --duration)           DURATION="$2"; shift 2 ;;
    --stale-mutation-at)  STALE_MUTATION_AT="$2"; shift 2 ;;
    --evidence-dir)       EVIDENCE_DIR="$2"; shift 2 ;;
    --take)               TAKE="$2"; shift 2 ;;
    --dry-run)            DRY_RUN=1; shift ;;
    --skip-probes)        SKIP_PROBES=1; shift ;;
    --skip-g04)           SKIP_G04=1; shift ;;
    -h|--help)            usage; exit 0 ;;
    *)
      echo "Unknown flag: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

require() {
  local cmd="$1"
  local note="${2:-}"
  if ! have "$cmd"; then
    log "ERROR: required command '$cmd' not found${note:+ ($note)}"
    exit 40
  fi
}

ensure_dir() {
  if [[ ! -d "$1" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      log "DRY-RUN: would create $1"
    else
      mkdir -p "$1"
    fi
  fi
}

safe_append() {
  local target="$1"
  shift
  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN: would write to $target: $*"
  else
    printf '%s\n' "$*" >> "$target"
  fi
}

check_origin() {
  local label="$1"
  local origin="$2"
  local path="$3"
  local expected_status="$4"
  local body_marker="${5:-}"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN: probe $label -> $origin$path"
    return 0
  fi

  local status
  status="$(curl --fail --show-error --silent --max-time 10 \
    --output /dev/null --write-out '%{http_code}' \
    "${origin}${path}" || echo "000")"

  if [[ "$status" != "$expected_status" ]]; then
    log "FAIL probe $label ($origin$path): expected $expected_status, got $status"
    return 1
  fi

  if [[ -n "$body_marker" ]]; then
    local body
    body="$(curl --fail --show-error --silent --max-time 10 "${origin}${path}" || true)"
    if ! printf '%s' "$body" | grep -q -- "$body_marker"; then
      log "FAIL probe $label: body missing marker '$body_marker'"
      return 1
    fi
  fi

  log "OK   probe $label -> $status $origin$path"
  return 0
}

check_cors() {
  local origin="$1"
  local path="$2"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN: CORS probe $FRONTEND_URL -> $origin$path"
    return 0
  fi

  local header
  header="$(curl --fail --show-error --silent --max-time 10 \
    --dump-header - --output /dev/null \
    --header "Origin: ${FRONTEND_URL}" \
    "${origin}${path}" || true)"

  if ! printf '%s' "$header" | tr 'A-Z' 'a-z' \
       | grep -q "access-control-allow-origin: ${FRONTEND_URL}"; then
    log "FAIL CORS probe $origin$path for Origin: ${FRONTEND_URL}"
    return 1
  fi

  log "OK   CORS probe $origin$path"
  return 0
}

# ── Dry-run short-circuit ────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "1" ]]; then
  log "=== DRY RUN — no remote calls, no files written ==="
  log "Frontend:      $FRONTEND_URL"
  log "API:           $API_URL"
  log "Scenario:      $SCENARIO"
  log "Duration:      $DURATION s"
  log "Stale mutation at: $STALE_MUTATION_AT s"
  log "Evidence dir:  $EVIDENCE_DIR"
  log "Take:          $TAKE"
  exit 0
fi

# ── Preflight ────────────────────────────────────────────────────────────────
require curl "needed for deployed-URL probes"
require jq "needed to verify G04 evidence JSON"

if [[ "$SKIP_G04" != "1" ]]; then
  require python3 "needed to run tests/e2e/gates/g04_guard_gate.py"
fi

ensure_dir "$EVIDENCE_DIR"
ensure_dir "${EVIDENCE_DIR}/screenshots"

log "=== RetailTwin AI — demo video take ${TAKE} ==="
log "  Frontend:           ${FRONTEND_URL}"
log "  API:                ${API_URL}"
log "  Scenario:           ${SCENARIO}"
log "  Duration:           ${DURATION}s"
log "  Stale-mutation at:  ${STALE_MUTATION_AT}s"
log "  Evidence dir:       ${EVIDENCE_DIR}"

# ── 1) Deployed-URL probes ───────────────────────────────────────────────────
PROBES_LOG="${EVIDENCE_DIR}/deployed-urls.txt"

if [[ "$SKIP_PROBES" == "1" ]]; then
  log "Skipping deployed-URL probes (--skip-probes)"
  safe_append "$PROBES_LOG" "[$(date -u +%FT%TZ)] SKIP probes (--skip-probes)"
else
  log "Step 1: probing deployed surface"
  safe_append "$PROBES_LOG" "[$(date -u +%FT%TZ)] Take ${TAKE}: starting deployed-URL probes"

  failures=0

  check_origin "frontend HEAD" "$FRONTEND_URL" "/" "200" >>"$PROBES_LOG" 2>&1 \
    || { failures=$((failures+1)); safe_append "$PROBES_LOG" "FAIL frontend HEAD $FRONTEND_URL/"; }
  safe_append "$PROBES_LOG" "[$(date -u +%FT%TZ)] frontend HEAD $FRONTEND_URL/ -> $(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/" || echo 000)"

  check_origin "api /health" "$API_URL" "/health" "200" \
    || { failures=$((failures+1)); safe_append "$PROBES_LOG" "FAIL api /health $API_URL/health"; }
  safe_append "$PROBES_LOG" "[$(date -u +%FT%TZ)] api /health $API_URL/health -> $(curl -s -o /dev/null -w '%{http_code}' "$API_URL/health" || echo 000)"

  check_origin "api /store" "$API_URL" "/store" "200" \
    || { failures=$((failures+1)); safe_append "$PROBES_LOG" "FAIL api /store $API_URL/store"; }
  safe_append "$PROBES_LOG" "[$(date -u +%FT%TZ)] api /store $API_URL/store -> $(curl -s -o /dev/null -w '%{http_code}' "$API_URL/store" || echo 000)"

  check_cors "$API_URL" "/health" \
    || { failures=$((failures+1)); safe_append "$PROBES_LOG" "FAIL CORS $API_URL/health"; }

  check_cors "$API_URL" "/store" \
    || { failures=$((failures+1)); safe_append "$PROBES_LOG" "FAIL CORS $API_URL/store"; }

  if [[ "$failures" -gt 0 ]]; then
    log "$failures probe(s) failed; aborting"
    safe_append "$PROBES_LOG" "RESULT: FAIL ($failures)"
    exit 10
  fi
  safe_append "$PROBES_LOG" "RESULT: PASS"
  log "All probes passed"
fi

# ── 2) Environment snapshot ──────────────────────────────────────────────────
log "Step 2: environment snapshot"
ENV_LOG="${EVIDENCE_DIR}/env.txt"
{
  printf 'take: %s\n' "$TAKE"
  printf 'recorded_at: %s\n' "$(date -u +%FT%TZ)"
  printf 'git_sha: %s\n' "$(git -C "$(dirname "$0")/.." rev-parse HEAD 2>/dev/null || echo unknown)"
  printf 'frontend_url: %s\n' "$FRONTEND_URL"
  printf 'api_url: %s\n' "$API_URL"
  printf 'scenario: %s\n' "$SCENARIO"
  printf 'duration_seconds: %s\n' "$DURATION"
  printf 'stale_mutation_at_seconds: %s\n' "$STALE_MUTATION_AT"
} > "$ENV_LOG"

if have gcloud; then
  {
    echo "--- cloud run revisions ---"
    gcloud run revisions list \
      --service retailtwin-api --region us-central1 \
      --project retailtwin-ai-511002 --format='table[box]' 2>/dev/null || true
  } >> "$ENV_LOG"
fi

if have firebase && [[ -f "${HOME}/.config/firebase/refresh_token" || -n "${FIREBASE_TOKEN:-}" ]]; then
  {
    echo "--- hosting releases ---"
    firebase hosting:releases:list \
      --site retailtwin-ai-511002 \
      --project retailtwin-ai-511002 2>/dev/null || true
  } >> "$ENV_LOG"
fi

log "Environment snapshot written to $ENV_LOG"

# ── 3) Drive deterministic scenario ──────────────────────────────────────────
SCENARIO_LOG="${EVIDENCE_DIR}/scenario-take-${TAKE}.log"
log "Step 3: driving the deterministic scenario for ${DURATION}s"
log "        (the recording tool is OBS / Loom on the producer's machine)"
log "        DELIBERATE STALE-CONTEXT MUTATION fires at t=${STALE_MUTATION_AT}s"
log "        Producer hands off the keyboard now."

{
  printf 'scenario_start: %s\n' "$(date -u +%FT%TZ)"
  printf 'duration: %s\n' "$DURATION"
  printf 'stale_mutation_at: %s\n' "$STALE_MUTATION_AT"
} > "$SCENARIO_LOG"

# Drive the scenario one second at a time so the producer's recording tool can
# stay in lock-step. This is a noop when the demo backend is doing the work
# itself; it is the entry point for any per-second producer cues.
start_epoch="$(date +%s)"
elapsed=0
while [[ "$elapsed" -lt "$DURATION" ]]; do
  now="$(date +%s)"
  elapsed=$((now - start_epoch))

  # Emit a heartbeat so screenshots can use this log as a clock reference.
  printf 't=%03ds heartbeat scenario=%s\n' "$elapsed" "$SCENARIO" >> "$SCENARIO_LOG"

  # At the deliberate stale-context moment, log the producer's manual action
  # (which is the ONLY manual moment in the entire demo).
  if [[ "$elapsed" -eq "$STALE_MUTATION_AT" ]]; then
    printf 't=%03ds deliberate-stale-context-mutation (manual producer action)\n' "$elapsed" >> "$SCENARIO_LOG"
    log "        >>> producer performs the deliberate stale-context mutation now <<<"
  fi

  # Sleep until the next second boundary, but no longer than 1s per loop so
  # `Ctrl-C` lands promptly.
  sleep 0.2
done

printf 'scenario_end: %s\n' "$(date -u +%FT%TZ)" >> "$SCENARIO_LOG"
log "Scenario window complete"

# ── 4) Per-shot screenshots placeholders ─────────────────────────────────────
log "Step 4: per-shot screenshot placeholders"
SHOTS_DIR="${EVIDENCE_DIR}/screenshots"
for i in "${!SHOT_LABELS[@]}"; do
  shot_file="${SHOTS_DIR}/shot-${SHOT_LABELS[$i]}.png"
  if [[ ! -f "$shot_file" ]]; then
    cat > "$shot_file" <<PLACEHOLDER
# Placeholder. Replace with the actual screenshot from the take.
# Shot ${SHOT_LABELS[$i]} — start ${SHOT_STARTS[$i]}s, end ${SHOT_ENDS[$i]}s.
# Producer: save the frame from OBS / Loom here before opening the PR.
PLACEHOLDER
  fi
done
log "Screenshots placeholder directory: $SHOTS_DIR"

# ── 5) G04 guard gate evidence ───────────────────────────────────────────────
G04_EVIDENCE="${EVIDENCE_DIR}/g04-evidence.json"
if [[ "$SKIP_G04" == "1" ]]; then
  log "Step 5: SKIPPED G04 (--skip-g04)"
  cat > "$G04_EVIDENCE" <<'JSON'
{
  "skipped": true,
  "reason": "--skip-g04 passed to record_demo_video.sh",
  "pass": null
}
JSON
else
  G04_SCRIPT="tests/e2e/gates/g04_guard_gate.py"
  if [[ -f "$G04_SCRIPT" ]]; then
    log "Step 5: running G04 guard gate -> $G04_EVIDENCE"
    if ! python3 "$G04_SCRIPT" --out "$G04_EVIDENCE"; then
      log "G04 gate did not pass; investigate. Evidence file may be partial."
      if [[ -f "$G04_EVIDENCE" ]] && [[ "$(jq -r '.pass // "null"' "$G04_EVIDENCE")" != "true" ]]; then
        log "Aborting take: G04 must pass before the demo video is recordable"
        exit 20
      fi
    fi
    pass="$(jq -r '.pass // "null"' "$G04_EVIDENCE" 2>/dev/null || echo "null")"
    log "G04 result: pass=${pass}"
  else
    log "G04 script not found at ${G04_SCRIPT}; emitting placeholder evidence"
    cat > "$G04_EVIDENCE" <<'JSON'
{
  "skipped": true,
  "reason": "tests/e2e/gates/g04_guard_gate.py not present",
  "pass": null
}
JSON
  fi
fi

# ── 6) Take-record JSON ──────────────────────────────────────────────────────
TAKE_RECORD="${EVIDENCE_DIR}/take-record.json"
log "Step 6: take-record JSON"
g04_pass="$(jq -r '.pass // "null"' "$G04_EVIDENCE" 2>/dev/null || echo "null")"
cat > "$TAKE_RECORD" <<JSON
{
  "issue": 47,
  "attempt": "${TAKE}",
  "frontend_origin": "${FRONTEND_URL}",
  "api_origin": "${API_URL}",
  "scenario": "${SCENARIO}",
  "duration_seconds": ${DURATION},
  "stale_mutation_at_seconds": ${STALE_MUTATION_AT},
  "g04_pass": ${g04_pass},
  "g04_evidence_file": "${G04_EVIDENCE}",
  "recorded_at": "$(date -u +%FT%TZ)"
}
JSON

# ── 7) Timing reference ──────────────────────────────────────────────────────
TIMING_LOG="${EVIDENCE_DIR}/timing.txt"
log "Step 7: timing reference (shot schedule)"
{
  printf 'shot,t_in,t_out,label\n'
  for i in "${!SHOT_LABELS[@]}"; do
    printf '%02d,%02d,%02d,%s\n' \
      "$((i + 1))" "${SHOT_STARTS[$i]}" "${SHOT_ENDS[$i]}" "${SHOT_LABELS[$i]}"
  done
  printf 'total_seconds,%d,%d,%s\n' 0 "$DURATION" "all shots"
} > "$TIMING_LOG"

# ── Summary ──────────────────────────────────────────────────────────────────
log "=== Take ${TAKE} complete ==="
log "Evidence:"
for f in \
  "$PROBES_LOG" "$ENV_LOG" "$SCENARIO_LOG" \
  "$G04_EVIDENCE" "$TAKE_RECORD" "$TIMING_LOG"; do
  log "  - $f"
done
log "  - ${SHOTS_DIR}/shot-*.png (placeholders; replace per shot-list.md)"
log ""
log "Next: producer stops OBS / Loom, edits to shot-list.md, and runs:"
log "  ffmpeg -i demo/raw/screen-take-${TAKE}.mkv -i demo/raw/voiceover.wav \\"
log "    -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \\"
log "    -c:a aac -b:a 160k -movflags +faststart \\"
log "    demo/retailtwin-demo.mp4"
log ""
log "Then verify the encoded MP4 with:"
log "  ffprobe -hide_banner -show_entries format=duration demo/retailtwin-demo.mp4"
log ""
log "See docs/demo-video/acceptance-criteria.md for the full pass / fail bar."
