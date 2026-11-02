# Triage Reports

This directory contains historical triage reports from the v2.2 quality and skill hardening initiative. These documents were produced during issue triage and are retained for audit trail purposes. They have been superseded by Kanban task cards and implementation tasks.

## The rule this directory follows

1. There is exactly **one** current audit worklist in the repository:
   [`../audits/CURRENT_AUDIT_WORKLIST.md`](../audits/CURRENT_AUDIT_WORKLIST.md). Open audit findings
   are listed there and nowhere else, each with the GitHub issue that owns the work.
2. A triage report whose issue is closed is **historical**. It lives under
   [`historical/`](historical/) and carries a one-line status header stating the truth:
   `Status: RESOLVED - closed in <issue> (<date>)` or `Status: SUPERSEDED - see <ADR>`. The original
   analysis body is preserved verbatim.
3. Only a **confirmed architectural decision** is promoted to an ADR in [`../adr/`](../adr/). A triage
   report is not an ADR.
4. Resolved findings are removed from current content. A current document never presents a closed
   issue's finding as outstanding work.

## Historical Reports

Reports retained for audit trail and traceability. See [`historical/README.md`](historical/README.md)
for the full index with per-report status.

| File | Scope |
|------|-------|
| `CI_QUALITY_GATES_TRIAGE.md` | Issue #5 CI quality gates gap analysis |
| `RELEASE_CLEAN_INSTALL_TRIAGE.md` | Issue #8 release workflow gap analysis |
| `S1_S4_SKILL_CONTRACTS_TRIAGE.md` | Issues #2/#6 Skills S1–S4 gap analysis |
| `S5_S8_SKILL_CONTRACTS_TRIAGE.md` | Issues #2/#6 Skills S5–S8 gap analysis |
| `SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md` | Issue #7 security CI gap analysis |
| `SKILL_CONTRACTS_TRIAGE.md` | Issues #2/#6 combined Skill contracts analysis |
| `TEST_ARCHITECTURE_TRIAGE.md` | Issues #3/#4 test architecture gap analysis |
| `TEST_CAMPAIGN_S192.md` | Issue #3 192-test campaign plan |
| `TRIAGE_v2.2_QUALITY_SKILL_HARDENING.md` | Master triage for all v2.2 issues |
| `V2.2_RELEASE_INTEGRATION_TRIAGE.md` | Issue #1 release integration analysis across the v2.2 triage reports |
| `DOCUMENTATION_IA_AUDIT_2026-09-22.md` | Documentation information architecture audit |
| `GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md` | Issue #8 release workflow gap analysis |
| `GAP_ANALYSIS_S1_S8_ARTEFACTS.md` | Issue #2 Skill artefact gap analysis (superseded by ADR-011) |
| `PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md` | Issue #9 reliability analysis |

## Active Triage

**There is no active triage report in this directory.** Every report listed above belongs to a closed
issue and is retained for traceability only.

The open audit findings are tracked in the single current audit worklist:
[`../audits/CURRENT_AUDIT_WORKLIST.md`](../audits/CURRENT_AUDIT_WORKLIST.md). It states its own
contents, and each open finding names the GitHub issue that owns the work. Do not add a second
worklist here — add the finding to that document instead.
