# Store events

Day-0 analytical backbone for issue #7. ADR [0005](../../docs/adr/0005-land-each-normalized-store-event-once.md) is the decision.

`POST /events` does not publish. The API still starts without Google Cloud credentials. Landing a row does not change the Live Twin, and this subscription does not start the Observer.

## Contract

The message body is the normalized store event in [data/schemas/store-event.schema.json](../../data/schemas/store-event.schema.json). `occurred_at` is the event timestamp.

| | |
| --- | --- |
| Project | `retailtwin-ai-511002` |
| Region | `us-central1` |
| Topic | `store-events` |
| Subscription | `store-events-analytics` (pull, ordering on, no expiration, no push endpoint) |
| Dataset | `retailtwin` |
| `sale.completed` | `sales_events` |
| `inventory.*` | `inventory_events` |
| `agent.*` | `agent_actions` |

Attributes are exactly `event_id`, `correlation_id`, `event_type`, and `store_id`, and each value matches the body. A missing, extra, or mismatched attribute is rejected. The ordering key is `event_id`. Ordered publish and pull use the `us-central1` Pub/Sub endpoint, because the global endpoint rejects an ordering key when the topic stores messages only in that region.

The event-id owner is the Firestore document `store_event_claims/{event_id}` in the existing `(default)` database. The lander creates it only when the document is absent. One create wins. The same normalized payload is a duplicate. A different payload does not replace the claim. BigQuery is derived history. The claim moves `claimed → landing → landed`. The 120 second landing lease chooses who may submit the insert. The BigQuery job id comes from the event id and the claim's insert generation. A takeover submits that same job id and waits for the existing job, so lease expiry during a slow job does not start a second insert. A new generation is written only after that job has finished with an error. `correlation_id` on the row is the published value. These claim documents are not Live Twin state. Issue #6 still owns the Live Twin.

The lander acknowledges inserted, duplicate, and conflict outcomes. A rejected message is written to `store_event_rejects` before it is acknowledged. If that write fails, the message stays unacknowledged. This command is the day-0 analytics lander. It is not the Observer and it does not attach a dead-letter topic.

The publisher emits `sale.completed` only. Inserts are BigQuery query jobs, not streaming inserts, so they stay on the on-demand query allowance. There is no reservation. The query still includes `NOT EXISTS`. That clause is not the uniqueness owner. A repeated job id joins the existing job. A process-local lock is not the owner either.

The committed fixture is [data/synthetic/sale-completed.json](../../data/synthetic/sale-completed.json): event `evt-sale-0001`, correlation `run-20261007-001`, store `store-001`, SKU `P001`, quantity 3.

The Weekend Demand Surge fixture is [data/synthetic/weekend-demand-surge.json](../../data/synthetic/weekend-demand-surge.json). Seed 1 is thirteen `sale.completed` events for SKU `P017`. Friday sells 50 units in four hours and Saturday sells 73, an increase of 0.46. `python -m retailtwin_api.demand_surge publish` sends that series on `store-events`. The same claim rules apply. The command does not start the Observer and does not change the Live Twin.

## Apply and check

The topic and the empty dataset come from the cloud foundation. This script adds the subscription and the three tables. It refuses every project except `retailtwin-ai-511002` and every region except `us-central1`. It does not create keys or change IAM.

```bash
CONFIRM_GCP_STORE_EVENTS=yes infrastructure/gcp/apply-store-events.sh
infrastructure/gcp/verify-store-events.sh
```

`verify-store-events.sh` only reads the project. Exit 0 means the topic, subscription, dataset, and tables match. Exit 1 is any mismatch.

## Publish and trace

From `apps/api`, with the API virtualenv and Application Default access through `gcloud`:

```bash
python -m retailtwin_api.backbone_cli smoke
```

The command publishes the fixture, lands it, publishes the same event again, and checks that the replay is a duplicate. The trace keeps one row and the correlation id `run-20261007-001`. A second smoke run reports the first delivery as `duplicate` as well. `publish` sends the fixture without consuming it.

The day-0 command uses the operator's project credentials. `retailtwin-api` stays the runtime publisher and does not receive BigQuery write or subscription pull access here.
