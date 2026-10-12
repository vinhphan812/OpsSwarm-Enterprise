# Stockout risk

Issue #32. Formula id `stockout-risk-v1`. The schema is [stockout-risk.schema.json](stockout-risk.schema.json).

The calculation does not call a forecasting service and does not read or change the Live Twin. Issue #31 may pass a forecast later. Until then the caller omits it.

## Inputs

- `shelf_quantity` and `backroom_quantity`: non-negative integers.
- `sales_velocity_units_per_hour`: observed demand, a finite decimal. This is required.
- `forecast_units_per_hour`: optional decimal. It is used only when it is higher than the observed rate.
- `horizon_hours`: defaults to 4, the same window as the weekend demand surge.
- `observed_at`: timezone-aware. The evidence stores UTC.
- `context_version` and `correlation_id`: provenance copied onto the evidence.

## Rule

Demand rate = observed velocity, or the forecast when the forecast is higher.

Units needed = demand rate × horizon.

Shortfall = max(0, units needed − shelf quantity).

Replenishment = min(shortfall, backroom quantity).

Uncovered = shortfall − replenishment.

Shelf hours of cover = shelf quantity / demand rate, omitted when demand is zero. Displayed rates are half-up to 0.01.

| Result | When |
| --- | --- |
| `normal` | Demand is zero, or the shelf and backroom together cover the horizon |
| `near_stockout` | The shelf still has stock and uncovered units remain |
| `stockout` | The shelf is empty and demand is above zero |

`backroom_covers_horizon` is true when the shortfall is positive and the backroom covers all of it. An empty shelf is still `stockout` in that case, because the shelf is empty now.

`high_demand` is true at 18.25 units per hour or more. That is the Saturday rate of the weekend demand surge for P017 (issue #30, seed 1): 73 units in 4 hours.

## P017 example

Shelf 8, backroom 54, velocity 18.25, horizon 4:

- units needed 73
- shortfall 65
- replenishment 54
- uncovered 11
- shelf cover 0.44 hour
- level `near_stockout`, `high_demand` true

## Run

From `services/forecasting`:

```bash
python -m pytest
```
