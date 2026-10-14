# Verifier

ADR 0017. `verify` re-reads the Live inventory rows a decision's actions touch and compares them with the transition those actions imply.

The caller passes the pre-commit `ProductInventory` for each touched SKU and a reader with `inventory(sku)`. Replenishment moves quantity from the backroom to the shelf. A facing change replaces the facing count. A move changes only `slot_id`. The shelf id stays as it was. Each touched SKU must be one version ahead of the pre-commit row.

The report status is `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE`. A row that does not match is `REGRESSION`. A missing baseline, a failed read, empty actions, or evidence whose store or correlation id does not match the caller is `INCONCLUSIVE`. The frozen per-action `VerifierOutcome` is true only when that action's SKU matched. The report status is the outcome the loop records.

`expected_impact.kpi_score` of `-1.0` is the planner's unscored sentinel. It is not compared and this package does not recompute the #33 formula. Any other expected score is `REGRESSION` when the caller supplies a different decimal, and `INCONCLUSIVE` when the caller supplies none.

The audit event stores the decision id, correlation id, status, reason, and SKUs in process memory. Logs use those fields and, on a read failure, the exception type. They do not include the exception text. `verify` does not write the Live Twin, does not import a model SDK, and does not import `demo_runtime`. No route calls it. Re-plan is `replan` in the orchestrator (ADR 0018). This check does not call it.
