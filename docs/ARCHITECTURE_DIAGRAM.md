# RetailTwin AI — Architecture Diagram

> **Purpose.** This document distills the canonical architecture of RetailTwin AI into four Mermaid diagrams. It is the **diagram half** of issue [#46](../README.md): one self-contained Mermaid block per layer, renderable on GitHub and in VS Code without extensions.
>
> **Audience.** Submission reviewers, new contributors, and judges who want a single-page map of the system before reading the deeper docs.
>
> **Authoritative sources.** All diagrams are derived from `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/DOMAIN_AND_DATA_MODEL.md`, `docs/CURRENT_STATUS.md`, `docs/CLOUD_RUNTIME_MATRIX.md`, and the ADRs in `docs/adr/`. When this file disagrees with those, the source docs win. See `docs/SUBMISSION_INDEX.md` for a quick pointer map.

---

## 1. System context — who talks to whom

This is the bird's-eye view: an external store event or operator command enters through the Google Cloud boundary, the RetailTwin AI control loop returns a guarded live mutation, and the 3D Twin surfaces the result.

```mermaid
flowchart TD
    classDef actor fill:#e6f0ff,stroke:#1f4e9a,stroke-width:1px
    classDef cloud fill:#fff7e0,stroke:#a25e00,stroke-width:1px
    classDef guard fill:#d9f7e8,stroke:#16794a,stroke-width:1px
    classDef twin fill:#ffe8d6,stroke:#c2410c,stroke-width:1px

    Customer[("Retail shopper<br/>synthetic POS event<br/>sale.completed")]


    Operator[/"Operator / reviewer<br/>human approval or<br/>Copilot prompt"/]


    subgraph GCP["Google Cloud — project retailtwin-ai-511002 / us-central1"]
      direction TB
      PubSub["Pub/Sub topic<br/>store-events"]
      CloudRun["Cloud Run service<br/>retailtwin-api<br/>(public invoker, WIF)"]
      Firestore["Firestore Native<br/>(default) — Live Twin"]
      BigQuery["BigQuery dataset<br/>retailtwin — sales_events /<br/>inventory_events /<br/>agent_actions / agent_action_audit"]
      Gemini["Vertex AI<br/>gemini-2.5-flash"]
      Storage["Cloud Storage<br/>retailtwin-ai-511002-assets<br/>(GLB models, fixtures)"]
    end

    subgraph Twin["RetailTwin AI control loop"]
      Observer[Observer]:::guard
      Investigator[Investigator]:::guard
      Planner[Planner]:::guard
      Simulator[Simulation Twin]:::guard
      DCG["Decision Context Guard<br/>No-Stale-Commit + signed token"]:::guard
      Executor[Guarded Executor]:::guard
      Verifier[Verifier]:::guard
    end

    subgraph Visual["3D Digital Twin"]
      Web["apps/web — React Three Fiber<br/>Live view, Simulation view,<br/>Agent Activity, DCG card"]
    end

    Customer -->|sale.completed| PubSub
    PubSub -->|pull: store-events-analytics| CloudRun
    Operator -->|approve / reject| Web
    Web -->|GET /store /agent/events| CloudRun

    CloudRun --> Observer --> Investigator --> Planner --> Simulator --> DCG
    DCG -->|ALLOW + signed token| Executor
    Executor -->|atomic commit,<br/>Firestore updateTime preconditions| Firestore
    Executor --> Verifier
    Verifier -->|AgentActivity row + observed row| BigQuery
    Firestore -->|GET /store diff every 5s| Web

    Planner -. "one get_inventory tool call<br/>functionCallingConfig.mode=ANY" .-> Gemini
    Gemini -. "structured decision JSON" .-> Planner

    Storage -. "GLB models + fixtures<br/>read-only" .-> Web
```

**Read it left-to-right**: a synthetic POS event enters Pub/Sub; the Cloud Run API consumes it through the seven-stage control loop; mutations are committed to Firestore only through the guarded Executor; BigQuery holds the audit trail; the 3D Twin reflects the Live state. The Gemini inference path is dotted because it is one constrained tool call, not a free-form chat.

---

## 2. End-to-end data flow — eight stages, one correlation id

Every autonomous run shares a single `correlation_id` from the originating `StoreEvent` so it can be traced end-to-end through logs, decisions, simulations, the guard audit, and the BigQuery trail.

```mermaid
flowchart TD
    classDef event fill:#eaf4fc,stroke:#3772a5
    classDef agent fill:#e9d5ff,stroke:#6b21a8
    classDef guarded fill:#d9f7e8,stroke:#16794a
    classDef twin fill:#ffe8d6,stroke:#c2410c
    classDef sink fill:#f5f5f5,stroke:#525252

    E1["sale.completed<br/>event_id=evt-000123<br/>correlation_id=run-20261007-001"]:::event
    E2["Pub/Sub message<br/>ordering_key=event_id<br/>attributes event_id, correlation_id,<br/>event_type, store_id"]:::event
    E3["Firestore<br/>store_event_claims/evt-000123<br/>idempotency ledger"]:::sink

    A1["Observer<br/>consumer.py<br/>ADR-0010"]:::agent
    A2["Investigator<br/>evidence.py<br/>ADR-0011"]:::agent
    A3["Planner<br/>plans.py<br/>ADR-0012"]:::agent
    A4["Simulation Twin<br/>branch.py + kpi<br/>ADRs-0013, formula simulation-kpi-v1"]:::agent

    G1["Decision Context Guard<br/>guard.py — six deterministic gates<br/>ADR-0014"]:::guarded
    G2["No-Stale-Commit<br/>no_stale_commit.py<br/>ADR-0015"]:::guarded
    G3["Signed single-use token<br/>authorization.py<br/>HMAC-SHA256, 30s TTL<br/>ADR-0016"]:::guarded

    X["Guarded Executor<br/>executor.py<br/>atomic commit<br/>Firestore updateTime precondition"]:::guarded
    V["Verifier<br/>verify.py<br/>re-reads touched SKUs<br/>ADR-0017"]:::guarded

    L1["Firestore Live Twin<br/>InventoryDocument v -> v+1<br/>PR-0106"]:::twin
    L2["3D Live view<br/>apps/web polls GET /store<br/>move / facings / replenishment cues"]:::twin

    R["replan.py<br/>refresh evidence + replan<br/>ADR-0018<br/>(on REFRESH_REQUIRED, bound 1)"]:::agent

    BQ["BigQuery agent_action_audit<br/>stages: trigger, evidence,<br/>decision, guard, execution, observed<br/>ADR-0019"]

    E1 --> E2
    E2 --> A1
    E1 --> E3
    A1 -->|start_investigation, no prompt| A2
    A2 -->|EvidenceBundle with<br/>entity_versions, is_sufficient| A3
    A3 -->|Decision candidates with<br/>context_version, kpi_score=-1.0| A4
    A4 -->|ScoredDecision with<br/>simulation_id, kpi_score| G1

    G1 --> G2
    G2 -->|CommitBinding<br/>entity_versions, expiry| G3
    G3 -->|SignedAuthorization<br/>HMAC, nonce, 30s| X
    X -->|commit_inventory<br/>all touched SKUs v -> v+1| L1
    X --> V
    V -->|VERIFIED or REGRESSION| BQ

    G1 -. REFRESH_REQUIRED .-> R
    R -. new EvidenceBundle, new context_version .-> A3
    R -. ALLOW + token .-> X

    L1 -->|GET /store diff| L2
    X -->|commit row| BQ
```

**Key invariants shown in the diagram**

- The simulator and DCG are the **only** paths into live state; Gemini never reaches Firestore directly.
- REFRESH_REQUIRED is the one signal that re-enters the loop; every other guard verdict ends the run.
- `kpi_score = -1.0` is the unscored sentinel until `simulation-kpi-v1` writes a real number.
- The Verifier never trusts the Executor's return value — it re-reads the Live Twin row by row.

---

## 3. Sequence diagram — one flagship run with eight stages

This is the signature run: a `sale.completed` triggers the agent, the Live Twin version moves between planning and commit, the Decision Context Guard (DCG) blocks the stale decision, the agent refreshes evidence and replans, the new decision passes, the guarded Executor commits, and the Verifier confirms the result.

```mermaid
sequenceDiagram
    autonumber
    participant POS as POS
    participant PS as Pub/Sub
    participant INV as Investigator
    participant PLN as Planner
    participant SIM as Simulation Twin
    participant GEM as Vertex Gemini
    participant DCG as Decision Context Guard
    participant EXE as Guarded Executor
    participant LT as Live Twin
    participant VRF as Verifier
    participant WEB as 3D Web

    POS->>PS: sale.completed event_id=evt-000123 correlation_id=run-001 store-001 sku=P017 qty=3
    PS->>INV: pull (subscription store-events-analytics)
    INV->>LT: get_inventory(P017) (read grant)
    LT-->>INV: shelf 8, backroom 54, version 981
    INV->>PLN: EvidenceBundle is_sufficient=true entity_versions={P017:981}
    PLN->>GEM: structured 2-3 candidates (JSON schema, no tools)
    GEM-->>PLN: candidates A: replenish +12 / B: facings 2->4 +12 / C: relocate + facings + replenish
    PLN->>SIM: simulate(candidates, simulation_id=sim-run-001)
    SIM-->>PLN: scored candidates kpi_score A=0.07 / B=0.12 / C=0.09
    Note over DCG,LT: Deliberate context mutation: P017 moves to version 982
    PLN->>DCG: submit Decision D1 (context_version=981)
    DCG->>LT: get_inventory(P017) (fresh)
    LT-->>DCG: shelf 8, backroom 54, version 982
    DCG-->>PLN: REFRESH_REQUIRED VERSION_STALE (No-Stale-Commit ADR-0015)
    PLN->>INV: refresh evidence (same correlation_id, new context_version=982)
    INV->>LT: get_inventory(P017) (read grant)
    LT-->>INV: shelf 7, backroom 53, version 982
    PLN->>GEM: structured candidates replan (run-001-r1 suffix)
    GEM-->>PLN: refreshed candidates D2
    PLN->>SIM: simulate(D2, simulation_id=sim-run-001-r1)
    SIM-->>DCG: ScoredDecision D2 for context 982 (kpi_score=0.12)
    DCG->>DCG: integrity / evidence / context / freshness / feasibility / policy (ADR-0014)
    DCG-->>EXE: ALLOW + SignedAuthorization (HMAC, 30s TTL, decision id, action hashes, live versions)
    EXE->>LT: redeem(token) -> recheck guard -> commit_inventory(facings 2->4, shelf+12, backroom-12)
    LT-->>EXE: P017 v983, store v+1 (atomic, Firestore updateTime precondition)
    EXE->>VRF: report transition (decision_id=D2, pre-commit snapshot, touched SKUs)
    VRF->>LT: re-read touched SKUs
    LT-->>VRF: P017 v983, expected row matches
    VRF-->>WEB: AgentActivityEntry stage=observed status=VERIFIED
    EXE-->>WEB: AgentActivityEntry stage=execution actions=[facings 2->4, shelf+12, backroom-12]
    WEB->>LT: poll GET /store every 5s
    LT-->>WEB: store snapshot with P017 v983
    WEB-->>POS: 3D shelf highlight + shelf +N, facings cue, history card
```

**Three reasons this diagram is the canonical one**

1. It shows the **stale branch live**: `REFRESH_REQUIRED` lands, a refresh is triggered without a human, and only D2 reaches the guarded commit.
2. It shows **why Gemini cannot write Live state**: the only model call (`structured candidates`) has no live tools; the only `Live Twin` write goes through `executor.commit_inventory` behind a signed token.
3. It shows **why the result is auditable**: every stage carries the same `correlation_id` and emits one BigQuery `agent_action_audit` row plus one `AgentActivityEntry` for judges.

---

## 4. Storage layout — Firestore, BigQuery, Pub/Sub

Operational state lives in Firestore, history in BigQuery, transport in Pub/Sub. Every mutable entity has a version and an `updated_at` so the DCG can detect staleness deterministically. See `docs/CLOUD_RUNTIME_MATRIX.md` for exact resource names.

```mermaid
flowchart LR
    classDef pubsub fill:#fde4d0,stroke:#a25e00
    classDef fs fill:#d6e4ff,stroke:#1f4e9a
    classDef bq fill:#d9f7e8,stroke:#16794a
    classDef bloom fill:#ffe8d6,stroke:#c2410c

    subgraph PS["Pub/Sub — us-central1"]
      direction TB
      T1["topic: store-events<br/>ordering: event_id<br/>attributes: event_id, correlation_id,<br/>event_type, store_id"]:::pubsub
      S1["pull subscription: store-events-analytics<br/>ack deadline 60s, 7d retention"]:::pubsub
    end

    subgraph FS["Firestore (default) — Live Twin + claims"]
      direction TB
      C1["collection: store_event_claims / {event_id}<br/>owner of event_id across processes<br/>status: claimed -> landing -> landed"]:::fs
      C2["collection: stores / {store_id}"]:::fs
      C3["collection: stores/{store_id}/zones / {zone_id}"]:::fs
      C4["collection: stores/{store_id}/shelves / {shelf_id}"]:::fs
      C5["collection: stores/{store_id}/slots / {slot_id}"]:::fs
      C6["collection: stores/{store_id}/inventory / {sku}<br/>version: int, updated_at, shelf_quantity,<br/>backroom_quantity, slot_id, facings"]:::fs
      C7["collection: stores/{store_id}/promotions / {promo_id}"]:::fs
      C8["collection: stores/{store_id}/simulations / {simulation_id}<br/>status: open / committed / rejected"]:::fs
    end

    subgraph BQ["BigQuery dataset retailtwin — us-central1"]
      direction TB
      T2["table: sales_events<br/>day-partitioned, cluster store_id, sku<br/>receives sale.completed"]:::bq
      T3["table: inventory_events<br/>receives inventory.*"]:::bq
      T4["table: agent_actions<br/>receives agent.*"]:::bq
      T5["table: agent_action_audit<br/>stages: trigger, evidence, decision,<br/>guard, execution, observed<br/>ADR-0019"]:::bq
    end

    subgraph Assets["Cloud Storage gs://retailtwin-ai-511002-assets"]
      direction TB
      G1["apps/web/public/models/<br/>snackies (low-poly GLB, 205 KB)<br/>kenney-food-kit (CC0)"]:::bloom
      G2["store fixture: data/schemas/store-state.example.json"]:::bloom
    end

    T1 -->|subscription pull| S1
    S1 -->|landed row once per event_id| T2
    S1 --> C1
    C1 --> T2

    C2 --- C3 --- C4 --- C5 --- C6
    C6 -->|"GET /store, every 5s"| WebApp(("3D web"))

    C6 -->|"atomic commit_inventory<br/>Firestore updateTime precondition"| C6
    C6 -->|"on commit"| T5
    C8 -->|"on approve / reject"| T5

    G1 -. read-only .-> WebApp
    G2 -. read-only .-> C2
```

**Two data-plane rules the diagram encodes**

- **Firestore owns truth.** BigQuery rows are an analytical projection keyed by `event_id`. A row that bypasses the Pub/Sub lander is not deleted; it is left in place, and the claim is marked `landed` (ADR 0005).
- **Mutable entities carry versions.** Every `inventory` document, the `stores` document, and every `simulation` document has a `version` integer and `updated_at`; the DCG refuses any action whose evidence version no longer matches the live read.

---

## 5. Reading order

1. `docs/SUBMISSION_INDEX.md` — one-page pointer map for judges.
2. `docs/PROJECT_CONTEXT.md` §4 — the **Weekend Demand Surge** scenario this whole architecture is shaped around.
3. `docs/ARCHITECTURE.md` — the narrative counterpart to this file (more prose, less pixel).
4. `docs/CURRENT_STATUS.md` — what is on `main` today vs what is the target architecture.
5. `docs/adr/` — every novel invariant is recorded as a `0001`-`0023` ADR (plus `0037` for the timeline).
