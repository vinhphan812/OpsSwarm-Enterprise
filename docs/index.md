---
owner: dev-pm
status: active
purpose: Main documentation entry point for OpsSwarm
---

# OpsSwarm Documentation

Welcome to the OpsSwarm project documentation. This is the **main entry point** for all project documentation.

## Quick reference

| Topic                            | Location                                                                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Project overview and quick start | [`../README.md`](../README.md)                                                                           |
| Test suite                       | [`tests/`](../tests/)                                                                                    |
| Skill contracts                  | [`../skills/`](https://github.com/vinhphan812/OpsSwarm-Enterprise/tree/master/skills)                    |
| CI workflows                     | [`.github/workflows/`](https://github.com/vinhphan812/OpsSwarm-Enterprise/tree/master/.github/workflows) |
| GitHub Actions runs              | [github.com/.../actions](https://github.com/vinhphan812/OpsSwarm-Enterprise/actions)                     |

## Canonical Documentation

| Document                           | Description                                                                                  |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System context, S1–S8 responsibility map, authority, evidence, trust boundaries, invariants. |
| [FLOWS.md](FLOWS.md)               | End-to-end sequences, exact runtime state machine, human gates, ambiguous-write handling.    |
| [INSTALLATION.md](INSTALLATION.md) | Installation and OpenClaw/GitHub setup.                                                      |
| [OPERATIONS.md](OPERATIONS.md)     | Human/machine incident operation.                                                            |
| [SECURITY.md](SECURITY.md)         | Security and authority model.                                                                |

## Testing and quality

| Layer       | Path                                          | Description                                                              |
| ----------- | --------------------------------------------- | ------------------------------------------------------------------------ |
| Unit        | [`tests/unit/`](../tests/unit/)               | Unit tests for all opsswarm modules. Run: `pytest tests/unit/`           |
| Integration | [`tests/integration/`](../tests/integration/) | Integration tests for orchestrator flows and crash recovery.             |
| Contracts   | [`tests/contracts/`](../tests/contracts/)     | Contract tests for evidence, GitHub, OpenClaw, webhook interfaces.       |
| E2E         | [`tests/e2e/`](../tests/e2e/)                 | End-to-end incident lifecycle tests.                                     |
| Faults      | [`tests/faults/`](../tests/faults/)           | Fault injection: timeouts, rate limits, API errors, concurrent webhooks. |
| Security    | [`tests/security/`](../tests/security/)       | Webhook signature validation tests.                                      |

Run all tests: `pytest -q`

CI quality gates are defined in [`.github/workflows/ci.yml`](https://github.com/vinhphan812/OpsSwarm-Enterprise/tree/master/.github/workflows).

## Architecture Decision Records

- [ADR Index](adr/) — Architectural decisions and their current status.

## Guides

- [Guides](guides/) — Operational guides, contracts, and implementation plans.

## Triage Reports

- [Triage Reports](triage/) — Issue triage, gap analysis, and remediation tracking.

## Audits & Reports

- [Audit Reports index](audits/README.md) — every audit report with its date, scope, status and owning issue.

### Current audit worklist

There is exactly **one** current audit worklist in the repository. Open audit findings are listed there
and nowhere else, each with the GitHub issue that owns the work:

- [CURRENT_AUDIT_WORKLIST.md](audits/CURRENT_AUDIT_WORKLIST.md) — the single current audit worklist.

### Current specifications

- [ISSUE-73_DEPLOYMENT_PROFILE_SPEC.md](audits/ISSUE-73_DEPLOYMENT_PROFILE_SPEC.md) — governing
  specification for the OCI, Compose and Kubernetes deployment profile (Issue #73, resolved).

### Historical reports

The reports below are retained for audit trail and traceability only. Each belongs to a closed issue and
carries a status header stating the outcome of its findings:

- [DOCUMENTATION_IA_AUDIT_2026-09-22.md](triage/historical/DOCUMENTATION_IA_AUDIT_2026-09-22.md) —
  documentation information architecture audit (resolved).
- [GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md](triage/historical/GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md) —
  release workflow gap analysis (resolved).
- [GAP_ANALYSIS_S1_S8_ARTEFACTS.md](triage/historical/GAP_ANALYSIS_S1_S8_ARTEFACTS.md) — per-Skill
  artefact gap analysis (superseded by ADR-011).
- [PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md](triage/historical/PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md) —
  persistence, idempotency and recovery design (resolved).

The full historical index is [triage/historical/README.md](triage/historical/README.md).

## Documentation rules

- One current audit worklist; historical reports under the triage historical area.
- Only confirmed architectural decisions are promoted to ADRs in [`adr/`](adr/README.md).
- Resolved findings are removed from current audit content, never presented as outstanding.

## Additional Resources

- [OpenClaw README](../openclaw/README.md) — OpenClaw-specific configuration notes.
- [Skill contracts](../skills/) — S1–S8 Skill definitions and validators.

---

_This index is maintained by the dev-pm team. Add new documentation to the appropriate section._
