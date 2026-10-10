# ADR 0037: Agent Activity Timeline Implementation

## Status
Proposed

## Context
We need to provide transparency into how agents solve tasks, moving beyond opaque black-box execution to an observable, 9-stage timeline.

## Decision
We will implement an MVP timeline using a typed mock data source. The architecture will leverage a swappable `IAgentEventStore` interface.

## Alternatives Considered
1. **Direct API Polling**: Rejected because of tight coupling and potential performance overhead.
2. **WebSocket Stream**: Deferred. While optimal for real-time observability, it introduces significant complexity for the MVP phase.

## Provenance Rules
- IDs must originate from deterministic, traceable sources.
- Agent summaries must be generated securely.
- No LLM Chain-of-Thought (CoT) artifacts shall be exposed in the UI.
