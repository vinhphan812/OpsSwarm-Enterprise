# Simulation Service

Clones live state into a simulation branch, applies candidate actions, and calculates before/after KPIs.

Issue #33 is the deterministic evaluator in this package. Formula id `simulation-kpi-v1`. The schema is [kpi/kpi-result.schema.json](kpi/kpi-result.schema.json). It calls stockout risk `stockout-risk-v1` from issue #32. It does not read or change the Live Twin, and it does not wait for the agent loop in issue #15.

## Actions

The action fields match `ActionUnion` in `apps/api/retailtwin_api/contracts.py`:

- `replenish_shelf(sku, quantity)` moves that many units from backroom to shelf. The move fails when the backroom is short.
- `change_facings(sku, facings)` sets the facing count. It does not move units.
- `move_product(sku, from_slot, to_slot)` changes the slot. The destination must be empty.

## Score

Each component is a share of horizon demand, displayed half-up to 0.01.

- `stockout_risk` comes from issue #32 on the clone. An empty shelf with demand scores 1. Otherwise it is uncovered units divided by units needed.
- `service_level` is shelf quantity after the actions, divided by units needed. Stock that is still in the backroom does not count.
- `revenue_benefit` is the extra units the shelf can sell, divided by units needed. `margin_benefit` is 0.
- `movement_cost` is replenished units, plus each facing changed, plus 1 for a slot move, divided by units needed.

`business_score = 1*revenue_benefit + 0*margin_benefit + 1*service_level - 1*stockout_risk - 1*movement_cost`

The score adds the displayed hundredths, so the table below can be checked from the result fields.

The same snapshot and actions always return the same result. A ledger stores that result under `simulation_id` and `candidate_id`. A second call with different actions for that pair fails and leaves the stored result in place.

## P017 weekend shelf

Shelf 8, backroom 54, 18.25 units per hour, horizon 4 hours (73 units needed):

| Candidate | Actions | Score |
| --- | --- | --- |
| baseline | none | -0.04 |
| A | replenish 12 | 0.12 |
| B | facings 2 to 4, replenish 12 | 0.09 |
| C | move slot, facings 2 to 4, replenish 12 | 0.07 |

Stockout risk stays 0.15 for A, B, and C because replenishment does not add inventory. Service level rises from 0.11 to 0.27.

## Run

From `services/simulation`, with issue #32 present at `services/forecasting`:

```bash
python -m pytest
python -m mypy kpi --ignore-missing-imports
```
