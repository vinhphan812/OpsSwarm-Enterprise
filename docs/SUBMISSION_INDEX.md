# RetailTwin AI — Submission Index

> **One-page pointer map for issue [#46](https://github.com/vinhphan812/retailtwin-ai/issues/46).** This document links the new submission artifacts (diagram, deck, index) to the existing project documentation. Judges and new contributors should start here.
>
> **Provenance.** All numbers, claims and code paths in `docs/SUBMISSION_DECK.md` and `docs/ARCHITECTURE_DIAGRAM.md` trace back to one of the sources listed below. When this file disagrees with a deeper doc, the deeper doc wins.

---

## 1. Submission artifacts (this issue)

| File | Role | Rendered with |
| --- | --- | --- |
| [`docs/ARCHITECTURE_DIAGRAM.md`](ARCHITECTURE_DIAGRAM.md) | Four self-contained Mermaid diagrams: system context, end-to-end data flow, flagship sequence diagram (eight stages), Firestore/BigQuery/Pub/Sub storage layout. | GitHub markdown viewer (and VS Code preview) — no extensions required. |
| [`docs/SUBMISSION_DECK.md`](SUBMISSION_DECK.md) | Four-section deck aligned to the published scoring rubric: Technical 40%, Impact 25%, Innovation 25%, UX 10%. Each section has 3–5 bullets, one evidence link, one measurable number. | Any markdown reader; intended for live presentation. |
| [`docs/SUBMISSION_INDEX.md`](SUBMISSION_INDEX.md) | This file — one-page map between the new artifacts and the existing ADRs / day-0 gate / status report. | GitHub markdown viewer. |

---

## 2. Architecture decision records — the novel parts

The ADRs below record the architecture decisions that reviewers will most often ask about. ADRs `0001`–`0023` plus `0037` are merged on `main`; the submission does **not** add new records in this issue — every ADR hyperlink below points to the merged source of truth.

| ADR | Decision | Read it for | Cited in deck section |
| --- | --- | --- | --- |
| [0008](adr/0008-provider-neutral-llm.md) | Provider-neutral LLM runtime (`LlmProvider` contract). | Why the agent code never imports a model SDK. | Innovation |
| [0014](adr/0014-guard-each-decision-with-deterministic-gates.md) | Six-gate Decision Context Guard; deterministic, no model SDK. | Why `ALLOW` / `DENY` / `REFRESH_REQUIRED` / `HUMAN_REVIEW` are code, not model verdicts. | Technical, Innovation |
| [0015](adr/0015-recheck-live-versions-before-every-commit.md) | No-Stale-Commit — `NoStaleCommit.authorize` / `recheck` with `CommitBinding` (entity_versions, expiry). | Why a decision valid at version `N` cannot reach Live at `N+1`. | Technical, Innovation |
| [0016](adr/0016-commit-only-through-a-signed-single-use-authorization.md) | Signed single-use `CommitAuthorization` (HMAC-SHA256, nonce, 30s TTL) + Executor is the only Live Twin writer. | Why the agent cannot paste its own commit through. | Technical, Innovation |
| [0017](adr/0017-verify-post-action-state-by-rereading-live-inventory.md) | Verifier re-reads each touched SKU and compares against the expected transition (`replenish_shelf`, `change_facings`, `move_product`). | Why "the response said success" is not the success criterion. | Technical |
| [0018](adr/0018-refresh-evidence-and-replan-after-a-stale-rejection.md) | `replan` reuses the same provider; `REFRESH_REQUIRED` discards the binding and replans at `RETAILTWIN_REPLAN_MAX_REFRESHES` (default 1). | How the autonomous run recovers without a human. | Innovation |
| [0019](adr/0019-record-agent-action-provenance-in-bigquery.md) | `retailtwin.agent_action_audit` carries one row per stage per `correlation_id`. | Where the audit trail lives and why `-1.0` is the unscored sentinel. | Impact, Innovation |
| [0020](adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md) | `create_provider` looks up registered builders; production accepts only `vertex_gemini`, refuses fake / loopback / API keys. | The fail-closed composition root. | Technical, Innovation |
| [0021](adr/0021-require-one-gemini-inventory-read.md) | One `get_inventory` tool call with `functionCallingConfig.mode=ANY` + `allowedFunctionNames`. | Why the read is typed Live data, not model prose. | Technical, Impact |
| [0022](adr/0022-draw-demo-stock-with-glb-models.md) | GLB stock models behind a primitive fallback. | How the 3D store stops looking like boxes and balls. | UX |
| [0023](adr/0023-start-investigations-from-accepted-sales.md) | `POST /events` hands `sale.completed` to the Observer through a process-memory pipe. | Why no human prompt is needed. | Impact |
| [0037](adr/0037-agent-activity-timeline.md) | Agent Activity timeline (proposed) — eight evidence rows, zero chain-of-thought. | What the judges see on the right panel. | UX |

> **Note on ADR numbering.** Issue #46's source text referenced ADRs `0024`–`0029`; these IDs are not yet assigned. The intent of those references — evidence for the novel architectural claims — is served by ADRs `0014`–`0021` listed above. New ADRs are added by the work that introduces the change; this issue adds documentation only.

---

## 3. Day-0 gate evidence

The submission uses the day-0 foundation already on `main`. Reviewers reproduce it with one script:

| Artifact | What it proves | Reproduce with |
| --- | --- | --- |
| [`scripts/verify-cloud-preflight.sh`](../scripts/verify-cloud-preflight.sh) | Cloud Run service, Firestore database, Pub/Sub topic/subscription, BigQuery dataset/tables, Vertex AI model `gemini-2.5-flash`, two runtime service accounts, WIF pool/provider, Firebase Hosting site, CORS allow-list. Read-only. | `./scripts/verify-cloud-preflight.sh` (exit 0 = all checks passed). |
| [`tests/e2e/gates/g03_autonomous_gate.py`](../tests/e2e/gates/g03_autonomous_gate.py) | One accepted `sale.completed` starts an investigation, plans a candidate, records the proposal for the approve route; the Live Twin is unchanged. | `cd apps/api && pytest tests/e2e/test_g03_autonomous_gate.py`. |
| [`tests/e2e/gates/g04_guard_gate.py`](../tests/e2e/gates/g04_guard_gate.py) | A stale decision is refused; Live Twin is unchanged; `replan` then issues a fresh decision at `N+1`. | `cd apps/api && python tests/e2e/gates/g04_guard_gate.py --out g04-evidence.json` (exit 0 = PASS). |
| [`tests/e2e/gates/g05_live_commit_gate.py`](../tests/e2e/gates/g05_live_commit_gate.py) | A valid guarded decision is committed through the signed authorization; the Verifier re-reads every touched SKU; Live Twin shows the committed transition. | `cd apps/api && python tests/e2e/gates/g05_live_commit_gate.py --out g05-evidence.json` (exit 0 = PASS). |
| [`tests/e2e/test_canonical_path.py`](../tests/e2e/test_canonical_path.py), `test_failure_diagnostics.py`, `test_stale_context.py`, `test_simulation_live_isolation.py` | Behavior coverage of the headline stages. | `cd apps/api && pytest tests/e2e/`. |

> **Note.** The issue text referenced `scripts/verify-day0-gate.sh` and `artifacts/day0-foundation`; those paths are not present on `main`. The canonical day-0 evidence is the preflight verifier + the three `tests/e2e/gates/` harnesses listed above; gates `g03` / `g04` / `g05` are run by `scripts/record_demo_video.sh` and are wired into CI.

---

## 4. Implementation ownership map

The repository has three merged slices on `main`; this section records where each piece of the submission lives in the source tree.

```text
apps/api/retailtwin_api/
├── llm/                           Provider-neutral LLM runtime + Vertex adapter (ADRs 0008, 0020)
│   ├── contracts.py               LlmProvider interface, capability flags
│   ├── factory.py                 create_provider, fail-closed production rules
│   ├── vertex.py                  Vertex adapter maps required_tool -> functionCallingConfig.mode=ANY
│   ├── openai_compatible.py
│   └── fake.py                    FakeLlmProvider for CI and gates
├── agents/
│   ├── observer/consumer.py       One investigation per accepted sale (ADR 0010)
│   ├── investigator/evidence.py   Versioned EvidenceBundle (ADR 0011)
│   ├── planner/plans.py           Structured decisions bound to evidence (ADR 0012)
│   ├── simulator/branch.py        Score candidates on a clone (ADR 0013)
│   ├── executor/executor.py       GuardedExecutor — only Live Twin writer (ADR 0016)
│   ├── verifier/verify.py         Post-action re-read (ADR 0017)
│   └── orchestrator/
│       ├── tool_registry.py       Allow-listed registry with capability gates (ADR 0009)
│       ├── inventory_read.py      One Gemini tool call (ADR 0021)
│       ├── autonomy.py            AutonomousInvestigations (ADR 0023)
│       └── replan.py              REFRESH_REQUIRED recovery (ADR 0018)
├── guard/decision_context_guard/
│   ├── guard.py                   Six deterministic gates (ADR 0014)
│   ├── no_stale_commit.py         Recheck + CommitBinding (ADR 0015)
│   └── authorization.py           Signed single-use token (ADR 0016)
├── audit/trail.py                 agent_action_audit row writer (ADR 0019)
├── firestore_twin.py              Firestore Live Twin boundary (atomic commit_inventory)
└── routes.py                      GET /store / /health / /ready, POST /events, etc.

apps/web/src/                      React Three Fiber 8, three spatial cues (PR #115, #116, #117)
└── state/twin.store.ts            Bound 3D state diff → Live and Simulation views

services/simulation/kpi/           simulation-kpi-v1 evaluator (stockout_risk, service_level,
                                   movement_cost, business_score; normalized [-2, 2])
services/forecasting/demand        Deterministic demand forecast fallback for issue #31
services/forecasting/risk          Deterministic stockout-risk service for issue #32

infrastructure/gcp/                Terraform-free baseline (project, APIs, IAM, budget)
                                   ownership codified by #99
scripts/                           Read-only verifiers and demo helpers
data/schemas/                      JSON schemas for events, decisions, store state
tests/e2e/gates/                   G03, G04, G05 evidence harnesses
tests/e2e/                         Behavior coverage (canonical path, failure diagnostics,
                                   stale context, simulation/live isolation)
```

---

## 5. Current status pointers

The submission rhetoric lives in `docs/SUBMISSION_DECK.md`; the implementation maturity lives here:

- [`docs/CURRENT_STATUS.md`](CURRENT_STATUS.md) — what's on `main` vs target architecture; gate status (Foundation #10, G02–G06 all NOT PASSED until evidence is captured).
- [`docs/PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) §1 — canonical loop and product definition.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — narrative counterpart to the diagram.
- [`docs/DOMAIN_AND_DATA_MODEL.md`](DOMAIN_AND_DATA_MODEL.md) — entities, events, evidence, KPIs.
- [`docs/CLOUD_RUNTIME_MATRIX.md`](CLOUD_RUNTIME_MATRIX.md) — canonical GCP/Firebase identifiers.
- [`docs/DEMO_AND_ACCEPTANCE.md`](DEMO_AND_ACCEPTANCE.md) — flagship scenario and gate acceptance criteria.
- [`docs/AGENT_TIMELINE.md`](AGENT_TIMELINE.md) — eight-stage timeline contract.

---

## 6. Quality gates for this PR

- No source-code changes; tests should pass unchanged.
- All Mermaid blocks use `flowchart TD` / `flowchart LR` / `sequenceDiagram` syntax; no HTML-only constructs; no secrets.
- Three new files only: `docs/ARCHITECTURE_DIAGRAM.md`, `docs/SUBMISSION_DECK.md`, `docs/SUBMISSION_INDEX.md`.

---

## 7. Caveats and known follow-ups

- ADRs `0024`–`0029` named in issue #46 do not exist on `main`; the intent of those references is served by ADRs `0014`–`0021` listed above.
- `scripts/verify-day0-gate.sh` and `artifacts/day0-foundation` named in issue #46 do not exist on `main`; the canonical Day-0 evidence pointer is `scripts/verify-cloud-preflight.sh` plus the `tests/e2e/gates/` harnesses.
- Gates G02–G06 and Foundation #10 are still NOT PASSED in `docs/CURRENT_STATUS.md`; this PR is documentation only and does not change gate state.
