#!/usr/bin/env bash
# G06 Submission Gate — production-mode runner (TODO / documented stub)
#
# Scope of THIS file
# --------------------
# The scripts/run-submission-gate.sh orchestrator runs the in-memory preflight
# (TestClient + LIVE_TWIN_BACKEND=memory + FakeLlmProvider). That path is
# stable and produces the 9 deterministic checks the in-memory case has
# always produced. PR #247's reviewers closed the runner for G06 with three
# blockers that converge on a *deployed* production stack, not TestClient.
#
# This file is the documented stub for the production-mode shell that drives
# the *real* Cloud Run revision of retailtwin-api against the *real* Firestore
# Live Twin and the *real* Pub/Sub backbone on retailtwin-ai-511002. It does
# NOT execute against Cloud Run today; it documents the wiring the reviewer
# still requires and intentionally exits non-zero until that wiring ships.
#
# Reviewer blockers (PR #247, 2026-10-16 / 2026-10-17 / 2026-10-18) this
# script is the answer to:
#
#   1. Label environment and source data. The orchestrator must set
#      G06_ENVIRONMENT=production-cloudrun, must capture the deployed Cloud
#      Run revision SHA, and must record app_env + provider_mode + the
#      BigQuery dataset identity and the Pub/Sub subscription name.
#   2. Capture the additional fields the runner previously omitted:
#      cloud_run_revision, provider_mode (vertex_gemini vs fake),
#      live_twin_backend=firestore, the per-action simulation_only vs
#      guarded_live_mutation tag, the DCG audit slice (per-gate verdict +
#      reason_code), and the explicit Verifier verdict.
#   3. Preserve the no-stale-commit negative case as an explicit matrix row.
#
# Required CLI / runtime contract
# -------------------------------
# The Python flagship harness (tests/e2e/gates/run_flagship_scenario.py)
# reads these env vars BEFORE its imports resolve. The production-mode
# shell sets them; the in-memory preflight leaves them unset:
#
#   G06_ENVIRONMENT=production-cloudrun
#   G06_PROVIDER_MODE=vertex_gemini
#   LIVE_TWIN_BACKEND=firestore
#   APP_ENV=production
#   G06_CLOUD_RUN_REVISION=<sha captured from gcloud>
#
# Steps the production shell MUST take
# ------------------------------------
# 1. Confirm we are targeting the canonical GCP project / region:
#      export PROJECT_ID=retailtwin-ai-511002
#      export REGION=us-central1
# 2. Resolve the deployed Cloud Run revision SHA so the evidence is anchored
#    to a real revision, not a 100%-traffic pseudo-name:
#      G06_CLOUD_RUN_REVISION="$(gcloud run services describe retailtwin-api \
#          --project "$PROJECT_ID" --region "$REGION" \
#          --format='value(status.latestReadyRevisionName)')"
# 3. Capture the BigQuery dataset identity, the Pub/Sub topic/subscription
#    pair, and a visible 3D post-commit check pointer. Each is one env var
#    the in-memory harness does NOT need today but the production harness
#    will fail closed on if missing.
# 4. Reuse the existing Python harness with the env vars above. The
#    in-process TestClient path is bypassed by setting
#    G06_RUNTIME=cloudrun and pointing G06_API_URL at the deployed URL.
# 5. Treat any missing checkpoint as a hard fail (fail closed). See:
#      scripts/verify-cloud-preflight.sh --exit-code-on-fail
#
# Why this is a stub today
# ------------------------
# retailtwin-api on Cloud Run today serves only the fixture store reader; it
# does not consume Pub/Sub, does not call Vertex, and does not write to the
# Firestore Live Twin. Wiring that is tracked under issue #143 (Cloud Run CD)
# and #134 (cloud runtime matrix). Until those land, the production run would
#    *either* be a 503 commit_unavailable,
#    *or* a fixture-read 200 that produces no real evidence.
# Neither is G06 reviewable. So this script refuses to run.
#
# Reviewers agree the in-memory runner remains a useful integration preflight
# even after the production runner ships; the orchestrator above is kept for
# that. This stub is the *companion* orchestrator that will produce real
# evidence once the deployed stack is wired.

set -euo pipefail

cat <<'MSG'
G06 production-mode runner (TODO)
=================================

This is a documented stub. It refuses to execute against production today
because the deployed retailtwin-api revision is a fixture-only reader and
does not yet satisfy the production acceptance contract that PR #247's
reviewers required. The in-memory preflight in scripts/run-submission-gate.sh
remains the supported run path until the wiring below is in place.

What the production shell will do once the stack is wired
---------------------------------------------------------

  PROJECT_ID=retailtwin-ai-511002
  REGION=us-central1
  SERVICE=retailtwin-api

  export G06_ENVIRONMENT=production-cloudrun
  export G06_PROVIDER_MODE=vertex_gemini
  export LIVE_TWIN_BACKEND=firestore
  export APP_ENV=production

  # 1. Anchor the run to a real Cloud Run revision (review blocker #2).
  export G06_CLOUD_RUN_REVISION="$(
      gcloud run services describe "$SERVICE" \
          --project "$PROJECT_ID" --region "$REGION" \
          --format='value(status.latestReadyRevisionName)'
  )"

  # 2. Capture the BigQuery / Pub/Sub / Live Twin identity the matrix
  #    expects to appear beside cloud_run_revision (review blocker #2).
  export G06_BIGQUERY_DATASET="retailtwin"
  export G06_PUBSUB_TOPIC="projects/${PROJECT_ID}/topics/store-events"
  export G06_PUBSUB_SUBSCRIPTION="projects/${PROJECT_ID}/subscriptions/store-events-analytics"
  export G06_LIVE_TWIN_KIND="firestore_native_default"

  # 3. Point the Python flagship harness at the deployed URL instead of
  #    the in-process TestClient. The harness picks the right code path
  #    based on G06_RUNTIME.
  export G06_RUNTIME=cloudrun
  export G06_API_URL="https://${SERVICE}-$(gcloud run services describe \
      "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
      --format='value(status.url)' | sed -E 's|https?://||')"

  # 4. Drive the same 20-run loop. The negative-case row is preserved
  #    unchanged by passing --mode negative once per matrix.
  bash scripts/run-submission-gate.sh --runs 20 --seed submission \
      --out gs://retailtwin-evidence/g06/$(date -u +%Y%m%d-%H%M%SZ)/matrix.json

MSG

# Refuse to run until the deployed stack satisfies the contract.
echo "Refusing to run: this is a TODO stub. See comment block above." >&2
exit 78
