# Demand forecast

Issue #31. Formula id `forecast-demand-v1`. The schema is [forecast-demand.schema.json](forecast-demand.schema.json).

`forecast_demand(sku, horizon)` returns the forecast units, the horizon, the method, `generated_at`, and the sales evidence. This package does not call BigQuery ML and does not read or change the Live Twin.

## Fallback

ML is off unless `use_ml` is true. The fallback method is `window-rate`.

The latest window ends at the latest sale and has the requested length. Its default length is 4 hours, and the maximum is 24. Forecast units repeat the units sold in that window. Units per hour are that total divided by the horizon.

The prior window is the same interval one day earlier. Direction is `up`, `down`, or `flat`. It is `unavailable` when the prior window has no sales. A repeated `event_id` counts once.

## Model

A caller may pass a model whose `predict` returns units over the horizon. `ForecastModelError` leaves the window rate in place and sets `ml_status` to `unavailable`. This package does not open a BigQuery client. A later adapter can implement that model.

## P017 weekend series

The committed series in `data/synthetic/weekend-demand-surge.json` sells 50 units on Friday and 73 on Saturday, in matching four-hour windows. The fallback forecast is 73 units, 18.25 per hour, direction `up`, increase 0.46.

## Run

From `services/forecasting`:

```bash
python -m pytest
python -m mypy demand --ignore-missing-imports
```
