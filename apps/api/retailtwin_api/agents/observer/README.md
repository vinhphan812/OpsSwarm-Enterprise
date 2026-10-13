# Observer

ADR 0010. This consumer turns a new `sale.completed` event into one investigation. It does not ask for a prompt, does not call a model, and does not write the Live Twin.

The analytics lander on `store-events-analytics` is a different consumer. It still acknowledges its own messages and does not start an investigation. This observer pulls from an `EventPipe`. A production run needs its own pull subscription so the two consumers do not share one ack.

## Outcomes

| Outcome | When | Investigation |
| --- | --- | --- |
| `started` | First `sale.completed` for an `event_id` | `start_investigation` is called, then the activation is committed, then the message is acknowledged |
| `duplicate` | Same payload after that commit | Acknowledged, not started again |
| `conflict` | Different payload for that `event_id` | The stored event stays. Acknowledged, not started again |
| `ignored` | Any other well-formed event type | Acknowledged, not started |
| `rejected` | Invalid body, attribute mismatch, or an `event_id` the claim rules reject | Quarantined, then acknowledged |

If `start_investigation` raises, the pending activation is removed and the message is not acknowledged. If quarantine raises, the message is not acknowledged.

`InvestigationStart` carries `investigation_id` (`inv-` plus `event_id`) and the `StoreEvent`, including `correlation_id`. It has no prompt.

The activation ledger is process memory. It is not `store_event_claims` and it is not the Live Twin. The Weekend Demand Surge publisher still only publishes. Running this consumer over that series starts one investigation per new event id, and a replay does not add more.
