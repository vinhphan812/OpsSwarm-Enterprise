# Day-0 Foundation Gate Runbook

> Companion to [ADR 0028](adr/0028-day-0-foundation-smoke-and-freeze.md) and
> [issue #10](https://github.com/vinhphan812/retailtwin-ai/issues/10).
> Use this runbook to **run the gate**, **interpret the evidence**, and
> **tag `day0-foundation`** on `main`.

The Day-0 Foundation Gate is the release-blocker defined by
[issue #10](https://github.com/vinhphan812/retailtwin-ai/issues/10). It
proves that the real production cloud path works end to end:

1. The web app and 3D scene build.
2. SKU `P001` is visible through a Firestore-backed API.
3. A `sale.completed` event is published and delivered to the
   `store-events-analytics` subscription. Whether the row is then
   written to `retailtwin.sales_events` by the analytics lander is an
   **operational observation** recorded by the gate; the gate only
   *requires* the BigQuery row when `--require-bq-row` is passed (or
   `DAY0_REQUIRE_BQ_ROW=1` is set). The default `verify-day0-gate.sh`
   run therefore proves the publish-and-deliver leg; the BigQuery row
   leg is gated by an explicit flag so it does not block the canonical
   run when the lander is offline.
4. Gemini (Vertex AI, `gemini-2.5-flash`) executes a real
   `get_inventory(P001)` tool call and the typed Live Twin document is the
   result.
5. The deployed Cloud Run service is reachable and reports the canonical
   production contract.
6. The repository has no committed secrets, no `.env` files, and no
   merge conflict markers.

The gate **authorises** the `day0-foundation` git tag on `main`. It does
not create the tag itself; tagging is a separate manual step after the
script returns exit code `0` on the same commit.

## What the gate runs

Two scripts collaborate:

- `scripts/verify-day0-gate.sh` — top-level orchestrator. Boots an
  apps/web build and delegates the cloud-facing checks to
  `scripts/day0_evidence.py`. Writes the final summary.
- `scripts/day0_evidence.py` — Python helper that talks to the deployed
  Cloud Run service, Firestore, BigQuery, and Vertex AI. Writes one JSON
  evidence file per run.

The contract tests in `apps/api/tests/test_day0_smoke.py` pin the
structure of both scripts so refactors cannot silently drop a required
check or change the evidence schema.

## Required credentials and tools

- A POSIX shell with `bash`, `gcloud`, `bq`, `node`, and `python3` on
  `PATH`.
- An authenticated gcloud identity (user account, WIF impersonation, or
  self-hosted runner service account) that can read the canonical
  project `retailtwin-ai-511002`. The script is **capability-based**:
  it probes Firestore and BigQuery at startup and refuses to run if the
  active identity cannot read either. The previous version hard-coded a
  single personal account; the new version accepts any identity with
  the right IAM.
- To pin execution to a specific identity (for example, to make CI fail
  closed when a developer runs the gate locally), set the
  `DAY0_REQUIRED_ACCOUNTS` environment variable to a comma-separated
  list of accepted accounts before invoking the script:

  ```bash
  DAY0_REQUIRED_ACCOUNTS=j.dangkhoa.1108@gmail.com,github-actions@retailtwin-ai-511002.iam.gserviceaccount.com \
    ./scripts/verify-day0-gate.sh
  ```
- Application Default Credentials configured for the canonical project
  when running a Vertex check (or any check that uses `google.auth.default`):

  ```bash
  gcloud auth application-default login
  gcloud auth application-default set-quota-project retailtwin-ai-511002
  ```
- `apps/api` installed in editable mode into a Python 3.11+ venv. The
  gate does not require the API to be running in advance — it boots its
  own local process on a free port.

## Running the gate

From the repository root:

```bash
./scripts/verify-day0-gate.sh
```

The script:

1. Verifies gcloud, bq, python3, and node are on `PATH` and that the
   active gcloud account is the billing owner. Refuses to continue if
   the account or project is wrong.
2. Runs `npm ci` (only if `apps/web/node_modules` is missing) and
   `npm run build` from `apps/web`. The production bundle must produce
   `dist/index.html` with exit code `0`.
3. Delegates to `scripts/day0_evidence.py`, which executes the seven
   checks against the canonical cloud project.
4. Surfaces each check as a `PASS` / `FAIL` / `SKIP` line and writes
   the JSON evidence to `artifacts/day0-foundation/<run-id>.json`.

Useful flags:

```bash
./scripts/verify-day0-gate.sh --skip-vertex          # skip the billable Gemini call
./scripts/verify-day0-gate.sh --skip-pubsub          # skip the sale.completed publish
./scripts/verify-day0-gate.sh --require-bq-row       # require the BigQuery row landed (analytics lander must be running)
DAY0_REQUIRE_BQ_ROW=1 ./scripts/verify-day0-gate.sh  # same as --require-bq-row
DAY0_REQUIRED_ACCOUNTS=alice@...,bob@... \
  ./scripts/verify-day0-gate.sh                      # pin execution to specific identities
CLOUD_RUN_URL=https://staging-...run.app \
  ./scripts/verify-day0-gate.sh                      # target a non-production revision
```

Skipped checks are recorded as `SKIP` in the evidence JSON and do not
contribute to PASS / FAIL counts. **Skipping Vertex or Pub/Sub prevents
the gate from authorising `day0-foundation`.** The default run proves
the publish + delivery leg; pass `--require-bq-row` only when the
analytics lander is known to be up and a fresh row must land for the
gate to pass.

## Evidence file

`artifacts/day0-foundation/<run-id>.json` (and the convenience copy
`artifacts/day0-foundation/latest.json`) records:

```json
{
  "schema_version": 1,
  "run_id": "20261016T120000Z-deadbeef",
  "started_at": "2026-10-16T12:00:00Z",
  "finished_at": "2026-10-16T12:01:30Z",
  "project": "retailtwin-ai-511002",
  "region": "us-central1",
  "vertex_model": "gemini-2.5-flash",
  "checks": [
    {
      "id": "cloud-run",
      "status": "pass",
      "message": "Deployed service ... reports production + P001",
      "details": {"p001": {...}}
    },
    ...
  ],
  "summary": {"pass": 7, "fail": 0, "skipped": 0}
}
```

`schema_version` lets future versions of the gate evolve the shape
without breaking readers. The contract test
`test_evidence_schema_matches_when_evidence_file_exists` rejects
evidence files that drop the top-level keys.

## Tagging `day0-foundation`

The gate **authorises** the tag; it does not apply it. Once
`scripts/verify-day0-gate.sh` exits `0` for the same day, on the same
commit you want to freeze, run:

```bash
git tag -a day0-foundation \
    -m "Day-0 Foundation Gate PASS on $(git rev-parse HEAD); evidence: artifacts/day0-foundation/<run-id>.json"
```

The tag annotation must mention the evidence file path. The canonical
commit is the merge commit that lands ADR 0028; never tag a branch tip.

To verify:

```bash
git show day0-foundation
```

## Failure modes and remediation

| Failing check                | Likely cause                                              | Fix                                                                       |
| ---------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------- |
| `cloud-run`                  | Cloud Run revision is broken or rolled back               | Re-run `scripts/deploy-cloudrun.sh`, then re-run the gate                  |
| `firestore-p001`             | Firestore document missing or schema drift                | Re-run `infrastructure/gcp/bootstrap.sh` or seed/reset script             |
| `local-api-firestore`        | ADC not configured or Firestore unreachable from this IP  | Re-run `gcloud auth application-default login`                             |
| `pubsub-event-path`          | Pub/Sub topic or BigQuery dataset missing                 | Re-run `infrastructure/gcp/apply-store-events.sh`                          |
| `vertex-live-inventory`      | Vertex rate-limited, model unavailable, or quota exhausted| Wait, retry; check billing budget `retailtwin-dev-guard`                  |
| `repo-hygiene`               | A `.env` or conflict marker was committed                 | Remove the file or resolve the conflict; re-run                            |

If a check fails repeatedly, attach the evidence JSON to a comment on
issue #10 with the full `details` payload — never paste access tokens.

## Local development loop

While developing the gate itself:

```bash
# From apps/api
PYTHONPATH=apps/api python -m pytest apps/api/tests/test_day0_smoke.py -q
PYTHONPATH=apps/api python scripts/day0_evidence.py --help
bash scripts/verify-day0-gate.sh --help
```

The contract tests do not touch GCP and run in seconds. They are the
fast feedback loop; the full cloud run is the slow confirmation.

## Related documents

- ADR 0028 — [docs/adr/0028-day-0-foundation-smoke-and-freeze.md](adr/0028-day-0-foundation-smoke-and-freeze.md)
- Issue #10 — [https://github.com/vinhphan812/retailtwin-ai/issues/10](https://github.com/vinhphan812/retailtwin-ai/issues/10)
- Cloud Runtime Matrix — [docs/CLOUD_RUNTIME_MATRIX.md](CLOUD_RUNTIME_MATRIX.md)
- Cloud Preflight Verifier — [scripts/verify-cloud-preflight.sh](verify-cloud-preflight.sh)