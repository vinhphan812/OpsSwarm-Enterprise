---
owner: dev-pm
status: active
purpose: The single current audit worklist for OpsSwarm Enterprise
---

# Current Audit Worklist

**Status:** CURRENT - the single current audit worklist

This is the **only** current audit worklist in the repository. It lists the audit findings that are still
open, each with the GitHub issue that owns the work. Every other audit document in the tree is either a
current specification referenced by production code, or a historical report retained for traceability.

## Contents of this worklist

| Finding | Owning issue | Area | State |
|---------|--------------|------|-------|
| Autonomous remediation trusts model risk labels without applying effective risk on the AUTO path; production also omits the required capability registry | [#133](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/133) | Policy / remediation authorisation | In progress; AUTO now requires registry or trusted classifier, unknown operations go to human approval, destructive operations are denied |

**This list is exhaustive for the audits covered by this worklist.** There are no further open audit
findings: the documentation information architecture audit and the Issue #8 release workflow gap analysis
both have an empty open-finding set (see below).

The policy / remediation authorisation finding above is a live work item and is not covered by the historical audits listed here.

| Former finding | Owning issue | Resolution |
|----------------|--------------|------------|
| The static-analysis baseline file `.static_analysis_baseline.toml` was absent from `master`, so the Ruff and mypy Stage-2 gate scripts could not enforce a baseline | [#124](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/124) | Closed: the baseline file is tracked and both gate scripts enforce it |
| `k8s/base/deployment.yaml` declared no `readinessProbe`, and the repository's own manifest validator rejected the base profile without one | [#125](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/125) | Closed: the base profile declares a readiness probe and the manifest validator enforces it |
| `.github/workflows/container-delivery.yml` still failed the build if a `readinessProbe` appeared, although `/ready` now exists | [#126](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/126) | Closed: the container-delivery workflow accepts the readiness probe |
| The shared HA rate limiter in `opsswarm/ha_db.py` failed open on database errors, and the synchronous `check_monitoring_rate_limit` entry point in `opsswarm/auth.py` silently returned in-memory semantics under an HA configuration | [#127](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/127) | Closed: the failure policy is explicit (bounded local fallback on an outage, propagation on a schema defect), the degraded mode is observable, and the synchronous entry point is removed |

## Audits with no open findings

| Audit | Historical report | Open findings |
|-------|-------------------|---------------|
| Documentation information architecture (2026-09-22) |
[`../triage/historical/DOCUMENTATION_IA_AUDIT_2026-09-22.md`](../triage/historical/DOCUMENTATION_IA_AUDIT_2026-09-22.md) | None. All four priority items were resolved by the v2.2 documentation restructure. |
| Issue #8 release workflow gap analysis |
[`../triage/historical/GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md`](../triage/historical/GAP_ANALYSIS_ISSUE8_RELEASE_WORKFLOW.md) | None. The three artefacts reported missing (`scripts/validate-artifacts.py`, `artifacts/`, `.github/workflows/security.yml`) are present. |
| S1–S8 operational artefacts gap analysis |
[`../triage/historical/GAP_ANALYSIS_S1_S8_ARTEFACTS.md`](../triage/historical/GAP_ANALYSIS_S1_S8_ARTEFACTS.md) | None. Superseded by ADR-011, which decides the opposite of the report's recommendation. |
| Issue #9 persistence, idempotency and recovery design |
[`../triage/historical/PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md`](../triage/historical/PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md) | None. The five decisions are recorded in ADR-009-1 to ADR-009-5 and the implementation modules exist. |

## Rules that govern this worklist

1. There is exactly **one** current audit worklist in the tree: this document.
2. Resolved findings are removed from current audit content and are not restated as open work here.
3. Historical reports live under `docs/triage/historical/` and each carries a status header stating the
   truth about its findings.
4. Only confirmed architectural decisions are promoted to ADRs in `docs/adr/`. A report is not an ADR.
5. Every open finding names the GitHub issue that owns the work. An open finding with no owning issue is a
   defect in the worklist and must be given an owner before it is listed.
