# 0001. Record architecture decisions in pull requests

Date: 2026-10-07

## Status

Accepted

## Context

RetailTwin AI splits work across the agent and Decision Context Guard, the 3D twin, data and Google Cloud, and integration. Choices that bind those roles are easy to lose when they live only inside the narrative architecture docs. A later pull request can drift from a schema, a state transition, a tool contract, or a security invariant without a record of what was decided, which alternatives were set aside, and which change introduced it.

The team needs a decision log that pull requests can point at. The format reference is the [architecture-decision-record](https://github.com/architecture-decision-record/architecture-decision-record) collection, using Michael Nygard's Status, Context, Decision, and Consequences sections.

This record is the tracking rule. It does not accept product or contract choices that are still open. Those get their own records in the pull request that adopts them.

## Decision

Keep the architecture decision log in `docs/adr/`. Name each record `NNNN-imperative-verb-phrase.md`. Use `template.md`.

Every pull request names the ADR it tracks.

- A pull request that makes a new architecture decision adds the next record in the same change.
- A pull request that replaces an accepted decision adds a new record and sets the previous status to `Superseded`, with links both ways. Accepted text stays intact.
- A pull request that implements an accepted decision links that record and does not open a new one.
- A pull request with no architectural effect writes `N/A` and one line saying why.

Open a record when the change affects a public schema, a state transition, a tool or action contract, a security invariant, a storage or execution boundary, or another choice a later reader would otherwise re-open.

## Consequences

- Reviewers can reject a pull request that changes an architectural invariant without a new or superseding record.
- The pull request template always has an ADR field, so the link is visible even when the answer is `N/A`.
- Architecture pull requests carry a short extra document. Small fixes only fill the field.
- Product decisions still living only in `docs/ARCHITECTURE.md` and the other guides are recorded when the pull request that implements or freezes them lands, not ahead of that decision.
- Pull request:
- Issue:
- Supersedes:
- Superseded by:
