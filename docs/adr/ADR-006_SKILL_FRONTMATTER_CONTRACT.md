# ADR-006: Skill Frontmatter Contract (S1-S8)

**Date:** 2026-09-22
**Status:** APPROVED
**Type:** Contract Specification
**Scope:** skills/*/SKILL.md

---

## Summary

This ADR defines the canonical Skill frontmatter contract for all 8 Skills (S1-S8). It resolves the proposed fields from
SKILL_CONTRACTS_TRIAGE.md against the current codebase evidence and explicitly records rejected fields.

---

## Decision

The canonical Skill frontmatter contract is:

```yaml
---
name: <skill-id>           # e.g., s1-intent-guard
description: <one-line>    # Canonical purpose
---
```

**No additional frontmatter fields are adopted.**

---

## Evidence Analysis

### Current State (Source Evidence)

All 8 skills currently use minimal frontmatter:

| Skill                | name | description | skill_level | pipeline_phase | author | version | depends_on | produces |
|----------------------|------|-------------|-------------|----------------|--------|---------|------------|----------|
| s1-intent-guard      | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s2-task-graph        | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s3-horizon-plan      | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s4-role-dispatch     | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s5-collab-exec       | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s6-resilience-guard  | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s7-observe-verify    | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |
| s8-orchestration-hub | ✓    | ✓           | ✗           | ✗              | ✗      | ✗       | ✗          | ✗        |

### Producer/Consumer Crosswalk

| Proposed Field   | Producer | Consumer         | Status                |
|------------------|----------|------------------|-----------------------|
| `name`           | Manual   | buildsystem/grep | **ADOPTED** (current) |
| `description`    | Manual   | buildsystem/grep | **ADOPTED** (current) |
| `skill_level`    | None     | None             | **REJECTED**          |
| `pipeline_phase` | None     | None             | **REJECTED**          |
| `author`         | None     | None             | **REJECTED**          |
| `version`        | None     | None             | **REJECTED**          |
| `depends_on`     | None     | None             | **REJECTED**          |
| `produces`       | None     | None             | **REJECTED**          |

### Rationale

1. **No producer exists** for the proposed fields. No buildsystem, test runner, or runtime component writes or generates
   `skill_level`, `pipeline_phase`, etc.

2. **No consumer exists** for the proposed fields. No code references these fields at runtime or in CI.

3. **The current minimal contract works.** The Skills are logically partitioned in `skill_logic.py` and
   `orchestrator.py`, not in separate runtime entrypoints.

4. **The proposed fields add weight without value** in the current architecture. If future requirements emerge (e.g.,
   dependency graphs between skills), they can be added then.

---

## Evidence Identity Schema

**ADOPTED** - Evidence format is already implemented and functional:

- **ID Format:** `EV-YYYYMMDDHHMMSSffffff`
- **Storage:** JSONL at `runtime-data/evidence/{run_id}.jsonl`
- **Producer:** `EvidenceStore.append()` in `evidence.py`
- **Consumer:** `EvidenceStore.list()` in `evidence.py`

This matches the spec in SKILL_CONTRACTS_TRIAGE.md lines 96-101.

---

## S7/S8 Authority Boundary

**REAFFIRMED** - The S7/S8 boundary is preserved as immutable:

1. **S7 is independent:** S8 cannot bypass S7 verification (orchestrator.py:107-115)
2. **S7 has veto power:** Failed verification keeps issue OPEN (orchestrator.py:112-114)
3. **S7 uses read-only evidence:** Independent health checks, not executor claims
4. **No regression allowed:** Any code change must preserve S7 independence

**Authority rule:** Free text in GitHub comments NEVER authorizes side effects. Only `/opsswarm approve <option>`
commands carry authority (orchestrator.py:121-156).

---

## Rejected Fields (Explicit Record)

The following fields from SKILL_CONTRACTS_TRIAGE.md are explicitly **REJECTED**:

| Field            | Reason                                                                    |
|------------------|---------------------------------------------------------------------------|
| `skill_level`    | No producer/consumer; S1-S8 is implicit in orchestrator phase             |
| `pipeline_phase` | No producer/consumer; lifecycle is implicit in RunState enum              |
| `author`         | No producer/consumer; tracked in git history                              |
| `version`        | No producer/consumer; versioned via git tags                              |
| `depends_on`     | No producer/consumer; skill orchestration is hardcoded in orchestrator.py |
| `produces`       | No producer/consumer; artifacts are typed in models.py                    |

---

## Validation

- [x] Crosswalk every field to real producer/consumer
- [x] Retain S7 independence (no regression)
- [x] Retain GitHub-command-only authority
- [x] Explicitly record rejected fields
- [x] No conflict against current state/evidence

---

## Related

- SKILL_CONTRACTS_TRIAGE.md (source analysis)
- ARCHITECTURE.md (frozen decisions)
- orchestrator.py (S7/S8 implementation)
- evidence.py (evidence store implementation)
- models.py (artifact types)
