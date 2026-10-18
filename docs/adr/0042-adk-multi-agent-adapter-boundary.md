# 0042. ADK multi-agent adapter boundary (preparatory stub)

Date: 2026-10-18

## Status

Proposed

## Context

Issue #21 asks for an optional Google ADK specialization of the
Observer / Investigator / Planner / Simulator / Verifier sub-agents,
while the deterministic tools, DCG, and the guarded Executor remain
authoritative. The single-orchestrator fallback stays behind a
feature flag and the provider-neutral `LlmProvider` path (ADR 0008,
ADR 0020) must keep working.

PR #254 (`feat(#21): Google ADK multi-agent specialization (optional)`)
landed a draft that assumed a fictitious `google.adk.orchestrator.Orchestrator`
interface and was rejected on review. The owner accepted it only as an
"explicitly renamed preparatory stub task, not as completion of #21".
Adding `google-adk` to the production lockfile and CI is gated on a
separate decision: the dependency is not part of this preparatory PR.

Two paths were considered for the next step:

- **Land the full integration in one PR.** It depends on pinning a real
  supported Google ADK release, wiring the orchestrator, and re-running
  the G06 evidence — 3–5 sub-PRs in their own right. Out of scope for a
  single-day PR.
- **Land the boundary stub only.** No `google-adk` import, no orchestrator
  change, no lockfile change. The dormant adapter sits behind the
  `LlmProvider` interface; activation is a future decision PR.

The audit (see `docs/CURRENT_STATUS.md` after merge) recommends the
boundary stub as the only realistic close-out for the day, leaving real
integration as 3–5 future sub-PRs.

## Decision

A new module `apps/api/retailtwin_api/llm/adk_adapter.py` introduces a
dormant `AdkLlmProvider`:

- Subclasses `LlmProvider`. `complete` raises `NotImplementedError`.
- `is_configured()` returns `False` while the stub ships.
- The class does not import `google.adk` and the file ships with no
  extra dependency. `pyproject.toml` and `uv.lock` are unchanged.

A helper `apps/api/retailtwin_api/llm/adk_register.py` exposes
`register_adk_provider()`:

- When the `ADK_ENABLED` environment variable is unset (default), the
  helper is a no-op — it does not touch the provider registry, so the
  canonical `fake` / `openai_compatible` / `vertex_gemini` adapters are
  the only ones the factory knows about.
- When `ADK_ENABLED=true` (or any truthy spelling), the helper calls
  `register_provider("adk_specialized", …, STANDARD_CAPABILITIES)` with a
  builder that returns the dormant `AdkLlmProvider`. The slot name is
  fixed; a future PR may replace the builder without renaming.

Activation is gated by the env var, **not** by `Settings`, because
`Settings` is the canonical process surface and ADK must not appear in
the production configuration contract today.

The orchestrator (`apps/api/retailtwin_api/agents/orchestrator/`) is
unchanged. The Tool Registry, Decision, Evidence, and DCG contracts are
unchanged. The production `LLM_PROVIDER=vertex_gemini` policy in
ADR 0020 is unchanged.

## Consequences

- **Backward compatible.** `ADK_ENABLED` defaults to false; the day-0
  Cloud Run revision and all local runs behave exactly as before. CI
  excludes the new code path so the merged main stays green.
- **No production coupling.** No `google-adk` import, no extra dependency,
  no orchestrator change. ADR 0020's "vertex_gemini on
  retailtwin-ai-511002 / us-central1" production invariant is preserved.
- **Fail closed.** A misconfigured rollout (someone sets
  `LLM_PROVIDER=adk_specialized` without `ADK_ENABLED`) raises
  `ConfigurationError("Unknown LLM provider")` from the factory, not a
  silent swap to the ADK path.
- **Future work.** The real integration is tracked separately:
  - **PR-R1** — pick a supported Google ADK release, pin it in `uv.lock`
    under an `adk` optional extra, and replace the dormant builder in
    `adk_register.py` with a real `Agent` / `App` wrapper.
  - **PR-R2** — wire the optional adapter into
    `AutonomousInvestigations` behind `Settings.adk_enabled` and
    `apps/api/retailtwin_api/main.py`.
  - **PR-R3** — re-run the full E2E with the flag on/off and compare
    `AgentActivityLog`, decisions, evidence, and DCG verdicts.
  - **PR-R4** — promote this ADR from Proposed to Accepted and update
    the orchestrator README to mention the optional ADK layer.
- **Issue #21 stays open.** This PR is preparatory; closing #21 requires
  the PR-R1…R4 follow-ups to ship. A new issue will be opened for the
  lockfile decision and the real integration.

- Pull request:
- Issue: #21
- Supersedes:
- Superseded by: