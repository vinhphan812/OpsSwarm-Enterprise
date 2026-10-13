# 0010. Start one investigation per new sale

Date: 2026-10-13

## Status

Accepted

## Context

Issue #12 needs a store event to start work without a person typing a prompt. ADR 0005 already lands each `sale.completed` once through subscription `store-events-analytics`. That lander acknowledges a message only after a terminal analytics outcome, and it does not start an investigation. The normalized event shape is the existing `StoreEvent`: `event_id`, `correlation_id`, `event_type`, `store_id`, `sku`, `quantity`, `occurred_at`, and `source`.

A second copy of the same payload must not start a second investigation. A different payload for the same `event_id` must not replace the first one. The handoff has to be recorded before the observer acknowledges the message, otherwise a crash after the start and before the ack would be indistinguishable from a message that was never handled.

Folding the observer into the analytics lander was set aside. That would make one ack serve two jobs and would change ADR 0005. Calling a model from the observer to decide whether the event matters was set aside. Issue #12 is event-driven, and the provider-neutral runtime stays behind the orchestrator that receives the handoff. Creating the production subscription in this change was set aside. Subscription `store-events-analytics` remains the lander's, and a shared pull would split messages between the two consumers. The observer accepts the existing `EventPipe` so the in-memory pipe can prove the rule, and a later subscription can supply that same pipe.

## Decision

The observer is a separate consumer in `apps/api/retailtwin_api/agents/observer/consumer.py`. It pulls one message at a time from an `EventPipe`.

A `sale.completed` event with matching attributes is reserved in a process-local activation ledger. The first reservation calls `start_investigation` with an `InvestigationStart`. That value carries `investigation_id` and the `StoreEvent`. It has no prompt. The investigation id is `inv-` plus the `event_id`. After `start_investigation` returns, the ledger commits the record as `started`, and only then does the observer acknowledge the message.

The same payload again is a `duplicate`. The observer acknowledges it and does not call `start_investigation`. A different payload for that `event_id` is a `conflict`. The stored event stays, no new investigation starts, and the message is acknowledged. If `start_investigation` raises, the pending reservation is removed and the message is not acknowledged.

Any other well-formed event type is acknowledged as `ignored` and does not start an investigation. An invalid body, an attribute mismatch, or an `event_id` the claim rules reject is quarantined and then acknowledged. If quarantine raises, the message is not acknowledged.

The ledger is not Live Twin state and it is not `store_event_claims`. The observer does not write the store. The analytics lander remains the consumer from ADR 0005.

## Consequences

A new `sale.completed` id can start one investigation when this consumer is run. Replaying that message does not start another. The orchestrator behind `start_investigation` must treat the same `investigation_id` as the same investigation, because a crash after the call and before the commit can deliver the event again while it is still `pending`.

The publisher in issue #30 still only publishes. It does not invoke this consumer. Foundation gate #10 stays open: this ledger is in-process, the live subscription is still `store-events-analytics`, and Gemini on Vertex remains issue #2. A production observer needs its own pull subscription on `store-events` before it can run beside the lander.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/120
- Issue: #12
- Supersedes:
- Superseded by:
