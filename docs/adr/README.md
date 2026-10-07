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

- Copy `template.md` for the next record and use the next free number.
- One decision per file.
- Status is `Proposed`, `Accepted`, `Superseded`, or `Deprecated`.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0003](0003-serve-store-reads-through-the-api.md) | Serve store reads through the API | Accepted |
