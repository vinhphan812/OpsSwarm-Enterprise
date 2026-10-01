# ADR-007: Skill Gate Validator

**Date:** 2026-09-22
**Status:** Proposed
**Type:** Architecture Decision

## Context

OpsSwarm-Enterprise ships 8 Skills (S1–S8). Each Skill ships as a directory containing at minimum a `SKILL.md` with YAML
frontmatter defining `name`, `version`, `description`, and `dependencies` (ADR-006). Before a Skill ships, an
independent gate must verify structural integrity, dependency resolution, and evidence generation — without relying on
the Skill's own runtime or tooling.

## Decision

An independent CLI validator `scripts/validate_skill.py` enforces these gates:

1. **Static structural validation** — exactly the allowlisted S1-S8 directory and exact `name`/`description` frontmatter are required; skill folders may contain only `SKILL.md`.
2. **Directory layout validation** — undeclared per-skill scripts, resources, tests, or other files fail validation.
3. **Dependency resolution** — all declared dependency entries (when present) must reference an existing allowlisted Skill.
4. **Test contract verification** — every skill must have at least 24 substantive tests, with normal, boundary, fault, and cross-skill categories. Category and per-test identity evidence is emitted in JSON.
5. **Runnable enforcement** — `--runnable` runs dependency, structure, test count, category, and evidence checks; it is not a skip flag.
6. **Evidence generation** — each gate run emits structured JSONL containing machine-readable per-test evidence consumable by CI.

## Implementation

The validator is implemented at `scripts/validate_skill.py` and is invoked by `.github/workflows/skill-gates.yml` as an
independent job per Skill (S1–S8). It accepts a `--skill` argument and emits a non-zero exit code on any gate failure.

## Status History

| Date       | Status   | Note                                   |
|------------|----------|----------------------------------------|
| 2026-09-22 | Proposed | CLI scaffolded; CI integration pending |

## Related Decisions

- [ADR-006](ADR-006_SKILL_FRONTMATTER_CONTRACT.md) — Skill frontmatter schema
- [ADR-011](ADR-011_SKILL_ARTEFACT_CONTRACT.md) — Skill artifact structure and test evidence mapping
