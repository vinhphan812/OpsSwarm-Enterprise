# RetailTwin AI — Submission Deck

> **Audience.** Submission reviewers and judges. Four sections map directly to the published scoring rubric: Technical 40%, Impact 25%, Innovation 25%, UX 10%. Each section carries three to five bullets, one evidence link, and one measurable number.
>
> **Companion files.** `docs/ARCHITECTURE_DIAGRAM.md` is the picture half of this submission; `docs/SUBMISSION_INDEX.md` is the one-page pointer map.
>
> **Tagline.** *See the store. Understand the business. Optimize it with AI.*

---

## Slide 1 — Title

- **RetailTwin AI** — Context-Guarded Autonomous 3D Retail Digital Twin.
- A store is machine-readable state (zones → shelves → slots → products); an AI agent observes, investigates, simulates, and only then acts on the Live Twin.
- Built on Google Cloud (Firestore + Pub/Sub + BigQuery + Cloud Run + Vertex AI) with Gemini `gemini-2.5-flash` as the planner and a deterministic Decision Context Guard as the safety boundary.
- **Evidence link.** `docs/PROJECT_CONTEXT.md` §1.
- **Measurable number.** 7-stage canonical loop `OBSERVE → INVESTIGATE → PLAN → SIMULATE → DCG → ACT → VERIFY` covers 100% of every autonomous action.

---

## Section A — Technical (40%)

> Single-orchestrator Gemini agent, deterministic guard, Firestore Live Twin, Cloud Run deployment.

- **Real Gemini tool calls**, not prose. `read_inventory` enforces one `get_inventory` call only — `functionCallingConfig.mode=ANY` with `allowedFunctionNames=[get_inventory]` — and the typed `ProductInventory` document is the result (`apps/api/retailtwin_api/agents/orchestrator/inventory_read.py`). The live call against `gemini-2.5-flash` on 2026-10-14 read `store-001 / P001` and matched the Firestore document byte-for-byte.
- **Provider-neutral LLM factory.** `create_provider` looks up `fake`, `openai_compatible`, and `vertex_gemini`; production accepts **only** `vertex_gemini` on `retailtwin-ai-511002` in `us-central1`, refuses a fake provider, refuses a loopback URL, and refuses `GEMINI_API_KEY`/`GOOGLE_API_KEY`. There is no fallback to the fake provider when a real adapter fails.
- **Firestore Live Twin boundary.** `LiveTwinRepository.commit_inventory` writes every touched SKU in one Firestore `:commit`, each document conditional on the `updateTime` the read returned. ADC auth on the Cloud Run service identity; no service-account keys.
- **Decision Context Guard — six deterministic gates.** integrity → evidence → context_version → freshness (default 120s) → physical feasibility → policy. Returns `ALLOW`, `DENY`, `REFRESH_REQUIRED`, or `HUMAN_REVIEW`. No model SDK is imported.
- **Guarded Executor + No-Stale-Commit.** The only Live Twin writer. A signed single-use token (HMAC-SHA256, default 30s TTL) binds the decision id, context hash, per-action SHA-256, live versions, and a 128-bit nonce; `recheck` runs the guard again immediately before the write.

**Evidence link.** [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) §3–§5 and ADRs [0014](adr/0014-guard-each-decision-with-deterministic-gates.md), [0015](adr/0015-recheck-live-versions-before-every-commit.md), [0016](adr/0016-commit-only-through-a-signed-single-use-authorization.md), [0020](adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md), [0021](adr/0021-require-one-gemini-inventory-read.md).

**Measurable number.** 6 DCG gates run in <1 ms in-process against the fixture Live Twin (`tests/e2e/gates/g04_guard_gate.py` exit 0 every run); commit token TTL defaults to **30 s** with `RETAILTWIN_COMMIT_TOKEN_TTL_SECONDS`.

---

## Section B — Impact (25%)

> Weekend Demand Surge scenario, measurable KPIs, ROI of agent-driven replenishment.

- **Single canonical flagship scenario: Weekend Demand Surge.** Synthetic POS events for `P017` send 50 units Friday and 73 units Saturday in matched 4-hour windows — a **+46%** velocity spike. The agent detects, investigates, plans, simulates, guards, commits, and verifies without a prompt.
- **Live agents, not dashboards.** `AUTONOMY_ENABLED=true` hands every accepted `sale.completed` to the Observer; investigator, planner, simulator, guard, Executor, and re-plan run without a human. Operators see the result on the 3D Live view and on the Agent Activity timeline.
- **Deterministic KPI scoring on a Simulation Twin.** `simulation-kpi-v1` returns stockout risk, service level, movement cost, and a normalized business score in [-2, 2] for each candidate. The same actions always return the same score; the model never invents KPI numbers.
- **Auditable agent action trail.** `record_trace` appends one `trigger`, `evidence`, `decision`, `guard`, `execution`, and `observed` row to `retailtwin.agent_action_audit` per `correlation_id`; `-1.0` is the documented unscored sentinel until simulation scores the candidate.
- **Deployed on Google Cloud at zero incremental cost.** Project `retailtwin-ai-511002` stays inside the always-free tier: ~1 USD/month budget (`retailtwin-dev-guard`) with 50/90/100% alerts. Runtime evidence verified by `./scripts/verify-cloud-preflight.sh` (read-only).

**Evidence link.** [`docs/DEMO_AND_ACCEPTANCE.md`](../DEMO_AND_ACCEPTANCE.md) §8 (sequence diagram of the stale-context-protected weekend surge) and [`docs/CURRENT_STATUS.md`](../CURRENT_STATUS.md) "Weekend Demand Surge fixture" line.

**Measurable number.** The P017 weekend series forecasts **73 units (≈18.25 per hour)**, direction up from Friday's 50; the deterministic stockout-risk service over a 4-hour horizon raises the rate only when evidence supports it (`services/forecasting/demand` and `services/forecasting/risk`).

---

## Section C — Innovation (25%)

> No-Stale-Commit, durable cross-instance agent pipeline, fail-closed composition root.

- **No-Stale-Commit invariant.** A decision valid for context version `N` can never reach Live Twin at `N+1` without revalidation. `NoStaleCommit.recheck` runs the guard on fresh reads, returns `REFRESH_REQUIRED VERSION_STALE` on a touched SKU move, returns `DENY BINDING_MISMATCH` on a hash change, and `REFRESH_REQUIRED CONTEXT_EXPIRED` past the binding expiry. The Executor's atomic Firestore commit uses `updateTime` preconditions so the race between recheck and write is closed at the database boundary.
- **Durable cross-instance agent pipeline.** Each `event_id` is owned by `store_event_claims/{event_id}` in Firestore; landing uses one BigQuery job id for the claim's `insert_generation`, so two replicas pick the same job and never insert the same row twice. The pull subscription `store-events-analytics` is the analytics lander; the Observer can attach its own pull subscription without changing ADR 0005.
- **Fail-closed composition root.** Agent code depends only on `LlmProvider`, `ToolRegistry`, `LiveTwinRepository`, and an injected clock. Adding an LLM adapter is `register_provider(...)`; nothing inside the planner, investigator, or guard branches on a vendor. In production the composition root rejects a fake adapter, a loopback URL, and a Gemini or Google API key — and there is no fallback to the fake provider when a real adapter fails.
- **Allow-listed tool registry with capability gates.** `READ`, `SIMULATION`, `COMMIT_REQUEST` are explicit capabilities; live-write tool names are refused in any case (in any letter case). Analytical tools (`forecast_demand`, `stockout_risk`, `compare_scenarios`, `calculate_business_impact`) stay dark until a deterministic port is bound, so the model cannot invent a KPI number.
- **Signed single-use commit authorization.** HMAC-SHA256 token carries decision id, context hash, per-action SHA-256, live versions, 128-bit nonce, and expiry. `MISSING_TOKEN`, `INVALID_SIGNATURE`, `TOKEN_EXPIRED`, `ACTION_MISMATCH`, `TOKEN_REUSED`, `UNKNOWN_TOKEN` each leave Live Twin unchanged.

**Evidence link.** [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) §4 (No-Stale-Commit) and ADRs [0008](adr/0008-provider-neutral-llm.md), [0014](adr/0014-guard-each-decision-with-deterministic-gates.md), [0015](adr/0015-recheck-live-versions-before-every-commit.md), [0016](adr/0016-commit-only-through-a-signed-single-use-authorization.md), [0018](adr/0018-refresh-evidence-and-replan-after-a-stale-rejection.md), [0020](adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md).

**Measurable number.** A guarded commit binding expires **30 seconds** after issue (`RETAILTWIN_COMMIT_TOKEN_TTL_SECONDS`, default 30); context staleness detection `REFRESH_REQUIRED` is bounded to **1** retry cycle (`RETAILTWIN_REPLAN_MAX_REFRESHES`, default 1, 0 allowed).

---

## Section D — User experience (10%)

> 3D cues, DCG card, live twin vs simulation twin views.

- **One 3D store, two unambiguous views.** The web app uses React Three Fiber 8 + Three.js + Drei, with `name` and `userData.entityId` for stable scene IDs and orbit-only camera interaction. `?twin=memory|demo` switches the canvas between Live and Simulation; the bound state diff reads from the same `twin.store`, so every cue works in both views and the Simulation view plays the move back when the proposal is left.
- **Three spatial cues judges can see.** **Move** — items hop from source to destination slot with a glow hand-over and the card saying "moved from A01-S02". **Facings** — capped at slot capacity, overflow flagged, change on the slot. **Replenishment** — `Shelf +N / Backroom -N` on the product card and details dialog; the shelf gain glows; inconsistent backroom→shelf transfer is flagged `inconsistentTransfer`; shelf units past facings show `+N not shown`.
- **Agent Activity timeline — eight evidence rows, zero chain-of-thought.** Stage rows (`trigger`, `evidence`, `decision`, `guard`, `execution`, `observed`) tied to the run's `correlation_id` and the Agent Activity panel's `run.store`. No hidden LLM CoT is stored or rendered; quantitative claims come from code/model output.
- **DCG card.** Renders `policy_result.checks` (one `{gate, passed, detail}` per gate that ran) plus the verdict (`ALLOW` / `DENY` / `REFRESH_REQUIRED` / `HUMAN_REVIEW`) and the `context_hash`. No raw token text is shown; only the structured guard result.
- **GLB stock models behind a primitive fallback.** Snackies and Kenney's Food Kit (`apps/web/public/models/`) replace the colored boxes and balls at zero regression to load or frame rate; `?assets=primitive` toggles back.

**Evidence link.** [`docs/AGENT_TIMELINE.md`](../AGENT_TIMELINE.md) and [`docs/CURRENT_STATUS.md`](../CURRENT_STATUS.md) "3D move cue", "3D facings cue", "3D replenishment cue" lines; ADR [0022](adr/0022-draw-demo-stock-with-glb-models.md).

**Measurable number.** **3** load-balanced spatial cues (move / facings / replenishment), one DCG card surface, and **2** Twin views (Live and Simulation) cover the competition UX; the 3D scene polls `GET /store` every **5 s** with exponential backoff to **60 s** on read failure.

---

## Slide — Closing

> *RetailTwin AI does not just let AI manage a store. It ensures every autonomous action is still valid at the exact moment it reaches the live store.*

One canonical path. One deterministic guard. One signed token. One auditable trail. Build on `main`. Demo on the published flagship scenario. Submit when G04 and G05 pass back-to-back.
