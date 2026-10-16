# 0041. Synthetic customer-traffic simulator and zone heatmap

Date: 2026-10-16

## Status

Accepted

## Context

Issue #36 asks for a customer-traffic simulator and zone heatmap to feed
the Investigator (#215) and the 3D Live/Simulation views. The Investigator
already consumes BigQuery `sales_events`; the heatmap needs a separate
signal — the volume of shoppers present in each zone over a window — that
sales cannot express.

Two alternatives were considered:

- **Reusing the `sales_events` wire shape for traffic.** A sale is a single
  SKU at a point in time, so re-purposing it for "5 shoppers, 80 seconds
  each, in zone A01" loses meaning and over-fits downstream consumers to
  one event type.
- **A separate `traffic_events` BigQuery table.** Keeps the wire shape
  honest: traffic is a continuous quantity, sales are discrete events.
  The table is provisioned as a follow-up; the simulator locks the contract
  before any table is created.

A deterministic simulator must be replayable so tests, demos and the
Investigator agree on the same heatmap for a given seed, window, and store
state.

## Decision

A new module `apps/api/retailtwin_api/synthetic/traffic.py` defines:

- `TrafficEvent` — a single zone sample: `timestamp`, `zone_id`,
  `customer_count`, `dwell_seconds`.
- `TrafficSimulator` — wraps a seeded `random.Random`. `simulate` returns
  one event per `(minute, zone)` pair when the seeded per-zone count is
  non-zero, so empty minutes stay absent from the heatmap. `started_at`
  must be timezone-aware; `duration_minutes` must be positive;
  `customer_count` must be non-negative; `seed` must be a non-negative
  integer.
- `aggregate_heatmap(events)` — returns `dict[zone_id, customer_seconds]`
  summing `customer_count * dwell_seconds`, rounded to two decimals.
- `simulate_traffic(snapshot, duration_minutes=60, customer_count=42, seed=...)` —
  one-shot wrapper for callers that don't need a reusable simulator.
- `derive_zone_ids(snapshot)` — unique sorted `shelf_id`s from the
  `StoreResponse`.
- A `main(argv)` CLI that loads the day-0 store fixture and writes the
  JSON stream to stdout or `--output`. Other backends (memory Live Twin,
  Firestore) are not supported in the CLI; the simulator runs on the
  deterministic day-0 fixture only.

A new `Settings.traffic_enabled` flag (default `false`) gates a
`GET /traffic/heatmap?store_id=...&window_minutes=60` route that returns
a `TrafficHeatmapResponse` (`store_id`, `window_minutes`, `started_at`,
`zone_customer_seconds`, `total_customer_seconds`, `simulator_seed`).
When the flag is off the route returns 503 `traffic_disabled`, so the
day-0 surface stays unchanged. The simulator and aggregator stay
importable; only the public route is gated.

The wire contract is intentionally separate from `sales_events`. A future
`traffic_events` BigQuery table (issue #36 follow-up) carries the same
shape; this module writes only the in-process stream so the contract is
locked before any table is provisioned.

## Consequences

- **Replayable heatmap.** Same `seed` + same `StoreResponse` + same window
  produces the same event stream. Tests assert equality directly and via
  JSON round-trip.
- **Backwards compatible.** Default off; no day-0 route, no schema, no
  BigQuery table is added when `TRAFFIC_ENABLED` is unset.
- **Wire contract separation.** Downstream consumers that already speak
  `sales_events` keep that contract; a new `traffic_events` consumer gets
  the new shape.
- **Fixture-only CLI.** The CLI rejects memory or Firestore stores because
  the simulator must run on the deterministic day-0 fixture; widening
  the supported backends is a later decision.
- **Follow-up work.** Provision the `traffic_events` BigQuery table,
  bind the heatmap to the Investigator's evidence (#215), and render the
  heatmap in the 3D view are separate issues.

- Pull request: feat(#36): deterministic customer traffic simulator + zone heatmap
- Issue: #36
- Supersedes:
- Superseded by: