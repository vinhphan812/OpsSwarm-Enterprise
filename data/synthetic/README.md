# Synthetic Data

Deterministic retail events used for development and reproducible competition demo scenarios.

`sale-completed.json` is the day-0 `sale.completed` fixture for the store-events backbone. Replaying it keeps the same `event_id` and `correlation_id`, one claim, and one sales row.

`weekend-demand-surge.json` is the Weekend Demand Surge fixture for issue #30. Seed 1 rebuilds the same thirteen `sale.completed` events for `store-001` / `P017`, correlation `run-weekend-demand-surge-1`. Friday 2026-10-09 08:00Z–12:00Z sells 50 units (12.5 per hour). Saturday 2026-10-10 08:00Z–12:00Z sells 73 units (18.25 per hour). The increase is 0.46. A repeated event id counts once, so a replay does not raise the velocity. Another seed is refused. The file is the same series the publisher sends.

From `apps/api`:

```bash
python -m retailtwin_api.demand_surge publish
```

That command publishes each sale on topic `store-events`. It does not start the Observer and it does not change the Live Twin. Landing still follows the store-events claim: one row per `event_id`, and a second publish of the same payload is a duplicate.
