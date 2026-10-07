# RetailTwin AI — Development and Review Workflow

## Source of truth

`main` is the integration baseline. An open pull request is not treated as implemented product behavior until it is merged and verified.

Before coding, read `docs/PROJECT_CONTEXT.md`, `docs/CURRENT_STATUS.md`, `docs/ARCHITECTURE.md`, `docs/DOMAIN_AND_DATA_MODEL.md`, relevant accepted ADRs, and the assigned GitHub issue/dependencies.

## Issue → branch → PR

Each implementation should:
- start from current `main`;
- address one clear issue/outcome;
- preserve the issue Definition of Done;
- add tests for success and important failure paths;
- update docs/ADR when contracts or invariants change;
- open a PR that references the issue and verification evidence.

Avoid long-lived feature branches from stale `main`. Reconcile current `main` before final review when parallel work changed shared files.

## Architecture Decision Records

Every PR names the ADR it follows or writes `N/A` with a reason.

Add/supersede an ADR when changing public schemas, control-loop state transitions, tool/action contracts, Live-vs-Simulation mutation boundaries, DCG/security invariants, storage/execution boundaries, or another decision future contributors would otherwise reopen.

Do not rewrite accepted history. Supersede it.

## Verification hierarchy

A change is not complete because code exists. Evidence should progress through:
1. unit tests;
2. component/service integration tests;
3. clean install/build;
4. cross-component smoke test;
5. release-gate evidence where applicable.

For web work, reproducible installation and CI are tracked by #58. For the autonomous product path, gate issues #10 and #49–#53 are authoritative.

## Merge safety

Before merging:
- reconcile the branch with current `main`;
- resolve review findings;
- pass relevant tests/builds;
- commit no secrets;
- preserve Live/Simulation boundaries;
- update documentation for changed behavior;
- preserve the ADR index when parallel PRs add records.

Parallel PRs touching `README.md`, `.gitignore`, `apps/web`, or `docs/adr/README.md` require explicit conflict review.

## Vocabulary for maturity

- **implemented:** merged on `main`;
- **in progress:** open PR;
- **planned/target:** documented or ticketed only;
- **verified:** evidence exists for the stated level;
- **gate passed:** corresponding gate issue is intentionally closed with evidence.

Never describe target architecture as already deployed.

## Competition stability rule

Do not add Competition-100 work while the core path is unstable. Preserve:

```text
Autonomous Trigger
→ Real Gemini Tool Use
→ Simulation Before Live
→ DCG / No-Stale-Commit
→ Guarded Live 3D Action
→ Verification
```

Optional sophistication must not weaken this path.
