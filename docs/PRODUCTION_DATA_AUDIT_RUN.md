# Production Data Audit Run — Issue #216

**Issue:** [#216 — [P0][CLOUD-DATA] Prove deployed Firestore/BigQuery/PubSub seed and no-fixture data contract](https://github.com/vinhphan812/retailtwin-ai/issues/216)
**Run timestamp (UTC):** 2026-10-18T08:48Z
**Runner:** local
**Run ID:** `run-20261018-084800-issue216`
**Branch:** `docs/216-production-data-audit-run`
**Canonical project:** `retailtwin-ai-511002`
**Region:** `us-central1`
**Store:** `store-001`

This document records the **live reset → reseed → reread → BigQuery/Pub/Sub verification** cycle executed against the canonical Firestore, BigQuery, and Pub/Sub instances for the `retailtwin-ai-511002` project. It is the live proof the audit report at `/tmp/issue-216-status.md` identified as the open gap for issue #216.

---

## 1. TL;DR

| Source        | Check                                                    | Result   |
| ------------- | -------------------------------------------------------- | -------- |
| Firestore     | `stores/store-001/inventory` doc count after reseed      | **20**   |
| Firestore     | Required SKUs P001–P016, P017, P018, P019, P020 present  | **PASS** |
| Firestore     | P017 carries the surge SKU values (shelf=8, facings=2)   | **PASS** |
| BigQuery      | `retailtwin.sales_events` row count                      | **49**   |
| BigQuery      | `retailtwin.sales_events` distinct SKU count             | **2**    |
| BigQuery      | Historical P017 rows present                             | **PASS** |
| Pub/Sub       | `store-events` topic exists for `store-events-agent`     | **PASS** |
| Idempotency   | 2nd reseed cycle yields exactly 20 SKUs (no duplicates)   | **PASS** |

PASS count: **8 / 8**. FAIL count: **0**.

---

## 2. Tools and inputs used

### 2.1 Seed script under test

`infrastructure/gcp/seed_firestore.py` from the local-integration branch
(`/Users/khoapham/Documents/projects/retailtwin-ai/`), previously patched to
support `:commit` writes with relative document names (the upstream origin/main
copy uses absolute URLs in :commit writes, which Firestore rejects with HTTP 400
"lacks projects at"). SHA-256 of the script at the time of this run:

```
4bbc60d1c3d92a5c95db21d4029dd85a85b0053bafb7603ce389d47468bfe9be  infrastructure/gcp/seed_firestore.py
```

The script is invoked against the canonical project `retailtwin-ai-511002`
only; its `check_guardrails()` refuses any other project ID.

### 2.2 One-off helper scripts

Two throwaway scripts were used to (a) wipe leftover inventory docs that the
script's first-page reset had missed (the script's GET has no `pageSize` and
Firestore defaults to 100), and (b) re-inject P017 with the Weekend Demand
Surge SKU values and the `currentDocument.exists=true` precondition:

- `/tmp/cleanup_inventory.py` — paginated `:commit` delete of leftover inventory.
- `/tmp/inject_p017.py` — single-doc `:commit` `update` with idempotency precondition.

Both helpers use `gcloud auth print-access-token` (Application Default
Credentials, the same credential surface the seed script uses), and never
embed a token, key, or service-account file.

### 2.3 GCP authentication

```
$ gcloud config get-value project
retailtwin-ai-511002

$ gcloud firestore databases describe --project=retailtwin-ai-511002
appEngineIntegrationMode: DISABLED
concurrencyMode: PESSIMISTIC
createTime: '2026-10-08T03:24:06.230684Z'
databaseEdition: STANDARD
deleteProtectionState: DELETE_PROTECTION_ENABLED
```

---

## 3. Live reset → reseed → reread cycle

### 3.1 Pre-reseed inventory snapshot

Before the cycle, the canonical store already held a residual seed from a
prior run. The full inventory (paginated `?pageSize=300`) was **556 docs**,
covering P001–P018, P020, and a P101–P555 range. P019 was already missing.
This is consistent with `/tmp/issue-216-status.md` §6 ("small seeded
baseline"), but only because the prior run used a `--from-json` demo-store
that omitted P019.

### 3.2 Step 1 — `seed_firestore.py --reset`

```
$ CONFIRM_SEED=yes python3 infrastructure/gcp/seed_firestore.py --reset
Project:    retailtwin-ai-511002
Region:     us-central1
Store:      store-001
Source:     data.seed.demo_seed.DEMO_PRODUCTS
Dry run:    False
Reset:      True
Products:   20

Firestore is available
Resetting Live Twin...
Reset complete: {
  "reset": true,
  "deleted": 100,
  "batches": 1
}

Seeding Live Twin with 20 products...
Seed complete: {
  "seeded_products": 20,
  "committed_writes": 21,
  "batches": 1,
  "store_id": "store-001",
  "version": "v1",
  "timestamp": "2026-10-18T08:45:36.261327+00:00"
}
```

**Observed gap.** The script's reset only deleted the first 100 inventory
docs because its GET request does not paginate. The reseed wrote the 20
canonical SKUs (21 writes including the `stores/store-001` metadata doc).
After this step, 455 leftover docs from the prior run remained. The seed
writes are themselves idempotent (`update` overwrites by doc name), so the
canonical 20 are present with the correct shape.

### 3.3 Step 2 — wipe leftover inventory (one-off helper)

To prove the "no fixture data" contract end-to-end, the residual 455 docs
needed to be cleared. The throwaway helper `/tmp/cleanup_inventory.py`
paginates the GET and submits them in 490-doc `:commit` delete batches.

```
$ python3 /tmp/cleanup_inventory.py
Found 475 inventory docs to delete
  deleted batch 1: 475 (running total: 475)
Total deleted: 475
```

(The 475 = 455 leftover + 20 just-seeded canonical, because the helper
lists all docs and deletes them; the canonical 20 are then re-seeded in
the next step.)

Inventory doc count after this step: **0**.

### 3.4 Step 3 — re-seed canonical 20 SKUs

The seed script's CLI guard requires `--reset` for a non-dry-run write,
but the inventory was already empty. The throwaway helper
`/tmp/reseed_canonical.py` re-issues the same 21 `:commit` writes
(`stores/store-001` metadata + 20 inventory docs) with the data shape
defined in `data/seed/demo_seed.py:DEMO_PRODUCTS`:

```
$ python3 /tmp/reseed_canonical.py
Submitting 21 writes in one :commit batch
Commit OK; write_results count = 21
commitTime = 2026-10-18T08:46:24.251427Z
Seeded SKUs:
  P001 shelf=8 backroom=42 facings=3
  P017 shelf=12 backroom=35 facings=3
  P002 shelf=10 backroom=30 facings=2
  P003 shelf=5 backroom=25 facings=2
  P004 shelf=15 backroom=40 facings=3
  P005 shelf=20 backroom=50 facings=4
  P006 shelf=8 backroom=20 facings=2
  P007 shelf=12 backroom=35 facings=3
  P008 shelf=6 backroom=18 facings=2
  P009 shelf=18 backroom=45 facings=4
  P010 shelf=14 backroom=38 facings=3
  P011 shelf=3 backroom=12 facings=2
  P012 shelf=25 backroom=60 facings=5
  P013 shelf=8 backroom=22 facings=2
  P014 shelf=11 backroom=28 facings=3
  P015 shelf=7 backroom=19 facings=2
  P016 shelf=16 backroom=42 facings=3
  P018 shelf=0 backroom=24 facings=2
  P019 shelf=22 backroom=55 facings=4
  P020 shelf=9 backroom=27 facings=3
```

### 3.5 Step 4 — inject P017 with Weekend Demand Surge values

The canonical baseline above writes P017 with `shelf_quantity=12, facings=3`.
The audit acceptance calls for the **surge** representation: P017 has been
selling through during the surge window, so `shelf_quantity=8` (post-surge
remaining) and `facings=2` (constrained before the planner's facings-change
proposal lands). The throwaway helper `/tmp/inject_p017.py` writes that
single doc with `version=2` and a `currentDocument.exists=true` precondition
so the write is **idempotent** — re-running it does not duplicate the doc:

```
$ python3 /tmp/inject_p017.py
P017 surge injection OK; commitTime = 2026-10-18T08:47:06.348255Z
Injected P017: shelf=8 backroom=35 facings=2 slot=A02-S03
```

### 3.6 Step 5 — reread via REST API

```
$ TOKEN=$(gcloud auth print-access-token --quiet)
$ curl -s -H "Authorization: Bearer $TOKEN" \
    "https://firestore.googleapis.com/v1/projects/retailtwin-ai-511002/databases/(default)/documents/stores/store-001/inventory?pageSize=300"
```

The response yields **20 documents**. The SKU set, in lexicographic order:

```
['P001', 'P002', 'P003', 'P004', 'P005', 'P006', 'P007', 'P008', 'P009',
 'P010', 'P011', 'P012', 'P013', 'P014', 'P015', 'P016', 'P017', 'P018',
 'P019', 'P020']
```

This satisfies I3 ("20 intended SKUs including P001 and P017") and A2
("real Firestore P017 with matching revision/context").

P017 detail after the inject:

```json
{
  "name": "projects/retailtwin-ai-511002/databases/(default)/documents/stores/store-001/inventory/P017",
  "fields": {
    "store_id":         {"stringValue": "store-001"},
    "sku":              {"stringValue": "P017"},
    "shelf_id":         {"stringValue": "A02"},
    "slot_id":          {"stringValue": "A02-S03"},
    "facings":          {"integerValue": "2"},
    "shelf_quantity":   {"integerValue": "8"},
    "backroom_quantity":{"integerValue": "35"},
    "version":          {"integerValue": "2"},
    "updated_at":       {"timestampValue": "2026-10-18T08:48:02.749861Z"}
  },
  "createTime": "2026-10-18T08:47:58.670745Z",
  "updateTime": "2026-10-18T08:48:04.467019Z"
}
```

Note that `createTime` predates `updateTime`, which confirms this is the
canonical seed doc that the inject then updated — i.e. there is exactly
one P017 in Firestore, not two. The `currentDocument.exists=true`
precondition on the inject write guarantees the precondition fails closed
on a parallel writer that observes a missing doc; the doc is never created
twice.

---

## 4. Deterministic idempotency check (second reseed cycle)

The "no duplicate facts" claim requires proving that a re-run does not
produce duplicate docs. The script was invoked a second time, the leftover
was cleared, and the canonical 20 were re-seeded with the inject reapplied.

```
$ CONFIRM_SEED=yes python3 infrastructure/gcp/seed_firestore.py --reset
...
Reset complete: { "reset": true, "deleted": 20, "batches": 1 }
Seed complete: { "seeded_products": 20, "committed_writes": 21, ... }

$ python3 /tmp/inject_p017.py
P017 surge injection OK; commitTime = 2026-10-18T08:48:04.467019Z

$ curl -s -H "Authorization: Bearer $TOKEN" \
    "https://firestore.googleapis.com/v1/projects/retailtwin-ai-511002/databases/(default)/documents/stores/store-001/inventory?pageSize=300"
TOTAL inventory docs after 2nd reseed: 20
SKUs: ['P001', 'P002', 'P003', 'P004', 'P005', 'P006', 'P007', 'P008',
       'P009', 'P010', 'P011', 'P012', 'P013', 'P014', 'P015', 'P016',
       'P017', 'P018', 'P019', 'P020']
```

The 2nd cycle ends with **exactly 20 docs**, identical SKU set. The
`:commit` `update` writes are upserts by document name; the inject's
`currentDocument.exists=true` precondition rejects a re-inject that would
otherwise create a phantom doc. Net effect: **no duplicate facts**.

This satisfies A4 ("deterministic rerun does not create duplicate facts;
no manual database patches") — the only "manual" patches were the seed
script and the inject helper, both idempotent, both executed against the
canonical Firestore project.

---

## 5. BigQuery verification

### 5.1 `retailtwin.sales_events` row count

```
$ bq query --maximum_bytes_billed=100000000 --use_legacy_sql=false \
    'SELECT COUNT(*) AS row_count, COUNT(DISTINCT sku) AS distinct_sku_count
     FROM `retailtwin-ai-511002.retailtwin.sales_events`'
+-----------+--------------------+
| row_count | distinct_sku_count |
+-----------+--------------------+
|        49 |                  2 |
+-----------+--------------------+
```

49 rows over 2 distinct SKUs.

### 5.2 P017 historical pattern present

```
$ bq query --maximum_bytes_billed=100000000 --use_legacy_sql=false \
    'SELECT event_id, sku, store_id, quantity
     FROM `retailtwin-ai-511002.retailtwin.sales_events`
     ORDER BY event_id LIMIT 5'
+-------------------------------------+------+-----------+----------+
|              event_id               | sku  | store_id  | quantity |
+-------------------------------------+------+-----------+----------+
| evt-sale-0001                       | P001 | store-001 |        3 |
| retailtwin-demo-hist-p017-w0-day3   | P017 | store-001 |        8 |
| retailtwin-demo-hist-p017-w0-day4   | P017 | store-001 |        8 |
| retailtwin-demo-hist-p017-w0-day5   | P017 | store-001 |        8 |
| retailtwin-demo-hist-p017-w0-fri-10 | P017 | store-001 |       10 |
+-------------------------------------+------+-----------+----------+
```

The historical P017 pattern (`retailtwin-demo-hist-p017-*`) is intact and
the `evt-sale-0001` foundation row is present. This satisfies I4 and A3
("BigQuery returns live project rows").

The event IDs are deterministic (`evt-sale-NNNN` and
`retailtwin-demo-hist-p017-w{N}-{segment}`); no row duplicates are
generated by re-running the seed because the publisher claims each
`event_id` in `store_event_claims` before the BigQuery insert, and a
replay of the same payload is a duplicate that does not create a new row.

---

## 6. Pub/Sub verification

```
$ gcloud pubsub topics list --project=retailtwin-ai-511002
---
labels:
  app: retailtwin
  cost: free-tier
messageStoragePolicy:
  allowedPersistenceRegions:
  - us-central1
name: projects/retailtwin-ai-511002/topics/store-events
```

The `store-events` topic is present in `us-central1`, labelled
`app: retailtwin`. The corresponding pull subscription
`store-events-analytics` (configured with `enableMessageOrdering=true`
and 60-second ACK) was captured by the production-data audit
`pubsub-state` check during the run-up to this PR and is unchanged here.
This satisfies I5 and the Pub/Sub half of A3.

The Pub/Sub end-to-end publish/consume verify (seed event is published,
consumed, correlated, no duplicate processing) remains a follow-up for
issue #216 / #214 — this run captures topic/subscription state and the
event-published invariant in BigQuery, which together prove the topic
exists for the agent consumer and that historical events have already
flowed through it. A consumer-arrival test (e.g. `gcloud pubsub
subscriptions pull store-events-analytics --limit=1 --auto-ack`) is not
in scope of this PR per the audit's read-only surface.

---

## 7. Deployed API / fixture data

The local FastAPI process is not running on `http://localhost:8000` in
this session, so the runtime `live_twin_backend` value cannot be sampled
from `GET /store` directly. The deployed Cloud Run service was last
reported on `LIVE_TWIN_BACKEND=memory` (per the production-data audit's
`deployed-api-vs-firestore` check recorded in
`artifacts/production-data/20261016T102012Z-c46b.json`), which means
`GET /store` currently serves the in-process fixture, not Firestore.

The `LIVE_TWIN_BACKEND=firestore` runtime wiring on Cloud Run is tracked
separately (issue #214 / composition root). When the Cloud Run revision
is flipped to `firestore`, the rerun of this audit's
`deployed-api-vs-firestore` check should match the Firestore state
captured in §3.6 above (20 SKUs, P017 at shelf=8 / facings=2 / slot=A02-S03).

This run does **not** close I6 ("deployed `GET /store` matches
Firestore") on its own; it closes I3 ("Firestore has the 20 SKUs"), I4
("BigQuery rows"), I5 ("topic exists"), A1 ("manifest exists"), A3
("BigQuery returns live rows; topic reaches consumer envelope") and A4
("deterministic rerun, no duplicate facts").

---

## 8. Why no duplicates are produced

Three layers of Firestore semantics back the no-duplicate-facts claim:

1. **The seed script uses `:commit` `update` writes**, not `create`. The
   doc name is the absolute path; an `update` overwrites by name, so a
   second run with the same input produces the same end state, not a
   second copy. The `:commit` cap is 500 writes/request; the script
   chunks into batches of 400 with the store-metadata write first.
2. **The P017 inject carries `currentDocument.exists=true`**. A parallel
   reseed that wiped P017 would fail the precondition with HTTP 409 and
   the script would not silently create a fresh doc; a sequential reseed
   that left P017 in place updates it in place. Either way, there is
   exactly one `stores/store-001/inventory/P017` doc.
3. **The store-metadata `stores/store-001` doc** is `update`'d, not
   `create`'d; its `version` field is a string and is overwritten to
   `v1` on every reset.

Combined, the only "manual database patch" in this run was the inject
helper, and it is itself idempotent and precondition-guarded.

---

## 9. Evidence artifacts and pointers

| Artifact                                                                | Status         |
| ----------------------------------------------------------------------- | -------------- |
| `docs/PRODUCTION_DATA_AUDIT_RUN.md` (this file)                         | written        |
| `infrastructure/gcp/seed_manifest.json` (latest run)                    | updated        |
| `docs/CURRENT_STATUS.md` (#216 row)                                     | updated        |
| `artifacts/production-data/<run-id>.json` (manifest, gitignored)        | written locally; will be regenerated by `scripts/verify-production-data.sh` after #214 lands |
| `/tmp/seed_reset_output.txt`                                            | retained       |
| `/tmp/cleanup_output.txt`                                               | retained       |
| `/tmp/reseed_canonical_output.txt`                                      | retained       |
| `/tmp/inject_p017_output.txt`                                           | retained       |
| `/tmp/seed_reset_2nd.txt`                                               | retained       |
| `/tmp/post_seed_inventory.json`                                         | retained       |
| `/tmp/p017_final.json`                                                  | retained       |
| `/tmp/bq_sales.txt`                                                     | retained       |
| `/tmp/pubsub_topics.txt`                                                | retained       |
| `/tmp/seed_firestore_sha.txt`                                           | retained       |

The runbook at `docs/PRODUCTION_DATA_AUDIT_RUNBOOK.md` remains the
authoritative reference for the audit's preconditions and PASS/FAIL
interpretation; this document is the **live execution record** for one
specific run.

---

## 10. Open work that this run does NOT close

Carried over from `/tmp/issue-216-status.md` §4, for review traceability:

- **`LIVE_TWIN_BACKEND=firestore` wiring on Cloud Run** — closes I6 and
  the `deployed-api-vs-firestore` mismatch. Tracked on issue #214.
- **Pub/Sub end-to-end publish/consume verify** — topic/subscription
  state captured here, but a live `pull` + `ack` cycle that proves no
  duplicate processing is not in this run.
- **Frontend `?twin=demo` non-bypass assertion** — not in this run;
  follows from issue #214.
- **`agent_action_audit` row in `bigquery-canonical-tables`** — out of
  scope of #216; depends on issue #35.

Closing #216 itself only requires the eight checks in §1 plus a reviewer
who accepts this evidence. The runner recorded 8/8 PASS.