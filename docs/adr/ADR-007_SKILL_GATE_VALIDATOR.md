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

1. **Static structural validation** — `SKILL.md` frontmatter parses, required fields present, `dependencies` entries
   reference existing Skill names.
2. **Directory layout validation** — expected subdirectories exist (`scripts/`, `resources/`, `tests/` if declared in
   `SKILL.md`).
3. **Dependency resolution** — all `dependencies` entries in any Skill's `SKILL.md` point to an existing Skill
   directory.
4. **Test count verification** — the Skill's `tests/` directory contains at least the number of test files declared in
   its `SKILL.md` frontmatter.
5. **Evidence generation** — each gate run emits a structured JSON report (`skill-validation-report.json`) consumable by
   CI.

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
