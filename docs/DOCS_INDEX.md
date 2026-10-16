# RetailTwin AI — Documentation Index

> Every document in the repository, with status, audience, and intended order of reading. Start with [README.md](../README.md) and the **Audiences** section below.

## Audiences

| Audience | Start here |
|---|---|
| Judge (3 minutes) | [README.md](../README.md) |
| Judge (deep dive) | [docs/COMPETITION_README.md](COMPETITION_README.md) |
| New developer (first day) | [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) → [CURRENT_STATUS.md](CURRENT_STATUS.md) → [ARCHITECTURE.md](ARCHITECTURE.md) → [DOMAIN_AND_DATA_MODEL.md](DOMAIN_AND_DATA_MODEL.md) → [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) → [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) |
| Reviewer of a pull request | [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) → [ARCHITECTURE.md](ARCHITECTURE.md) → [adr/README.md](adr/README.md) → relevant ADR(s) |
| Operator of the Cloud Run / Firebase stack | [CLOUD_RUNTIME_MATRIX.md](CLOUD_RUNTIME_MATRIX.md) → [deploy.md](deploy.md) → [deploy-web.md](deploy-web.md) → `../scripts/verify-cloud-preflight.sh` |
| Demo presenter | [DEMO_AND_ACCEPTANCE.md](DEMO_AND_ACCEPTANCE.md) → [DEMO_VIDEO.md](DEMO_VIDEO.md) → [demo-video/](demo-video/) |

## Top-level

| File | Audience | Status | Purpose |
|---|---|---|---|
| [README.md](../README.md) | Everyone | Stable | One-screen judge-facing overview. Problem, solution, architecture, flagship scenario, AI/Cloud usage, safety, setup, deployment, demo, limitations, and a short docs index. |
| [COMPETITION_README.md](COMPETITION_README.md) | Judge, technical reviewer | Stable | Long-form technical brief. Architecture deep dive with a Mermaid diagram, the 8-stage agent control loop walkthrough, storage layout, gate evidence index, and performance numbers. |

## Project documents

| File | Audience | Status | Purpose |
|---|---|---|---|
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | New developer, judge | Stable | The retail problem, product behaviour, scope, glossary. Read first. |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | New developer, reviewer | Living | Authoritative current maturity, work in progress, and release-gate status. Update whenever a gate changes or a major subsystem lands. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Reviewer, implementer | Stable (target) | Components, data flow, security, DCG, Live/Simulation boundary. Describes the target product; status is in CURRENT_STATUS.md. |
| [architecture/README.md](architecture/README.md) | Everyone | In flight (#46) | Canonical autonomous control loop diagram. Cross-referenced in README.md and COMPETITION_README.md. |
| [DOMAIN_AND_DATA_MODEL.md](DOMAIN_AND_DATA_MODEL.md) | Implementer | Stable | Store / Zone / Shelf / Slot / Product model, events, evidence, tools, actions, KPIs, Live/Simulation isolation. |
| [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) | New developer, role owner | Stable | Role-by-role work and the build phases. Cuts Competition-100 features when the core path is unstable. |
| [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) | Reviewer, implementer | Stable | Issue → branch → PR → ADR workflow, verification hierarchy, merge-safety rules, vocabulary for maturity. |
| [DEMO_AND_ACCEPTANCE.md](DEMO_AND_ACCEPTANCE.md) | Demo presenter, judge | Stable | Flagship scenario, 3-minute storyboard, stale-context acceptance, 20-run Submission Gate, failure tests, judge-visible evidence. |
| [CLOUD_RUNTIME_MATRIX.md](CLOUD_RUNTIME_MATRIX.md) | Operator, reviewer | Living | Canonical GCP/Firebase production configuration. Exact names, regions, IAM roles, environment variables, verification commands. The matrix Terraform #99 will codify. |
| [AGENT_TIMELINE.md](AGENT_TIMELINE.md) | Implementer | Stable (schema) | 9-stage Agent Activity schema. The mock timeline is no longer mounted; #94 fills the panel from `GET /agent/events`. |
| [DEMO_VIDEO.md](DEMO_VIDEO.md) | Demo presenter | Stable | Demo video overview, links to the runbook. |
| [deploy.md](deploy.md) | Operator | Stable | API deploy guide and token verification command. |
| [deploy-web.md](deploy-web.md) | Operator | Stable | Web deploy guide. |
| [DOCS_INDEX.md](DOCS_INDEX.md) | Everyone | Living | This file. |

## Demo and video

| File | Purpose |
|---|---|
| [demo/README.md](demo/README.md) | Demo index. |
| [DEMO_VIDEO.md](DEMO_VIDEO.md) | Demo video overview. |
| [demo-video/acceptance-criteria.md](demo-video/acceptance-criteria.md) | Acceptance criteria for the demo video. |
| [demo-video/production-checklist.md](demo-video/production-checklist.md) | Production checklist. |
| [demo-video/shot-list.md](demo-video/shot-list.md) | Shot list. |
| [competition/README.md](competition/README.md) | Competition folder index. |

## Architecture decision log (`docs/adr/`)

Every PR names the ADR it tracks. A change that makes a new architecture decision adds the next record in the same PR. A change that replaces an accepted decision adds a new record and marks the previous one `Superseded`. Do not rewrite accepted history.

### Foundation and runtime

| ADR | Title | Status | Issue / PR |
|---|---|---|---|
| [0001](adr/0001-record-architecture-decisions-in-pull-requests.md) | Record architecture decisions in pull requests | Accepted | — |
| [0002](adr/0002-render-store-entities-as-named-primitives.md) | Render store entities as named primitives | Accepted | — |
| [0003](adr/0003-serve-store-reads-through-the-api.md) | Serve store reads through the API | Accepted | — |
| [0004](adr/0004-keep-the-cloud-foundation-on-free-tier.md) | Keep the cloud foundation on the free tier | Accepted | — |
| [0005](adr/0005-land-each-normalized-store-event-once.md) | Land each normalized store event once | Accepted | — |
| [0006](adr/0006-use-heroui-v2-for-app-status-ui.md) | Use HeroUI v2 for app status UI | Accepted | — |
| [0007](adr/0007-keep-store-layout-static-until-the-twin-serves-geometry.md) | Keep the store layout static until the twin serves geometry | Accepted | — |
| [0008](adr/0008-provider-neutral-llm.md) | Provider-neutral LLM runtime | Accepted | — |
| [0020](adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md) | Register LLM providers and require Vertex ADC in production | Accepted | #136 / PR #178 |
| [0022](adr/0022-draw-demo-stock-with-glb-models.md) | Draw demo stock with GLB models, primitives as the fallback | Accepted | — |

### Agent control loop

| ADR | Title | Status | Issue / PR |
|---|---|---|---|
| [0009](adr/0009-expose-one-allow-listed-tool-registry.md) | Expose one allow-listed tool registry | Accepted | #11 / PR #119 |
| [0010](adr/0010-start-one-investigation-per-sale.md) | Start one investigation per sale | Accepted | #12 / PR #120, #122 |
| [0011](adr/0011-collect-versioned-evidence-from-the-tool-registry.md) | Collect versioned evidence from the tool registry | Accepted | #13 / PR #121, #123 |
| [0012](adr/0012-bind-candidate-plans-to-the-evidence-context.md) | Bind candidate plans to the evidence context | Accepted | #14 / PR #124, #155 |
| [0013](adr/0013-score-candidate-plans-on-a-simulation-clone.md) | Score candidate plans on a simulation clone | Accepted | #15 / PR #125, #161 |
| [0014](adr/0014-guard-each-decision-with-deterministic-gates.md) | Guard each decision with deterministic gates | Accepted | #16 / PR #138, #148 |
| [0015](adr/0015-recheck-live-versions-before-every-commit.md) | Recheck live versions before every commit | Accepted | #17 / PR #139, #149, #152 |
| [0016](adr/0016-commit-only-through-a-signed-single-use-authorization.md) | Commit only through a signed single-use authorization | Accepted | #18 / PR #141, #163, #166 |
| [0017](adr/0017-verify-post-action-state-by-rereading-live-inventory.md) | Verify post-action state by rereading live inventory | Accepted | #19 / PR #167 |
| [0018](adr/0018-refresh-evidence-and-replan-after-a-stale-rejection.md) | Refresh evidence and replan after a stale rejection | Accepted | #20 / PR #168 |
| [0019](adr/0019-record-agent-action-provenance-in-bigquery.md) | Record agent-action provenance in BigQuery | Accepted | #35 / PR #177 |
| [0021](adr/0021-require-one-gemini-inventory-read.md) | Require one Gemini inventory read | Accepted | #2 / PR #179 |
| [0023](adr/0023-start-investigations-from-accepted-sales.md) | Start investigations from accepted sales | Accepted | #50 / PR #199 |
| [0037](adr/0037-agent-activity-timeline.md) | Agent activity timeline | Accepted | #94 (in flight) |

### Authoring

| File | Purpose |
|---|---|
| [adr/README.md](adr/README.md) | Index, pull-request rule, file convention, status vocabulary. |
| [adr/template.md](adr/template.md) | Template for the next record. |

## How to update this index

When you add a new ADR, append a row to the right group above. When you add a new top-level document, add a row to **Project documents**. When you add a new audience for an existing document, add a row to **Audiences**. Keep the table sorted by file name within each group so the index is reproducible.
