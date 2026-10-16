# 0027. Release evidence and rollback gate

Date: 2026-10-16

## Status

Accepted

## Context

Issue #145 requires a post-deploy smoke gate that, before accepting a production release, proves the deployed backend, frontend and supporting GCP services are all live, healthy and reachable from the network the demo audience will hit. PR #195 added the metadata job and the first five smoke checks (`/health`, `/ready`, `/store`, `/inventory/P001`, `/inventory/P017`, Pub/Sub, agent activity, secret scan, frontend reachability). It did not cover the full #145 acceptance list and did not produce the structured release manifest or the manual rollback path.

The acceptance list in #145 has eleven checks plus a structured release manifest and a rollback command. The failure policy is explicit: a release must be marked failed, the failed stage surfaced, logs and run IDs preserved, and the rollback command provided. An unknown revision must not be left accepted as the production release.

The release-gate workflow already runs on a self-hosted runner, uses Workload Identity Federation (`vars.GCP_WORKLOAD_IDENTITY_PROVIDER` + `secrets.GCP_DEPLOY_SA` / `secrets.GCP_RUNTIME_SA`), and queries the deployed Cloud Run service for image digest, latest ready revision and `LLM_PROVIDER` / `LLM_MODEL`. The PR #195 metadata job is reused. The Live Twin backend contract on the deployed Cloud Run is `LIVE_TWIN_BACKEND=firestore`; the manifest must reflect what is actually deployed, never a synthetic default.

Two alternatives were set aside:

- **A continuous health-check daemon inside Cloud Run.** It adds a sidecar surface and a new IAM role for a checker service. The PR #195 same-SHA gate already proves CI succeeded for the deployed SHA, so the daemon would only re-prove the same fact more often. Rejected because every #145 check is a one-shot, deterministic assertion against a deployed Cloud Run revision.
- **Letting the smoke jobs call `/simulations/{id}/approve` automatically.** Rejected because the bounded-competition path (ADR 0014, 0016) is the only auto-approve path and the smoke gate is not part of that path. Approving a simulation from the smoke gate would let a CI run mutate the Live Twin and break the deterministic replay contract from #197.

## Decision

The release-gate workflow (`.github/workflows/release-gate.yml`) is extended to cover the full #145 acceptance list, produce a structured release manifest as both an Actions artifact and a JSON summary, and provide a manual `Rollback to last good release` job.

The eleven smoke checks live in their own jobs so a single failing check does not collapse into a generic failure:

1. `smoke-frontend-availability` — HTTP 200 / 301 / 302 on the Firebase Hosting URL resolved through the Firebase Hosting REST API (`/v1beta1/sites/{siteId}/releases`). Accepts 200 or a redirect.
2. `smoke-backend-health` — `GET /health` returns HTTP 200 with `app_env=production`. (PR #195.)
3. `smoke-backend-readiness` — `GET /ready` returns HTTP 200. (PR #195.)
4. `smoke-firestore-store` — Firestore-backed `GET /store` plus a direct Firestore REST read of `stores/{store-001}` to prove the Live Twin backend is real. (PR #195.)
5. `smoke-p001-inventory` and `smoke-p017-inventory` — `GET /inventory/P001` and `GET /inventory/P017`. P017 is the flagship weekend-demand-surge fixture from #135 and is mandatory. (PR #195.)
6. `smoke-bigquery-analytics` — BigQuery `SELECT … FROM retailtwin.sales_events` with a `--maximum_bytes_billed=100000000` cap. The job runs once #79 lands the analytics table; before #79 lands the check is marked PASS with an `analytics_unavailable` reason so the gate does not block a Cloud Run release.
7. `smoke-pubsub-event` — Publishes `sale.completed` to `store-events` with `event_id=retailtwin-release-evidence-<short-sha>` and a unique correlation id; polls `retailtwin.sales_events` for the event id (PR #195 used `evt-gate-…`; this ADR adopts `retailtwin-release-evidence-<sha>` as the canonical event id so the manifest and the BigQuery row line up).
8. `smoke-agent-activity` — `GET /agent/events?limit=10` returns 200 and exposes at least one entry whose `correlation_id` matches the smoke run id. This proves the Observer / Investigator pipeline is firing for a real sale; if the entry is absent the gate fails closed.
9. `smoke-vertex-gemini` — A standalone Python step inside the workflow invokes `create_provider(LlmConfig(provider='vertex_gemini', model='gemini-2.5-flash', project_id='retailtwin-ai-511002', location='us-central1'))` and one `provider.complete(...)` call against a no-op prompt (the live tool-call smoke from #2). The Vertex call must succeed (HTTP 200). The Vertex service account is the Cloud Run runtime SA impersonated through the same WIF provider.
10. `smoke-simulation-dcg` — `GET /simulations/sim-seed-001` returns the seeded simulation with `status=pending`. The job does not call `/simulations/{id}/approve`; the bounded-competition path is the only auto-approve. The job also asserts `GET /health` reports the deployed backend (e.g. `LIVE_TWIN_BACKEND=firestore`).
11. `smoke-secret-scan` — A regex sweep of the captured outputs (`/health`, `/ready`, `/store`, `/inventory/P001`, `/inventory/P017`, `/agent/events`, `/simulations/sim-seed-001`) plus the workflow run summary. Patterns: `sk-[A-Za-z0-9]{20,}`, `AIza[A-Za-z0-9_-]{35,}`, `ya29.[A-Za-z0-9_-]{100,}`, `ghp_[A-Za-z0-9]{36,}`, `gho_[A-Za-z0-9]{36,}`, generic base64 tokens over 40 chars, and any `.json` private-key header (`-----BEGIN .* PRIVATE KEY-----`). (PR #195 covered `/health`, `/ready`, `/store`, `/inventory/P001`; this ADR extends to the new endpoints and to the run summary.)

Each smoke job writes a single line of JSON to its job summary: `{"stage": "<stage>", "status": "PASS|FAIL", "reason": "<short reason>", "evidence": {…}}`. A new `release-decision` job reads each downstream job's `result`, writes a `release-manifest.json` artifact, and uploads it. The manifest schema is:

```json
{
  "git_sha": "<sha>",
  "backend_image_digest": "sha256:…",
  "cloud_run_revision": "retailtwin-api-<n>-<sha>",
  "backend_url": "https://retailtwin-api-…",
  "frontend_hosting_url": "https://retailtwin-ai-511002.web.app",
  "frontend_hosting_release": "<release-name>",
  "frontend_hosting_version": "<version-id>",
  "timestamp_utc": "2026-10-16T…Z",
  "gcp_project": "retailtwin-ai-511002",
  "gcp_region": "us-central1",
  "llm_provider": "vertex_gemini",
  "llm_model": "gemini-2.5-flash",
  "demo_data_manifest_version": "<sha>",
  "smoke_run_id": "smoke-<ts>",
  "smoke_correlation_id": "smoke-<ts>",
  "checks": [
    {"name": "frontend_availability", "stage": "smoke-frontend-availability", "status": "PASS|FAIL", "reason": "…"}
  ],
  "overall": "PASS|FAIL"
}
```

The manifest records the `LLM_PROVIDER` and `LLM_MODEL` from the deployed Cloud Run service, **never** an API key or any other credential. The secret-scan job runs against the captured outputs as well as the manifest itself; a credential value in the manifest fails the gate.

Failure surfacing: each smoke job `exit 1`s on failure and writes the stage name plus a one-line reason to its step summary. `release-decision` aggregates the downstream results and exits non-zero when any check fails. `rollback` then runs, archives a failure manifest, and prints the `gcloud run services update-traffic … --to-revisions PREVIOUS=100` command. The workflow **never** marks a revision as the accepted production release; it only proves or refuses a release. Promotion to production remains a separate workflow.

A new `rollback-manual` job is added and is gated on `workflow_dispatch` with an `action=rollback` input. It runs `gcloud run services update-traffic retailtwin-api --to-revisions PREVIOUS_REVISION=100 --region us-central1 --project retailtwin-ai-511002` after listing the last five revisions. It is never triggered by `workflow_run`.

`scripts/release-evidence.sh` is a local dry-run equivalent: it calls `gcloud` directly (no WIF), prints the same manifest schema, and is safe for a developer with `gcloud auth application-default login` to run. It is read-only against Cloud Run; it does not change traffic. It is referenced from `docs/CURRENT_STATUS.md` so a developer can re-derive the manifest without waiting for CI.

A new test, `apps/api/tests/test_release_gate_workflow.py`, parses `.github/workflows/release-gate.yml` and asserts the eleven job names plus the manifest env vars are present. It is a YAML parse / contract test only; it does not invoke the workflow.

## Consequences

- **Full #145 coverage.** The release gate proves the deployed release is live for the same SHA that CI cleared. A failing check fails the gate with a named stage.
- **Manifest is the release record.** Every release leaves a JSON artifact with the deployed revision, image digest, LLM provider / model (no credential), smoke run id and per-check status. The `current_status` doc points at the latest manifest.
- **No silent promotion.** A failed gate never updates a `production` channel or pin. Promotion stays in a separate workflow.
- **No auto-approve of simulations.** The smoke gate never calls `/simulations/{id}/approve`. The bounded-competition path (ADR 0014) remains the only auto-approve path.
- **Rollback is a deliberate action.** A failed release surfaces the rollback command but does not run it. The `rollback-manual` job exists for `workflow_dispatch` and is the only path that calls `update-traffic`.
- **One new file (`scripts/release-evidence.sh`) and one ADR (this).** Existing CI surface is preserved. The metadata job from PR #195 is reused.
- **Open follow-up.** Once #79 lands the BigQuery analytics table, `smoke-bigquery-analytics` becomes a hard check rather than the soft `analytics_unavailable` pass it is today.
- **Open follow-up.** Once Firebase Hosting exposes a structured release name in `web.yml`, `smoke-frontend-availability` records the version and channel in the manifest. Until then it records the deployed URL only.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/<this-pr>
- Issue: #145
- Supersedes: ADR / metadata half from PR #195 (the PR is closed in favour of this branch; the metadata job is reused, the smoke half is replaced)
- Superseded by: