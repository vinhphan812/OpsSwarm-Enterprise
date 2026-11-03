# Historical Triage Reports

This directory contains working documents produced during the v2.2 quality and skill hardening initiative. They are retained for audit trail and traceability. They have been superseded by Kanban task cards on the [opsswarm-enterprise board](https://github.com/vinhphan812/OpsSwarm-Enterprise).

Every report in this directory belongs to a closed issue. Each carries a one-line status header stating the truth about its findings, so a reader can tell a resolved report from an open gap without opening it. The original analysis bodies are preserved verbatim as the historical record.

## Reports

| File | Issue | Summary | Status |
|------|-------|---------|--------|
| `CI_QUALITY_GATES_TRIAGE.md` | #5 | Gap analysis: ci.yml, Ruff, MyPy, coverage | RESOLVED — closed in #5 (2026-09-27) |
| `RELEASE_CLEAN_INSTALL_TRIAGE.md` | #8 | Gap analysis: release.yml, wheel, smoke test | RESOLVED — closed in #8 (2026-10-05) |
| `S1_S4_SKILL_CONTRACTS_TRIAGE.md` | #2 | Skill contracts for S1–S4 | RESOLVED — closed in #2 (2026-10-03) |
| `S5_S8_SKILL_CONTRACTS_TRIAGE.md` | #2 | Skill contracts for S5–S8 | RESOLVED — closed in #2 (2026-10-03) |
| `SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md` | #7 | Security CI: Bandit, pip-audit, Gitleaks, SBOM | RESOLVED — closed in #7 (2026-09-27) |
| `SKILL_CONTRACTS_TRIAGE.md` | #2/#6 | Combined Skill contract gap analysis | RESOLVED — closed in #2 (2026-10-03) and #6 (2026-10-05) |
| `TEST_ARCHITECTURE_TRIAGE.md` | #3/#4 | Test hierarchy and layer gaps | RESOLVED — closed in #3 and #4 (2026-10-03) |
| `TEST_CAMPAIGN_S192.md` | #3 | 192-test campaign plan | RESOLVED — closed in #3 (2026-10-03) |
| `TRIAGE_v2.2_QUALITY_SKILL_HARDENING.md` | #1–#9 | Master triage for all v2.2 issues | RESOLVED — closed in #1 (2026-10-05) |
| `V2.2_RELEASE_INTEGRATION_TRIAGE.md` | #1 | Release integration analysis across the v2.2 triage reports (#1–#9) | RESOLVED — closed in #1 (2026-10-05) |
| `DOCUMENTATION_IA_AUDIT_2026-09-22.md` | #2/#3 | Documentation information architecture audit | RESOLVED — closed in #2 and #3 (2026-10-03); remaining documentation drift closed in #25 (2026-10-05) |
| `GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md` | #8 | Release workflow gap analysis: missing artefacts and release-time assumptions | RESOLVED — closed in #8 (2026-10-05) |
| `GAP_ANALYSIS_S1_S8_ARTEFACTS.md` | #2/#6 | Per-Skill `scripts/`, `resources/` and `tests/` artefact gap analysis | SUPERSEDED — see [ADR-011](../../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) |
| `PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md` | #9 | Design for persistence, idempotency, concurrency and recovery | RESOLVED — closed in #9 (2026-10-05); the five decisions are recorded in ADR-009-1 to ADR-009-5 |

## Where current work lives

There is exactly **one** current audit worklist:
[`../../audits/CURRENT_AUDIT_WORKLIST.md`](../../audits/CURRENT_AUDIT_WORKLIST.md). It lists the open
audit findings, each with the GitHub issue that owns the work. The current audit report index is
[`../../audits/README.md`](../../audits/README.md), and the triage index is
[`../README.md`](../README.md).

A new report does not belong in this directory unless its issue is closed. Add open findings to the
current audit worklist instead.
