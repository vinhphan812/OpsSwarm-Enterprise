# Architecture Decision Records (ADRs)

This directory contains Architectural Decision Records for the OpsSwarm project.

## ADR Index

| ADR                                              | Title                          | Status   | Notes                                           |
|--------------------------------------------------|--------------------------------|----------|-------------------------------------------------|
| 001                                              | *(not yet used)*               | —        | Reserved for future decisions                   |
| 002                                              | *(not yet used)*               | —        | Reserved for future decisions                   |
| 003                                              | *(not yet used)*               | —        | Reserved for future decisions                   |
| 004                                              | *(not yet used)*               | —        | Reserved for future decisions                   |
| 005                                              | *(not yet used)*               | —        | Reserved for future decisions                   |
| [006](ADR-006_SKILL_FRONTMATTER_CONTRACT.md)     | Skill Frontmatter Contract     | Approved | S1–S8 SKILL.md schema                           |
| [007](ADR-007_SKILL_GATE_VALIDATOR.md)           | Skill Gate Validator           | Proposed | Independent CI; see `scripts/validate_skill.py` |
| [008](ADR-008_DEPENDENCY_LOCK_RELEASE_POLICY.md) | Dependency Lock Release Policy | Approved | requirements.txt, SBOM, checksum                |
| [009-1](ADR-009-1_IDEMPOTENCY_STRATEGY.md)       | Idempotency Strategy           | Approved | #9 reliability                                  |
| [009-2](ADR-009-2_STATE_ENFORCEMENT.md)          | State Enforcement              | Approved | #9 reliability                                  |
| [009-3](ADR-009-3_CHECKPOINT_STRATEGY.md)        | Checkpoint Strategy            | Approved | #9 reliability                                  |
| [009-4](ADR-009-4_EVIDENCE_DEDUPLICATION.md)     | Evidence Deduplication         | Approved | #9 reliability                                  |
| [009-5](ADR-009-5_COMMAND_DETERMINISM.md)        | Command Determinism            | Approved | #9 reliability                                  |
| [010](ADR-010_SECURITY_WORKFLOW_AND_POLICY.md)   | Security Workflow and Policy   | Approved | #7 CI gate                                      |
| [011](ADR-011_SKILL_ARTEFACT_CONTRACT.md) | Skill Artifact Contract        | Approved | #2, #6                                     |
| [012](ADR-012_COMMAND_OUTCOME_MODEL.md) | Command Outcome Model          | Proposed | #9 reliability (Once-style CONFIRMED/ABSENT/UNKNOWN) |

## ADR Lifecycle Statuses

| Status         | Meaning                                     |
|----------------|---------------------------------------------|
| **Proposed**   | Under discussion; not yet adopted           |
| **Accepted**   | Adopted and is the current project position |
| **Deprecated** | No longer recommended; no replacement yet   |
| **Superseded** | Replaced by a later ADR                     |

## ADR Naming Convention

ADRs use the format `ADR-NNN-title.md` where:

- `NNN` is a zero-padded number
- `title` is a lowercase hyphenated title

## Related Documentation

- [Documentation Index](../index.md)
- [Audit Reports](../audits/)
