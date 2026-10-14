# Architecture decision log

An architecture decision record (ADR) captures one important architecture decision, the context in which it was made, and the consequences. The log is the set of those records.

Format reference: [architecture-decision-record](https://github.com/architecture-decision-record/architecture-decision-record). Records use the Michael Nygard sections: Status, Context, Decision, Consequences.

`docs/ARCHITECTURE.md` describes the system. This directory records why a choice was made and which pull request adopted it.

## Pull request rule

Every pull request names the ADR it tracks.

- A change that makes a new architecture decision adds the next record in the same pull request.
- A change that replaces an accepted decision adds a new record and marks the previous one `Superseded`. Do not rewrite the accepted history.
- A change that only implements an accepted decision links that record.
- A change with no architectural effect writes `N/A` and one line saying why.

Write a new record when the change affects a public schema, a state transition, a tool or action contract, a security invariant, a storage or execution boundary, or another choice a later reader would otherwise re-open.

Skip a new record when an accepted ADR already covers the choice, or when the change is a small fix with no architectural effect.

## File convention

`NNNN-imperative-verb-phrase.md`

- `0001-record-architecture-decisions-in-pull-requests.md`
- Copy `template.md` for the next record and use the next free number.
- One decision per file.
- Status is `Proposed`, `Accepted`, `Superseded`, or `Deprecated`.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions-in-pull-requests.md) | Record architecture decisions in pull requests | Accepted |
| [0002](0002-render-store-entities-as-named-primitives.md) | Render store entities as named primitives | Accepted |
| [0003](0003-serve-store-reads-through-the-api.md) | Serve store reads through the API | Accepted |
| [0004](0004-keep-the-cloud-foundation-on-free-tier.md) | Keep the cloud foundation on the free tier | Accepted |
| [0005](0005-land-each-normalized-store-event-once.md) | Land each normalized store event once | Accepted |
| [0006](0006-use-heroui-v2-for-app-status-ui.md) | Use HeroUI v2 for app status UI | Accepted |
| [0007](0007-keep-store-layout-static-until-the-twin-serves-geometry.md) | Keep the store layout static until the twin serves geometry | Accepted |
| [0008](0008-provider-neutral-llm.md) | Provider-neutral LLM runtime | Accepted |
| [0009](0009-expose-one-allow-listed-tool-registry.md) | Expose one allow-listed tool registry | Accepted |
| [0010](0010-start-one-investigation-per-sale.md) | Start one investigation per new sale | Accepted |
| [0011](0011-collect-versioned-evidence-from-the-tool-registry.md) | Collect versioned evidence from the tool registry | Accepted |
| [0012](0012-bind-candidate-plans-to-the-evidence-context.md) | Bind candidate plans to the evidence context | Accepted |
| [0014](0014-guard-each-decision-with-deterministic-gates.md) | Guard each decision with deterministic gates | Accepted |
| [0015](0015-recheck-live-versions-before-every-commit.md) | Recheck live versions before every commit | Accepted |
| [0016](0016-commit-only-through-a-signed-single-use-authorization.md) | Commit only through a signed single-use authorization | Accepted |
| [0017](0017-verify-post-action-state-by-rereading-live-inventory.md) | Verify post-action state by rereading live inventory | Accepted |
