# 0014. Guard each decision with deterministic gates

Date: 2026-10-13

## Status

Accepted

## Context

Issue #16 needs a deterministic Decision Context Guard (DCG) between a `Decision` and the Live Twin. ARCHITECTURE §4 names five MVP gates: decision integrity, context version, freshness, physical and business constraints, and authorization or policy. The outcomes are `ALLOW`, `DENY`, `REFRESH_REQUIRED` and `HUMAN_REVIEW`. The frozen contracts already define `Decision`, `EvidenceBundle`, `DCGVerdict` and `DCGVerdictResult`. ADR 0011 records `entity_versions` as `{sku: inventory version}` for each bundle. The Live Twin (#6) stores one `InventoryDocument` per SKU with an integer `version`. #85 requires DCG to stay provider-neutral.

The PR #89 demo scaffold in `demo_runtime/` compares a random per-twin context id, has no feasibility or policy gate, never returns `HUMAN_REVIEW`, and is not importable from production code. Building on it was set aside.

Comparing the store-level `context_version` (`store-001:vN`) was set aside. Any change anywhere in the store would make every open decision stale. Reading slot capacity from the web layout was set aside: the Live Twin has no capacity field and the API must not depend on the frontend. Letting a model judge feasibility was set aside. LLM self-checking is not an enforcement boundary.

## Decision

`DecisionContextGuard.evaluate(decision)` in `apps/api/retailtwin_api/guard/decision_context_guard/` returns a `DCGVerdictResult`. It takes an injected Live Twin reader (`get_inventory` and `list_inventory`), a `GuardPolicy` and a clock. Gates run in this order and the first failure decides the verdict:

1. **Integrity** (`DENY INVALID_DECISION`). The decision must have a non-blank `decision_id`, `agent_id` and `context_version`. It must have at least one action and at least one evidence bundle. All bundles must come from one store and carry one non-blank `correlation_id`, so evidence from two investigations is never mixed. No action type may repeat for the same SKU. `context_timestamp` and every bundle `freshness` and `collected_at` must be timezone-aware and no more than the 5s clock skew in the future. Only `context_timestamp` and `freshness` set the expiry.
2. **Evidence**. Every bundle must have `is_sufficient`, otherwise `DENY INSUFFICIENT_EVIDENCE`. Bundles must agree on each SKU version, otherwise `DENY CONFLICTING_EVIDENCE`.
3. **Context version**, entity-level. Each SKU that an action touches is read from the Live Twin.
   - If the evidence has no version for the SKU: `DENY MISSING_CONTEXT_VERSION`.
   - If the SKU is not in the store: `DENY UNKNOWN_ENTITY`.
   - If the live version differs from the version the evidence read: `REFRESH_REQUIRED VERSION_STALE`.
   - SKUs that no action touches do not make the decision stale.
4. **Freshness** (`REFRESH_REQUIRED CONTEXT_EXPIRED`). The oldest of `context_timestamp` and every bundle `freshness` must be no older than `RETAILTWIN_DCG_FRESHNESS_SECONDS`. The default is 120.
5. **Physical feasibility** (`DENY INFEASIBLE_ACTION`). Actions are applied in order to a copy of the live documents.
   - A replenishment may not exceed the backroom quantity at that point.
   - Facings may not exceed `RETAILTWIN_DCG_MAX_FACINGS`, default 12, which stands in for slot capacity.
   - A move must start from the SKU's current slot and end in a different slot that no other SKU holds.
6. **Policy**. An action type outside `allowed_actions` is `DENY ACTION_NOT_ALLOWED`. More than `RETAILTWIN_DCG_MAX_ACTIONS` actions (default 5), or a replenishment above `RETAILTWIN_DCG_MAX_REPLENISH_UNITS` (default 200), is `HUMAN_REVIEW POLICY_THRESHOLD`.

Any exception from a Live Twin read is `DENY TWIN_UNAVAILABLE`, and the exception text is not copied.

`context_hash` is the SHA-256 of canonical JSON over the decision id, the store id, the live versions read and the canonical actions. A canonical action is `{"type": "move_product" | "change_facings" | "replenish_shelf", ...fields}`.

The result fields are set as follows:

- `policy_result` records `failed_gate`, one `{gate, passed, detail}` entry per gate that ran, the store id, the correlation id and the live versions read. Verdict and read-failure logs carry the decision id and the correlation id.
- On `ALLOW`, `expiry` is the time the oldest context ages out. On any other verdict, `expiry` is the evaluation time.

The guard never writes the Live Twin, never calls a model, and imports no model SDK. A test enforces the import rule.

## Consequences

The Executor (#18) can treat `ALLOW` plus `context_hash` as the only basis for a commit authorization. No-Stale-Commit (#17) can re-run the same evaluation immediately before commit and compare hashes. The DCG UI (#40) can render `policy_result.checks` without parsing log text.

`max_facings` is a single policy number until the Live Twin or planogram serves per-slot capacity. Move feasibility knows only which slots are occupied, not which slots exist. Nothing calls the guard yet: `POST /simulations/{id}/approve` is wired in #18. Guard decisions are not persisted. The audit trail is #35.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/148
- Issue: #16
- Supersedes:
- Superseded by:
