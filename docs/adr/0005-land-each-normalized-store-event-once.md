# 0005. Land each normalized store event once

Date: 2026-10-08

## Status

Accepted

## Context

Issue #7 needs an event backbone that can trigger and explain an autonomous run. The domain model already fixes the minimum store event: `event_id`, `correlation_id`, `event_type`, `store_id`, `sku`, `quantity`, `occurred_at`, and `source`. ADR 0003 keeps `POST /events` in process memory and does not publish. The accepted foundation record ADR 0004 puts Pub/Sub topic `store-events` and an empty BigQuery dataset `retailtwin` in `us-central1` and leaves the subscription and the tables to this issue. This record is numbered 0005 so it does not take 0004.

A replay of the same event id has to be visible as a duplicate. BigQuery has no unique constraint. A query-job `NOT EXISTS` insert stops a sequential replay, and two landers can both observe the id as absent and both insert. The same id can also race across the three tables. BigQuery transactions do not add that key. Pub/Sub exactly-once delivery deduplicates a service message id, not a second publish of the same event. Streaming inserts and a Pub/Sub BigQuery subscription are billed outside the on-demand query allowance the foundation stays inside, and both would store a second row unless something else noticed.

Publishing from `POST /events` was set aside. That would replace the acceptance rule in ADR 0003 and would make the API process depend on Google Cloud credentials. A Pub/Sub schema registry entry was set aside too. The registry takes Avro or Protocol Buffer, which would be a second contract beside the JSON shape already in the domain model. A Pub/Sub dead-letter topic was set aside because attaching one would grant the Pub/Sub service agent a new IAM binding.

## Decision

The normalized store event is the Pub/Sub message body. Attributes `event_id`, `correlation_id`, `event_type`, and `store_id` copy those fields. The ordering key is `event_id`. `occurred_at` is the event timestamp.

Topic `store-events` keeps the foundation storage limit of `us-central1`. Subscription `store-events-analytics` is a pull subscription with message ordering, a 60 second ack deadline, 7 day retention, and no expiration. It has no push endpoint.

Dataset `retailtwin` gains three day-partitioned tables, clustered by `store_id` and `sku`:

- `sales_events` receives `sale.completed`
- `inventory_events` receives `inventory.*`
- `agent_actions` receives `agent.*`

The day-0 publisher emits `sale.completed` only. The atomic owner of an `event_id` is the Firestore document `store_event_claims/{event_id}` in the existing `(default)` database in `us-central1`. The lander creates that document with a commit precondition that it does not exist. One create wins. The loser reads the document. The same normalized payload is a duplicate. A different payload or a different table is a conflict and does not replace the document. These documents are an idempotency ledger. They are not Live Twin state, and issue #6 still owns that store.

BigQuery stays derived history. The lander writes a row with a query job, not a streaming insert. `ingested_at` is the write time and is not part of identity. A conflict does not write a row. `correlation_id` on the stored row is the published `correlation_id`.

Only one BigQuery job may insert that row. The claim document moves `claimed → landing → landed`. The move to `landing` is a compare-and-update on the document update time and holds a 120 second lease. That lease chooses who may submit the insert. The job id is `store-event-{sha256(event_id)}-{generation}`, and the generation is stored on the claim. A takeover keeps the generation and submits that same job id. BigQuery returns the existing job, and the lander waits for it, so a job that outlives the lease does not start a second insert. A new generation is written only after that job is DONE and has `errorResult`. The query still includes `NOT EXISTS`, and that clause is not the uniqueness mechanism. A Python process lock is not the guarantee, and the lease alone is not either. A row that already matches the claim is left in place, and the claim is marked `landed`.

The message attributes are exactly `event_id`, `correlation_id`, `event_type`, and `store_id`, and each value matches the body. A missing attribute, an extra attribute, or a mismatched value is rejected and is not claimed.

The lander acknowledges a message only after a terminal outcome. Inserted, duplicate, and conflict are terminal because the claim already recorded the decision. A rejected message is written to `store_event_rejects` before it is acknowledged. If that write fails, the message is not acknowledged. This command is the day-0 analytics lander. It is not the Observer.

`POST /events` still does not publish. This path does not change inventory, write the Live Twin, or start the Observer.

## Consequences

- A fixture can be published, consumed, and queried. Replaying that event id returns duplicate and leaves one row. The correlation id is the same on the message and the row.
- Landing cost stays on the on-demand query allowance. No reservation and no streaming insert are added.
- Ordered publish uses the `us-central1` Pub/Sub endpoint. The topic storage policy rejects an ordering key sent to the global endpoint.
- The API still starts without Google Cloud credentials. ADR 0003 stays in force.
- `retailtwin-api` remains the runtime publisher from the foundation decision. This record does not grant that account BigQuery write, subscription pull, or Firestore access, and it does not create a key. The day-0 smoke command uses the operator's existing project credentials.
- `inventory_events` and `agent_actions` use the same envelope and stay empty until those event types are published. Product performance, simulation results, and the Observer remain later work.
- The claim document is the event-id owner across processes. The BigQuery job id for that claim's insert generation is the owner of the derived insert. A BigQuery insert that bypasses that job id can still add a row, because those tables have no unique key. The lander does not overwrite that row. The smoke check counts rows for the fixture event id.
- A rejected message is stored as a quarantine document before acknowledgement. That record is evidence for this lander. It does not start the Observer.
- Foundation gate #10 stays open. The claim ledger is not the Firestore Live Twin. Issue #6, Gemini, and Cloud Run are still required, and a store event does not yet start an investigation.
- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/63
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/7
- Supersedes:
- Superseded by:
