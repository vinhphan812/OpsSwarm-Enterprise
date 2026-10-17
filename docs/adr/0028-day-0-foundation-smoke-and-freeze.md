# 0028. Day-0 foundation smoke test and freeze

Date: 2026-10-16

## Status

Accepted

## Context

Issue [#10](https://github.com/vinhphan812/retailtwin-ai/issues/10) is the
release-blocker gate for Day-0. It states that "components can pass
separately and still fail together" and requires one integrated run that
proves the real cloud path works end to end:

1. The web app and 3D scene load.
2. SKU `P001` is visible through a Firestore-backed API.
3. The Pub/Sub event path lands `sale.completed` rows in BigQuery.
4. Gemini (Vertex AI, `gemini-2.5-flash`) executes a real
   `get_inventory(P001)` tool call and the typed Live Twin document is the
   result.
5. The deployed Cloud Run service is reachable and serves the canonical
   fixture contract.
6. No secrets are committed to the repository.
7. An integrated smoke test reports PASS, and only then is a
   `day0-foundation` git tag applied to `main`.

Until now these checks have been scattered across
`scripts/verify-cloud-preflight.sh`, the opt-in
`apps/api/tests/test_vertex_inventory_live.py`, the `release-gate.yml`
workflow, and ad-hoc curl probes. None of them on its own can answer the
gate question. A drift between the deployed Cloud Run revision and the
Firestore Live Twin is invisible to any single check.

## Decision

The Day-0 Foundation Gate is one **read-only, opt-in, evidence-emitting**
script `scripts/verify-day0-gate.sh` that exercises every required cloud
resource against the canonical production project `retailtwin-ai-511002`
in `us-central1` and reports a single PASS/FAIL line per check, an
overall summary, and a JSON evidence file. The gate script:

- Hits the deployed Cloud Run service (`/health`, `/store`,
  `/inventory/P001`) and asserts `app_env=production`,
  `fixture_loaded=true`, and the canonical fixture SKU `P001` is in the
  response.
- Reads `stores/store-001` and `stores/store-001/inventory/P001` from
  Firestore directly (REST, ADC token) and asserts the document matches
  the published `InventoryDocument` schema (`store_id`, `sku`,
  `shelf_id`, `slot_id`, `facings`, `shelf_quantity`,
  `backroom_quantity`, `version`, `updated_at`).
- Boots a local API process with `LIVE_TWIN_BACKEND=firestore`,
  `APP_ENV=e2e-smoke`, and `AUTONOMY_ENABLED=false`, asserts the same
  `/inventory/P001` response comes from the Firestore adapter, then
  shuts the process down.
- Publishes a single deterministic `sale.completed` event through
  `retailtwin_api.backbone_cli publish`, then asserts the message is
  delivered to subscription `store-events-analytics` within 30 s.
  Whether the message is then written to `retailtwin.sales_events` by
  the analytics lander is recorded as `bq_landed` in the evidence; the
  default run does not require the row. Pass `--require-bq-row` (or
  set `DAY0_REQUIRE_BQ_ROW=1`) to make the row mandatory when the
  lander is known to be up.
- Runs the opt-in Vertex live read
  (`apps/api/tests/test_vertex_inventory_live.py`,
  `RETAILTWIN_VERTEX_LIVE=1`), asserts the returned `ProductInventory`
  matches the Firestore document for `P001` (shelf, slot, facings,
  shelf quantity, backroom quantity, version).
- Builds the web app (`npm run build` from `apps/web`) and asserts the
  built bundle exposes the 3D entry script and the StoreStatus panel.
- Runs the repository hygiene scan from `.github/workflows/ci.yml` to
  confirm no `.env` files, no committed secrets, no conflict markers,
  and no malformed workflow YAML.

The script is **capability-based**. It refuses to run unless the
active gcloud project is `retailtwin-ai-511002`, the active identity
can read `stores/store-001` in Firestore, and the active identity can
query `retailtwinsales_events` in BigQuery. The active gcloud user
account, a WIF impersonation, or a self-hosted runner service account
are all accepted as long as the IAM allows the probes above. The
optional `DAY0_REQUIRED_ACCOUNTS` environment variable pins execution
to one or more named accounts (comma-separated) for environments that
want a closed identity allowlist.

Exit codes:

- `0` — every check passed; an evidence JSON is written to
  `artifacts/day0-foundation/<run-id>.json`.
- `1` — at least one check failed; the JSON file is written with the
  failing checks populated.
- `2` — script precondition was not met (wrong project, missing
  ADC, missing npm, capability probe refused).

The `day0-foundation` git tag is **only** applied to `main` when the
script exits `0` on the merge commit that lands this ADR. The gate
prints a "Tag day0-foundation is now permitted" line on exit `0`, then
the human runs `git tag -a day0-foundation -m "..."` separately. The tag
itself is never created by the script.

## Consequences

- The gate is reproducible from a clean shell. CI can run it on demand
  but does not require it; the canonical run is local against the real
  project.
- The Cloud Run service stays on `LIVE_TWIN_BACKEND=memory` (fixture)
  for Day-0. The Firestore-backed read is proven by a separate local
  process; production `firestore` wiring is tracked on issues
  [#134](https://github.com/vinhphan812/retailtwin-ai/issues/134) and
  [#143](https://github.com/vinhphan812/retailtwin-ai/issues/143) and
  is **not** in scope for this ADR.
- A new contract test `apps/api/tests/test_day0_smoke.py` pins the
  script's structure: it does not call GCP, but it asserts the
  evidence JSON schema, the check list, and the opt-in environment
  variables the script expects.
- `docs/CURRENT_STATUS.md` gains a "Day-0 Foundation Gate" entry
  pointing at the script and the tag.
- `docs/DAY0_GATE_RUNBOOK.md` records how to run the gate, how to
  interpret the evidence, and how to tag `day0-foundation`.

- Pull request: <https://github.com/vinhphan812/retailtwin-ai/pull/243>
- Issue: <https://github.com/vinhphan812/retailtwin-ai/issues/10>
- Supersedes:
- Superseded by: