# Google Cloud AI Builder Cup 2026 — Competition Context

RetailTwin AI is being built as a submission for the **Google Cloud AI Builder Cup 2026**, under the **Retail & Commerce — Intelligent Customer and Business Experiences** challenge area.

## Competition positioning

**RetailTwin AI — Context-Guarded Autonomous 3D Retail Digital Twin**

The submission is intentionally positioned as an autonomous retail-operations system, not a chatbot and not a decorative 3D dashboard.

Core judge-visible story:

```text
EVENT → AI → INVESTIGATE → SIMULATE → GUARD → LIVE 3D ACTION → VERIFY
```

The technical differentiator is the **Decision Context Guard (DCG)** and **No-Stale-Commit** behavior: a decision is bound to the context that justified it and is revalidated immediately before a live action. A stale decision must fail closed.

## Scoring alignment

- **Technical merit / GenAI implementation:** Gemini on Vertex AI performs evidence-grounded planning through constrained tools; deterministic services own state, simulation numbers and guard decisions.
- **Problem alignment / impact:** reduce stockout risk and improve shelf/replenishment decisions while keeping autonomous actions controlled and auditable.
- **Innovation / creativity:** combine an operational 3D Digital Twin, autonomous event-driven agent loop, Simulation-before-Live, and context-guarded execution.
- **UX / solution design:** show the store, trigger, evidence, alternatives, guard outcome, live action and verification in one understandable workflow.

## Submission artifacts

The final package is expected to include:
- a deployed working application URL;
- a public GitHub repository when required for submission;
- an English demo video within the competition duration limit;
- presentation/deck material;
- clear evidence of meaningful Google AI and Google Cloud usage;
- reproducible setup and demo instructions;
- no committed credentials or secrets.

Before final submission, re-check the official competition site/terms because dates and submission details may change.

## Internal acceptance standard

Submission readiness is stricter than “the demo works once.” The flagship Weekend Demand Surge scenario must prove:
1. autonomous event activation without a user prompt;
2. Gemini reasoning over real tool-returned evidence;
3. isolated Simulation Twin changes before Live;
4. deterministic KPI evaluation;
5. intentional stale-context rejection;
6. automatic evidence refresh/re-plan;
7. DCG-authorized live commit;
8. visible 3D state change;
9. post-action verification;
10. 20 consecutive reproducible E2E PASS runs for G06.

See `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/DEMO_AND_ACCEPTANCE.md`, and `docs/CURRENT_STATUS.md`.
