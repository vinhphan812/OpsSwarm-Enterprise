# 0018. Refresh evidence and replan after a stale rejection

Date: 2026-10-14

## Status

Accepted

## Context

Issue #20 requires that a `REFRESH_REQUIRED` verdict is not the end of an autonomous run. Blocking the stale decision is ADR 0015. The operator still has to collect current evidence and authorize a new decision, without a person prompting the next step. Issue #85 requires that refresh to call the same provider-neutral investigator and planner. The configured provider is injected. The orchestration must not branch on which vendor that provider talks to.

The simulator that scores a plan is still issue #15 and is not on this branch. Recomputing the #33 KPI here would be a second formula. Calling the unmerged simulator package would couple this loop to a pull request that is still open. A missing score is not a reason to skip the guard: ADR 0012 leaves `kpi_score` at `-1.0` until a scorer runs, and the guard does not read that field.

Retrying the model until it sounds more confident was set aside. A provider failure is not a live action, and it must not be counted as another commit attempt. Reusing the `CommitBinding` from the rejected decision was set aside: ADR 0015 returns a binding only on `ALLOW`, and a later `REFRESH_REQUIRED` means that binding is finished. Writing the Live Twin from this module was set aside: ADR 0016 keeps that write on the guarded Executor.

## Decision

`replan` in `apps/api/retailtwin_api/agents/orchestrator/replan.py` takes the current `Decision`, the original `InvestigationStart`, one `LlmProvider`, the tool registry, a `NoStaleCommit` authorizer, and a context-version source.

It authorizes that decision. `ALLOW` is rechecked. Only a recheck that is still `ALLOW` is passed, with the binding from that authorization, to an injected commit port. The port is the only path toward a live write. This module does not issue a commit token and does not write the Live Twin.

`DENY` tries the next candidate from the same refresh, then stops when none remain. `HUMAN_REVIEW` stops immediately. Neither refreshes and neither commits.

`REFRESH_REQUIRED`, including a recheck that becomes stale, discards the binding and does not copy the rejected decision's context version. When the completed refresh count is still below `RETAILTWIN_REPLAN_MAX_REFRESHES` (default 1, `0` allowed), `replan` calls `investigate` with the same provider and the same investigation. It then reads the context-version source for that store and calls `plan` with the version that read returned, and one new clock reading. A later refresh reads the source again. The new `Decision` values keep the event's correlation id and store id and carry that refreshed context version. The previous `Decision` object is not modified. A blank or failed context read stops the run before `plan`. A decision that does not carry the version just read stops the run before commit, including when a simulation port rewrites it. When a simulation port is injected, it may return scored copies and the highest score is authorized first. When it is not injected, the planner order stands, `simulation_id` stays empty, and `kpi_score` stays `-1.0`.

A provider, planner, simulation, or commit failure stops the run. It does not start another refresh and it does not count as a second live attempt. Past the refresh bound, the run stops with no commit.

## Consequences

A flagship decision whose evidence is one version behind the Live Twin can be replaced by a new decision and committed without a prompt. That committed decision's `context_version`, and the guard result that allowed it, are the version the source reported after the refresh. A twin that is still moving after that refresh stops at the bound with the Live Twin unchanged, and the next refresh, when one is still allowed, reads the source again instead of keeping the rejected version. Swapping the injected provider does not change those outcomes.

The caller supplies the registry, so the refreshed reads are only as current as the ports the caller bound. The commit port must still go through the guarded Executor; this record does not authorize any other writer. Scoring stays optional until #15. The BigQuery audit stays #35. This record does not mark gates G02–G06 or foundation gate #10 passed.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/168
- Issue: #20
- Supersedes:
- Superseded by:
