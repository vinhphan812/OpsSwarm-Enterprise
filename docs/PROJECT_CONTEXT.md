# RetailTwin AI — Project Context and Product Specification

> **Read this file first.** This document explains the product target: what RetailTwin AI is, why it exists, what problem it solves, and how the completed competition system is intended to behave. For what is actually implemented on `main` today, read `docs/CURRENT_STATUS.md` immediately after this file.

## 1. Executive summary

**RetailTwin AI — Context-Guarded Autonomous 3D Retail Digital Twin** is an autonomous retail-operations system built around a live 3D digital twin of a store.

The product is not a chatbot and the 3D scene is not decorative. The store is represented as machine-readable state: zones, shelves, slots, products, inventory, sales signals, promotions and operational constraints. An AI agent continuously observes events, detects business problems, investigates evidence, proposes alternatives, simulates them against a cloned Digital Twin, validates the selected decision through a deterministic **Decision Context Guard (DCG)**, applies an allowed action to the Live Twin, and verifies the result.

Canonical loop:

`OBSERVE → DETECT → INVESTIGATE → PLAN → SIMULATE → GUARD → ACT → VERIFY`

Short product definition:

> **RetailTwin AI = Store Data + 3D Digital Twin + Autonomous AI Agent + Simulation + Context-Guarded Execution.**

Tagline:

> **See the store. Understand the business. Optimize it with AI.**

## 2. The problem

Retail operations continuously change. A product can sell faster than expected, shelf stock can become insufficient even while backroom inventory is available, a high-performing SKU can have too few facings, a low-performing SKU can occupy valuable shelf space, or a promotion can create a localized demand spike.

Traditional dashboards are mostly observational: they tell a manager what happened. Chatbots are mostly reactive: a human must ask a question. Generic LLM agents introduce another risk: a decision may be reasonable when generated but become invalid seconds later because inventory, shelf state, promotion or another business context has changed.

RetailTwin AI addresses three gaps:

1. **From dashboard to autonomous operator** — the system reacts to store events without waiting for a prompt.
2. **From flat data to spatial operations** — AI actions are grounded in a 3D Digital Twin where products, shelves and slots are explicit entities.
3. **From AI suggestion to safe action** — every live action is simulated and then revalidated against current context immediately before commit.

## 3. Who would use it?

A real product could serve supermarket/store operators, retail operations teams, category managers, merchandising teams, inventory/replenishment teams and regional managers.

Example applications include shelf replenishment, planogram optimization, facings adjustment, promotion placement, stockout-risk reduction, operational what-if simulation, and auditable AI-assisted store management.

The competition prototype demonstrates these ideas using synthetic but realistic retail data. It is not intended to control a real physical store during the competition.

## 4. Flagship scenario: Weekend Demand Surge

This is the primary end-to-end scenario and should remain the first scenario implemented.

1. The store is running with **AUTOPILOT ON**.
2. Synthetic POS events show SKU P017 selling substantially faster than its baseline.
3. Pub/Sub emits/forwards the event; no human prompt is required.
4. Observer activates the autonomous workflow.
5. Investigator reads sales velocity, shelf inventory, backroom inventory, shelf allocation, forecast and relevant context.
6. The system diagnoses that total inventory is sufficient but shelf allocation is too small, creating stockout risk.
7. Planner generates bounded alternatives, for example:
   - A: replenish only;
   - B: increase facings + replenish;
   - C: relocate a lower-performing SKU + increase facings + replenish.
8. Each alternative is applied to a **Simulation Twin**, never directly to the Live Twin.
9. The simulator calculates quantitative KPI effects. Gemini may explain these values but must not invent them.
10. Planner selects a preferred trade-off.
11. DCG revalidates the decision against the current store context.
12. For the signature demo, the live context intentionally changes between planning and commit. DCG detects that the decision is stale and returns `REFRESH_REQUIRED`.
13. The agent automatically refreshes evidence, creates a new decision and re-simulates if required.
14. DCG validates the new decision and authorizes only the exact permitted actions.
15. Executor applies those actions to the Live Twin.
16. The 3D store visibly changes.
17. Verifier checks expected versus observed state/result and records the outcome.

The point of the scenario is not merely “AI moved a product.” It demonstrates **autonomy + simulation + stale-context protection + controlled execution + verification**.

## 5. Product modes

### Autopilot — primary competition mode
Events automatically trigger the AI control loop. Low-risk, policy-allowed actions may be committed after simulation and DCG validation. This is the primary demo.

### Copilot — secondary
A human can request analysis; AI proposes and simulates actions and a human can approve actions that policy marks as review-required.

### Manual — diagnostic
A user can inspect the 3D Twin and manipulate simulation state for testing. Manual mode must not create an unsafe bypass around Live Twin controls.

## 6. Core product principles

### Digital Twin owns truth
The LLM does not own inventory, product location, context version or KPI truth. Canonical state belongs to the Digital Twin and analytical services.

### Gemini decides WHAT and WHY
Gemini interprets evidence, forms bounded plans and explains trade-offs.

### Deterministic services calculate numbers
Forecasting, stockout risk, constraints and simulation KPI calculations are performed by code/models/services. Gemini must not fabricate quantitative impact.

### Simulate before live
A proposed operational change is first applied to an isolated Simulation Twin.

### Context guard before commit
The Decision Context Guard is deterministic server-side enforcement, not another LLM agent.

### Fail closed
If validity cannot be established, the system does not commit.

### No stale commit
A decision valid for context version N must not be applied after relevant context changes to N+1 without re-evaluation.

### Semantic preservation
An approved move/replenishment decision must not silently become a price or promotion change during translation/execution.

### Evidence, not chain-of-thought
The UI shows trigger, evidence, concise diagnosis, alternatives, selected plan, guard result, actions and verification. It never exposes hidden model chain-of-thought.

## 7. What is in scope for MVP-SAFE?

The minimum acceptable product contains:
- one 3D store;
- approximately 20–50 SKUs;
- Firestore-backed Live Twin;
- deterministic synthetic POS/inventory events;
- Gemini on Vertex AI;
- autonomous event trigger;
- real constrained tool calling;
- product move/facings/replenishment actions;
- isolated Simulation Twin;
- deterministic KPI evaluator;
- MVP Decision Context Guard;
- guarded Live Twin commit;
- visible 3D state change;
- cloud deployment.

A single Gemini orchestrator plus deterministic tools is sufficient. Multi-agent ADK specialization is optional until the core path is stable.

## 8. What is deliberately not required for MVP?

Do not block the critical path on photorealistic Blender assets, customer avatars, computer vision, sophisticated traffic simulation, advanced optimization solvers, Looker dashboards, Vertex AI Search, multi-agent complexity, or automatic rollback.

These are Competition-100 enhancements only after the Submission Gate is stable.

## 9. Success criteria

A judge or new developer should be able to observe this sequence:

`EVENT → AI → INVESTIGATE → SIMULATE → GUARD → LIVE 3D ACTION → VERIFY`

The strongest proof is the stale-context demonstration:
- decision generated for context N;
- relevant state changes to N+1;
- DCG blocks the old decision;
- agent refreshes/replans;
- new decision passes;
- exact authorized action is committed;
- 3D Live Twin changes;
- verifier confirms the result.

## 10. Project glossary

**Live Twin** — canonical current operational state.  
**Simulation Twin** — isolated clone/branch used for what-if actions.  
**Store Event** — POS/inventory/promotion/traffic signal that can trigger automation.  
**EvidenceBundle** — versioned facts used to justify a decision.  
**Decision** — structured plan tied to exact context/evidence.  
**DCG** — deterministic Decision Context Guard before live execution.  
**No-Stale-Commit** — invariant preventing execution against changed relevant context.  
**Commit authorization/token** — short-lived permission for an exact decision/action set.  
**Executor** — only component allowed to perform guarded live actions.  
**Verifier** — checks observed result after execution.  
**Agent Activity** — user-visible evidence/action timeline, not hidden reasoning.

## 11. Where to read next

1. `docs/CURRENT_STATUS.md` — current implementation, open integration work and gate status.
2. `docs/ARCHITECTURE.md` — target components, data flow, security and DCG.
3. `docs/DOMAIN_AND_DATA_MODEL.md` — target entities, schemas, events and actions.
4. `docs/IMPLEMENTATION_GUIDE.md` — role-by-role work and build order.
5. `docs/DEVELOPMENT_WORKFLOW.md` — branch/PR/verification rules.
6. `docs/DEMO_AND_ACCEPTANCE.md` — flagship demo and release gates.
7. `docs/adr/` — architecture decision log. Pull requests name the ADR they track.
8. GitHub Issues — executable work tickets and Definition of Done.
