# 0024a. BigQuery `sales_events` evidence — schema, IAM, units, and source-of-truth

Date: 2026-10-18

## Status

Proposed

## Context

ADR 0024 commits the durable agent pipeline to BigQuery as the canonical evidence store and binds the Investigator's `get_sales_history` read port to `retailtwin.sales_events` through `apps/api/retailtwin_api/bigquery_sales_history.py`. The reader is shipped on `main` (`258cc6d`, PR #308) and the P017 fixture suite is green locally; issue #215 calls out sub-task 1 — *"validate production table schemas, locations, IAM, and timestamp/unit semantics; settle single SoT for sales vs Firestore Live quantities"* — and says nothing in `docs/adr/` traces that review against the deployed project.

Without this record the next reviewer reading the reader cannot tell, from a doc alone, which `sales_events` columns the reader trusts, which BigQuery dataset and IAM principal grant the read, what `quantity` means, or how `sales_events` and the Firestore Live Twin relate. A misconfigured project_id, a sibling dataset, or a row with `quantity` denominated in shelf units instead of units per `sale.completed` event could all pass the bounded `LIMIT`-style query and silently change `version` outputs.

The deployed table is fixed for now. `bq show retailtwin-ai-511002:retailtwin.sales_events` reports **49 rows across 2 SKUs** in `us-central1` (window 2026-09-12 → 2026-10-08). Production reads `us-central1` and never crosses regions. Three alternatives were considered:

- **Document the schema only** in `bigquery_sales_history.py`'s docstring. Loses the IAM contract, units, and the sales↔inventory SoT split a later reader needs.
- **Put the schema in `infrastructure/gcp/README.md` only.** Splits the *what* (schema and units) from the *why* (durable evidence) and hides the source-of-truth split from the agent-evidence log.
- **Capture schema, IAM, units, and SoT in one ADR addendum** that lives beside ADR 0024 so a reader of the durable pipeline finds the contract on the next click. This is the option below.

## Decision

This record commits four contracts that the durable `get_sales_history` port relies on. None change the code; they document what the code already enforces.

### 1. Source-of-truth split between sales and inventory

Two stores back the agent evidence:

| Concern | Canonical store | Doc / code |
| --- | --- | --- |
| Sales velocity / demand signal | BigQuery `retailtwin.sales_events` | ADR 0005; ADR 0024; `bigquery_sales_history.py` |
| Inventory state (facings, on-shelf units) | Firestore `(default)` live-twin documents | ADR 0003; ADR 0004; ADR 0029 |

Sales rows and inventory rows are **joined by `sku` only**, not by `quantity`. `sales_events.quantity` counts units sold per `sale.completed` event and never equals `inventory.{on_hand|facing}` — those are different units of truth owned by different stores. Any Investigator evidence that needs both reads them through their own ports (`get_sales_history` for sales; the Firestore Live-Twin port, ADR 0003, for inventory) and the Planner composes the two. A migration that adds a `quantity` join between the two stores is rejected here: it would force one store to drift from its SoT.

### 2. Table schema (canonical, as deployed)

The reader queries `retailtwin-ai-511002.retailtwin.sales_events` (the constants `ALLOWED_PROJECT_ID`, `ALLOWED_DATASET_ID`, `TABLE_SALES_EVENTS` in `bigquery_sales_history.py` line 50–54 pin this lineage and refuse any other). The canonical documented schema is:

```
retailtwin-ai-511002.retailtwin.sales_events
  event_id        STRING    NOT NULL   -- one row per accepted sale.completed
  correlation_id  STRING    NOT NULL   -- run-id grouping across Pub/Sub + BigQuery
  event_type      STRING    NOT NULL   -- constant: "sale.completed"
  store_id        STRING    NOT NULL   -- multi-tenant partition key
  sku             STRING    NOT NULL   -- join key with Firestore Live Twin
  quantity        INT64     NOT NULL   -- units sold per sale.completed event
  occurred_at     TIMESTAMP NOT NULL   -- server-side sale time (event time)
  source          STRING    NOT NULL   -- publishing subsystem (e.g. "historical-pos")
  landed_at       TIMESTAMP NOT NULL   -- Pub/Sub / BigQuery landing time
                                       -- (= the deployed column "ingested_at";
                                       -- the reader surfaces it as "landed_at")
```

`occurred_at` is partitioned (DAY) and the table is clustered by `store_id, sku` so a bounded `(store_id, sku, window_hours)` read stays inside the slot. The deployed table today exposes the same semantic column under the name `ingested_at` (set by the analytics backbone at INSERT time, ADR 0005); the reader aliases it as `landed_at` in SQL and in the `BigQuerySalesEvidence.source_watermark` field so the application contract and the on-disk column name do not drift in lockstep.

### 3. IAM — read access only

BigQuery read access for the agent pipeline goes to one service account on one dataset on one table:

| Principal | Scope | Role |
| --- | --- | --- |
| `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | `retailtwin` dataset | `roles/bigquery.dataViewer` (BigQuery read; foundation day-0 bootstrap grants the project-level `roles/datastore.user`, `roles/logging.logWriter` and grants `roles/aiplatform.user` to the agent SA; the BigQuery grant is scoped on the dataset, not the project) |
| `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | `sales_events` table | `roles/bigquery.dataViewer` (table-level, dataset-scoped) |

The `retailtwin-agent` service account (Vertex only, foundation day-0 bootstrap) is **not** granted BigQuery access. The agent code path never queries BigQuery directly — `read_sales_history` always runs in the API process and the Investigator carries the read port. No service-account key is created; the API runtime uses ADC via the Cloud Run runtime identity (`retailtwin-api@…iam.gserviceaccount.com`). Operators verify the grant with the day-0 gate (`scripts/day0_evidence.py::_assert_can_query_bigquery`) which probes a `SELECT 1 FROM retailtwin.sales_events LIMIT 1` and refuses if the active identity lacks `bigquery.dataViewer` on the dataset.

### 4. Units and time semantics

The `quantity` field on a single row is **unit count per `sale.completed` event**, not per shelf unit, not per day, not per `correlation_id`. The same row contributes its `quantity` exactly once to `BigQuerySalesEvidence.total_quantity` (the typed model sums `int(getattr(row, "quantity", 0))` for every returned row). Aggregation windows (e.g. `total_quantity` across a 168-hour window) are the sum of these per-event counts; a Friday / Saturday split is the sum of the rows whose `occurred_at` falls in the split's UTC bounds.

Two timestamps per row, one each for the two clock meanings:

| Column | Meaning | Set by | Used as |
| --- | --- | --- | --- |
| `occurred_at` | Server-side sale time (event time) | The publisher at `sale.completed` (POS / scheduler) | Windowing: the `WHERE occurred_at BETWEEN start AND end` clause; UTC, timezone-aware |
| `landed_at` | Pub/Sub / BigQuery landing time | The lander (BigQuery INSERT timestamp) | `BigQuerySalesEvidence.source_watermark = MAX(landed_at)` over the window's rows; the `version` digest includes it so two snapshots with the same rows but different landing times still produce a different `sales-evidence-<digest>` |

`landed_at` is the watermark because the Investigator needs the operational "how fresh is the snapshot" marker, not the event time itself; the event-time filter already lives in the query. The reader normalises both timestamps to UTC ISO-8601 before the `version` digest.

## Consequences

- **Schema and units are pinned.** A misconfigured dataset, an extra column, a `quantity` denominator drift, or a row whose `landed_at` advances without an `occurred_at` advance are visible from this record before they reach the reader.
- **IAM is one principal, one dataset, one table.** The agent SA stays out of BigQuery. No key is created. The day-0 gate proves the reader runs under the right identity on every release.
- **SoT split is explicit.** Sales velocity is a BigQuery read; inventory state is a Firestore read. A future reader who tries to join the two stores on `quantity` finds the rejection here and reopens this record instead of slipping the change in.
- **Time semantics are unambiguous.** `occurred_at` partitions the rows; `landed_at` marks the snapshot. `version` is a sha256-prefix over `(query_window, source_watermark, data_lineage, content_digest)` and is therefore stable across distinct BigQuery jobs over identical rows (`tests/test_bigquery_sales_history.py::TestReadSalesHistoryDeterminism::test_two_runs_against_same_rows_return_identical_evidence`).
- **No code change in this record.** A future record that adds columns, changes the IAM principal, or relocates the dataset updates this addendum first. A change to the sales↔inventory SoT split requires a new ADR with `Supersedes #0024a`.

- Pull request:
- Issue: #215
- Supersedes:
- Superseded by:
