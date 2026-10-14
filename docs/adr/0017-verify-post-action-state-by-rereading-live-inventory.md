# 0017. Verify post-action state by rereading live inventory

Date: 2026-10-14

## Status

Accepted

## Context

Issue #19 requires a check after execution. A successful commit response does not prove the shelf, slot, facings, or version the actions named are what the Live Twin now holds. The check must emit `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE`, and a known mismatch must surface as `REGRESSION`.

ADR 0012 leaves `expected_impact.kpi_score` at `-1.0` until simulation scores the candidate. That sentinel is not a business score. Issue #33 owns the KPI formula. Recomputing it here would be a second formula. The demo verifier under `demo_runtime` compares a private gap score and can ask for rollback. That type stays sealed. This record does not supersede ADR 0014, ADR 0015, or ADR 0016. The guarded Executor is the only Live Twin writer. The verifier does not call it. The caller supplies the pre-commit rows, and this check only re-reads.

Calling a model to explain the outcome was set aside. #85 requires the three statuses to be decided by deterministic code. Trusting the executor's own return value was set aside: the point of the check is a fresh read. Inventing a tolerance band around a KPI was set aside: a band would hide a real miss, and an unscored decision has no KPI to band.

## Decision

`verify` in `apps/api/retailtwin_api/agents/verifier/verify.py` re-reads each SKU a decision's actions touch through an injected `inventory(sku)` reader. The caller passes the pre-commit `ProductInventory` of those SKUs. The expected row is the pre-commit row after the actions, in order, with the version one ahead:

- `replenish_shelf` adds the quantity to the shelf and subtracts it from the backroom;
- `change_facings` replaces the facing count;
- `move_product` changes only `slot_id`.

The shelf id stays on the pre-commit row. The layout, not this check, maps a slot to a shelf. Every evidence bundle must name the same store and the same correlation id the caller passes. The result status is `VERIFIED` when every re-read matches that expected row. It is `REGRESSION` when a re-read contradicts the row, or when a scored `kpi_score` disagrees with the observed decimal the caller supplies. It is `INCONCLUSIVE` when there is nothing to compare: no actions, disagreeing evidence, a missing baseline, a failed or empty read, or a scored decision with no observed decimal. `kpi_score` of `-1.0` is not compared. This module does not call the KPI evaluator.

Each action also gets the frozen `VerifierOutcome`: `verified` is true only when that action's SKU matched the expected row. The report status remains the source of truth for `VERIFIED`, `REGRESSION`, and `INCONCLUSIVE`. A process-memory audit event stores the decision id, correlation id, status, reason, and SKUs. Logs use those fields and the exception type. They do not include the exception text. `verify` has no write method and does not import a model SDK or `demo_runtime`.

## Consequences

A mismatch between the committed actions and the next inventory read is visible without a model call. The caller, later the orchestrator after #18, must keep the pre-commit rows. This check does not re-run the guard, does not roll back, and does not re-plan. Re-plan stays issue #20. The BigQuery audit stays issue #35.

An expected score other than `-1.0` stays `INCONCLUSIVE` until the caller passes the decimal it observed. This record does not define how that decimal is measured.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/167
- Issue: #19
- Supersedes:
- Superseded by:
