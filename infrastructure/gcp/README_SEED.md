# Demo Data Seed and Reset

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This directory contains scripts to seed and reset the GCP services for the
deterministic RetailTwin AI end-to-end demo.

## Scenario

**Weekend Demand Surge / P017** — the canonical flagship demo scenario.

- **Baseline (Friday)**: 50 units sold in 4 hours (12.5/hour)
- **Surge (Saturday)**: 73 units sold in 4 hours (18.25/hour)
- **Increase**: 46%
- **Trigger**: The AI detects the demand surge and recommends increasing P017 facings

## Demo Flow

```
RESET → Firestore baseline → BigQuery context → Pub/Sub event →
Observer → Investigator → Planner → Simulation → KPI → DCG →
Live mutation → Verifier → 3D update
```

## Scripts

| Script | Purpose |
|--------|---------|
| `seed_gcp.py` | Seed all GCP services (Firestore, BigQuery, Pub/Sub) |
| `seed_firestore.py` | Seed Firestore Live Twin with 556 products including P017 |
| `seed_bigquery.py` | Seed BigQuery with 4 weeks of historical sales context |
| `seed_pubsub.py` | Publish demand-surge events through Pub/Sub |
| `reset_demo.py` | Reset all GCP services to baseline |
| `seed-demo.sh` | Shell wrapper for all seed operations |

## Usage

### Seed All Services

```bash
# Preview all operations
python infrastructure/gcp/seed_gcp.py --dry-run

# Seed all services
CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py

# Seed and publish demo events
CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py --publish-events

# Full reset and seed
CONFIRM_RESET=yes CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py --reset
```

### Individual Service Operations

```bash
# Firestore only
CONFIRM_SEED=yes python infrastructure/gcp/seed_firestore.py

# BigQuery only
CONFIRM_SEED=yes python infrastructure/gcp/seed_bigquery.py --dry-run  # Preview
CONFIRM_SEED=yes python infrastructure/gcp/seed_bigquery.py           # Execute

# Pub/Sub events only
CONFIRM_SEED=yes python infrastructure/gcp/seed_pubsub.py --phase=baseline  # Friday only
CONFIRM_SEED=yes python infrastructure/gcp/seed_pubsub.py --phase=surge     # Saturday only
CONFIRM_SEED=yes python infrastructure/gcp/seed_pubsub.py                    # All events
```

### Reset Services

```bash
# Preview reset
python infrastructure/gcp/reset_demo.py --dry-run

# Reset all services
CONFIRM_RESET=yes python infrastructure/gcp/reset_demo.py

# Reset Firestore only
CONFIRM_RESET=yes python infrastructure/gcp/reset_demo.py --firestore-only
```

## Seed Data

### Firestore Live Twin

The Firestore seed creates 556 products (`data/seed/demo_seed.py`): the demo
store (P001-P016, P018, P020, P101-P637, the same products as
`data/schemas/store-state.demo.json`) plus P017. It writes them in commits of
at most 500, Firestore's limit per commit. Including:

| SKU | Shelf | Slot | Facings | Shelf Qty | Backroom Qty |
|-----|-------|------|---------|-----------|--------------|
| P001 | A01 | A01-S01 | 3 | 8 | 42 |
| **P017** | **A02** | **A02-S03** | **3** | **12** | **35** |
| P002 | A01 | A01-S20 | 2 | 10 | 10 |
| ... | ... | ... | ... | ... | ... |

P017 is the demand-surge target with limited initial facings (3) that the AI
will recommend increasing to handle the weekend surge.

### BigQuery Historical Context

4 weeks of historical sales data for P017 showing the recurring weekend surge pattern:
- Friday: ~50 units
- Saturday: ~73 units
- Weekdays: ~25 units

This context helps the AI's forecasting and KPI calculations.

### Pub/Sub Events

The demand-surge event series:
- 5 baseline events (Friday, 50 units total)
- 8 surge events (Saturday, 73 units total)
- All events share correlation_id `run-weekend-demand-surge-1`

## Idempotency and reset safety

All demo event IDs use the `retailtwin-demo-` namespace and remain
**deterministic** so fixture replay is reproducible.  A reset deletes only:

- `stores/store-001/inventory/*`; and
- `store_event_claims` documents whose final document ID begins
  `retailtwin-demo-`.

The claim deletion and inventory reset use one Firestore commit. This means a
successful reset removes stale demo claims before deterministic demo events are
published again. Claims with any other event ID are locally filtered out before
they can become delete writes. If cleanup cannot fit in one atomic Firestore
commit, reset fails closed rather than partially cleaning claims. BigQuery
cleanup has the same namespace predicate: `event_id LIKE 'retailtwin-demo-%'`.

Seed writes use `NOT EXISTS` for deterministic event IDs; this makes a
completed seed replay idempotent. A BigQuery command error is **not** treated as
"skipped" or a duplicate: seed exits non-zero with the failed event ID and does
not write a success manifest, preserving the manifest from the last complete
seed for reset/recovery.

### Dry run and confirmation

`--dry-run` is offline and makes no GCP API, `gcloud`, or `bq` request. It
prints only the bounded namespace and payload plan. Without `--dry-run`, reset
requires `CONFIRM_RESET=yes`; seed requires `CONFIRM_SEED=yes`.

## Prerequisites

1. GCP project: `retailtwin-ai-511002`
2. Region: `us-central1`
3. Billing enabled
4. APIs enabled: Firestore, BigQuery, Pub/Sub
5. Apply foundation: `infrastructure/gcp/bootstrap.sh`
6. Apply store-events: `infrastructure/gcp/apply-store-events.sh`

## Verification

```bash
# Verify Firestore seed
python -c "
from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository
repo = FirestoreLiveTwinRepository()
inv = repo.list_inventory('store-001')
print(f'Store products: {len(inv)}')
for item in inv[:5]:
    print(f'  {item.sku}: qty={item.shelf_quantity}, facings={item.facings}')
"

# Verify BigQuery seed
bq query --project_id=retailtwin-ai-511002 \
  "SELECT sku, COUNT(*) as events, SUM(quantity) as units
   FROM retailtwin.sales_events
   WHERE sku = 'P017'
   GROUP BY sku"
```

## See Also

- [docs/DEMO_AND_ACCEPTANCE.md](../../docs/DEMO_AND_ACCEPTANCE.md) — demo scenario details
- [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) — system architecture
- [docs/DOMAIN_AND_DATA_MODEL.md](../../docs/DOMAIN_AND_DATA_MODEL.md) — data model
