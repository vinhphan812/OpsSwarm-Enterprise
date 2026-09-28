# ADR-013: Trusted Capability Registry for Deterministic Approval

**Status:** Proposed
**Created:** 2026-09-28
**Related:** Issue #24, PR #32, ADR-012

---

## Context

PR #32 delivered `PolicyEngine.classify_operation()` which inspects command text to detect
high-risk operations (e.g., `patch /admin/`). However, approval in `orchestrator.py` still
uses `option.risk` — the risk label supplied by the LLM model in `RemediationOption.risk` —
as the primary classification. The LLM-supplied label is advisory only; it cannot be
deterministically overridden by an operator.

This creates two concrete problems:

1. **Model hallucination of risk**: An LLM may label a `kubectl delete pod` operation as
   `safe_write` when the operator's policy classifies all `delete` operations as
   `risky_write` or higher. The system defers to the model rather than the policy.
2. **No operator-controlled allow-list**: Trusted operations that are known-safe at the
   operator's discretion (e.g., an approved migration script that always sets the replica
   count to a specific value) cannot be unconditionally whitelisted.

Issue #24 tracks the requirement for a trusted capability registry that makes approval
deterministic: the operator's declared policy always takes precedence over the model's
judgment.

---

## Required Decisions

### D1 — Where is the registry defined?

| Option | Description | Complexity | Risk |
|--------|-------------|------------|------|
| A | Embedded in `PolicyEngine` as a Python constant | Low | Inflexible; requires code changes to update policy |
| B | JSON/YAML file on disk (e.g., `config/capability-registry.yaml`) | Low | Requires redeploy of the config file; standard ops |
| C | Entries in `policy` section of `config/production.yaml` / `test.yaml` | Low | Co-locates policy with other config; grows large |
| D | OpenClaw skill frontmatter (`skills/*/SKILL.md` `capabilities:` field) | Medium | Operators already edit skills; ties risk to skill definitions |

**Decision: Option B — `config/capability-registry.yaml` (standalone YAML file).**

Rationale:
- **Separation of concerns**: The registry is operator-authored policy, not code. A separate
  file makes it clear what is being reviewed and audited.
- **Environment-variable expansion**: `opsswarm/config.py` already supports `${ENV_VAR}`
  expansion in YAML. The registry file can use the same mechanism, enabling per-environment
  overrides without code changes.
- **Existing infrastructure**: Loading is a one-liner: `yaml.safe_load(Path(cfg_path).read_text())`.
  No new libraries required.
- **Alternative C was rejected** because co-locating the registry in `production.yaml`
  mixes declarative policy with runtime orchestration config, making review and versioning
  harder.

The registry file path is configurable via the existing config mechanism:

```yaml
# In config/production.yaml
capability_registry:
  path: "config/capability-registry.yaml"   # relative to repo root
  # path: "/etc/opsswarm/capability-registry.yaml"   # absolute path for containerized deploys
```

If the path key is absent, the registry is treated as empty (model label is used as-is).

---

### D2 — What is the schema?

Each entry maps a **canonical operation key** to a **risk override**.

```yaml
version: "1"           # schema version; required for forward-compatibility
description: |
  Operator-maintained registry of known-safe and known-risky operations.
  The registry overrides LLM-supplied risk labels. Entries are evaluated
  in order of specificity (most-specific match wins).

rules:

  # ── Safe-write allow-list ──────────────────────────────────────
  # The LLM may label these as risky_write; operator declares them safe.
  - id: "allow-kubectl-set-replicas"
    canonical_operation: "kubectl_scale_replicas"
    description: "Scale deployment replicas via kubectl scale --replicas=N"
    pattern: "kubectl scale"          # checked against the raw command string
    pattern_mode: "prefix"            # "prefix" | "contains" | "regex" (default: "contains")
    risk: safe_write
    rationale: "Horizontal scaling is a routine and safe operation"
    approved_by: "platform-team"
    approved_at: "2026-09-15"

  # ── Risky-write demotion ───────────────────────────────────────
  # The LLM may label this as safe_write; operator corrects to risky_write.
  - id: "risky-patch-admin"
    canonical_operation: "admin_patch"
    description: "Any PATCH request to /admin/ namespace"
    pattern: "patch /admin/"
    pattern_mode: "contains"
    risk: risky_write
    rationale: "Admin namespace contains elevated privileges; require human approval"
    approved_by: "security-team"
    approved_at: "2026-09-10"

  # ── Destructive block-list ─────────────────────────────────────
  - id: "deny-flush-redis"
    canonical_operation: "redis_flush"
    description: "FLUSHALL or FLUSHDB on any Redis host"
    pattern: "redis-cli.*FLUSH"
    pattern_mode: "regex"
    risk: destructive
    rationale: "Data loss risk; never auto-execute"
    approved_by: "dba-team"
    approved_at: "2026-09-01"
```

#### Schema Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Schema version. Currently `"1"`. |
| `description` | string | No | Human-readable description of the registry's intent. |
| `rules` | list | Yes | Ordered list of override rules. |
| `rules[].id` | string | Yes | Unique identifier for this rule. |
| `rules[].canonical_operation` | string | Yes | Stable identifier for the operation class. Used in audit logs and evidence. |
| `rules[].description` | string | Yes | Human-readable description of what this rule covers. |
| `rules[].pattern` | string | Yes | String or regex pattern matched against the raw command text. |
| `rules[].pattern_mode` | enum | No | `"contains"` (default), `"prefix"`, `"regex"`. |
| `rules[].risk` | enum | Yes | Override risk level. One of: `read`, `safe_write`, `risky_write`, `destructive`. |
| `rules[].rationale` | string | No | Why this override was introduced. |
| `rules[].approved_by` | string | No | Team or individual who approved this rule. |
| `approved_at` | string | No | ISO-8601 date of approval. |

**Pattern matching is case-insensitive.** Whitespace normalization is applied before matching.

**Canonical operation identifiers** should use snake_case (e.g., `kubectl_scale_replicas`,
`admin_patch`, `redis_flush`). The canonical operation name is stable across pattern
changes and is what appears in evidence and audit logs.

---

### D3 — How does it override?

There are two dimensions to override: **direction** and **precedence**.

#### Direction

| Option | Description |
|--------|-------------|
| A | Registry always wins (both upgrades and downgrades) |
| B | Registry only upgrades risk (model's `safe_write` → registry `risky_write` is allowed; registry `safe_write` for model's `risky_write` is ignored) |

**Decision: Option A — registry always wins.**

Rationale: "deterministic approval" means the operator's declared policy is the source of
truth. If the operator explicitly marks a command as `risky_write`, it must not be
auto-executed regardless of what the model said. Option B is the current implicit behavior
(via `classify_operation()` escalation only), which is insufficient for the allow-list
use case.

#### Precedence

```
1. capability-registry rule match  →  use registry risk
2. PolicyEngine.classify_operation  →  use classified risk (escalation only, applied after registry miss)
3. option.risk                       →  use model-supplied risk (fallback)
```

The `PolicyEngine.classify_operation()` escalation is preserved as a second layer for
operations not yet in the registry. It continues to run after the registry lookup, and
its result is used only if the registry did not match. This means the registry and
`classify_operation` are not redundant — they cover different scopes.

#### Precedence pseudocode

```python
def resolve_risk(option: RemediationOption, registry: CapabilityRegistry) -> Risk:
    # Step 1: registry override (always wins on match)
    registry_risk = registry.lookup(option.description)
    if registry_risk is not None:
        return registry_risk

    # Step 2: heuristic escalation (fallback for unregistered operations)
    classified = PolicyEngine.classify_operation(option.description)
    if _RISK_ORDER[classified] > _RISK_ORDER[option.risk]:
        return classified

    # Step 3: model-supplied label
    return option.risk
```

The `_RISK_ORDER` is `{read: -1, safe_write: 0, risky_write: 1, destructive: 2}`.

---

### D4 — How is it versioned and deployed?

| Concern | Decision |
|---------|----------|
| Schema versioning | Integer `version` field in the YAML root. Breaking schema changes increment the major version. The loader validates `version` on load and raises `ValueError` on unknown version. |
| File versioning | The registry file is versioned in the same git repository as the codebase. Changes to the registry are reviewed via the standard PR process. |
| Environment-specific overrides | `${ENV_VAR}` expansion (existing `config.py` mechanism) allows the `path` key itself to be environment-variable-driven: `path: "${CAPABILITY_REGISTRY_PATH:-config/capability-registry.yaml}"`. |
| Startup validation | `PolicyEngine` (or a new `CapabilityRegistry` class) validates the registry file on startup. Invalid YAML or unknown schema version raises `ValueError` at startup, blocking the process. |
| Hot reload | Not supported in v1. Changes require a process restart. |
| Read-only environments | If the registry file is not readable, the system logs a warning and falls back to the model label (fail-closed is NOT applied here to avoid single-file outages blocking the whole system; instead a warning is logged). |

**Rationale for git versioning**: The registry is policy, not infrastructure config.
Treating it as code (git-tracked, PR-reviewed, deployed with the app) provides audit
trail, rollback, and access control via existing repo permissions.

---

### D5 — What happens when an unknown operation is encountered?

**Decision: Fail-open for the registry (warning + model label), fail-closed for `classify_operation`.**

| Scenario | Behavior |
|----------|----------|
| Registry file is missing or unreadable | Log `WARNING`, use model label. Do not block startup or approval. |
| Registry file has invalid YAML | Raise `ValueError` at startup. Block startup until fixed. |
| Registry file has unknown `version` | Raise `ValueError` at startup. |
| No rule matches the operation | Use `PolicyEngine.classify_operation()` result; if that also yields the model's original label, use model label. Log the unmatched operation at `INFO` level. |
| Rule matches but `risk` value is invalid | Raise `ValueError` at startup (validation is done once on load, not at match time). |

The asymmetric treatment of missing file vs. invalid file is intentional: a missing file
means "no registry configured" (operator has not opted in), while an invalid file means
"registry is misconfigured" (operator tried to configure it and made an error).

---

## Audit Trail

Each approval event that uses the registry must record the following in the evidence store
(evidence kind: `S6.capability_override`):

```json
{
  "option_id": "opt-001",
  "canonical_operation": "admin_patch",
  "rule_id": "risky-patch-admin",
  "registry_risk": "risky_write",
  "model_risk": "safe_write",
  "effective_risk": "risky_write",
  "pattern_matched": "patch /admin/",
  "pattern_mode": "contains",
  "approved_by": "alice",
  "timestamp": "2026-09-28T12:00:00Z"
}
```

The `canonical_operation` field provides a stable, human-readable identifier for the
overridden operation that does not depend on the pattern text (which may change as the
registry evolves).

Evidence entries are appended via the existing `EvidenceStore.append()` mechanism.

---

## Summary of Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | `config/capability-registry.yaml`, path configurable via `capability_registry.path` in `production.yaml` | Operator-authored policy separate from code; uses existing config infrastructure |
| D2 | YAML schema with `version`, `rules[].id`, `canonical_operation`, `pattern`, `pattern_mode`, `risk` | Matches existing YAML conventions; extensible without breaking existing entries |
| D3 | Registry always wins on match; `classify_operation()` preserved as a second escalation layer | Deterministic approval requires operator policy as source of truth; existing escalation behavior retained for unregistered ops |
| D4 | Git-tracked, PR-reviewed, startup validation, no hot reload | Policy-as-code discipline; startup validation catches misconfiguration early |
| D5 | Missing registry file: warning + model label; invalid YAML/version: block startup; unmatched operation: `classify_operation` then model label | Missing ≠ misconfigured; unmatched operations degrade gracefully with full logging |

---

## Out of Scope (Implementation Task)

- Loading and caching of the registry file
- Pattern-matching implementation (`contains`, `prefix`, `regex`)
- Integration point in `PolicyEngine` or `Orchestrator.approve()`
- Unit tests for the registry lookup logic
- Migration of existing `PolicyEngine.classify_operation()` entries into registry format

These belong to the implementation task that follows this ADR.

---

## Consequences

### Positive
- Approval is operator-deterministic: the configured policy is always the source of truth.
- Registry changes go through standard PR review, providing an auditable change history.
- Canonical operation names in evidence make post-incident review and reporting unambiguous.
- Graceful degradation when registry is absent or an operation is unmatched.

### Negative
- Registry must be manually kept in sync with operational reality. Stale entries can
  produce incorrect risk labels.
- Process restart is required to pick up registry changes.
- Registry file adds one more file for operators to maintain.

### Risks
- An overly broad pattern (e.g., `"delete"`) could unintentionally override many operations.
  Mitigation: encourage narrow patterns; add a `pattern_review` CI gate that flags rules
  with common keywords (flagged in a follow-up task).
- Untrusted actor with write access to the repo could add allow-rules that bypass safety.
  Mitigation: standard repo access controls apply; consider a separate `capability-
  registry.approved_by` field for future integration with an approval workflow.

---

## References

- `opsswarm/policy.py` — existing `PolicyEngine.classify_operation()` implementation
- `opsswarm/orchestrator.py:544-583` — current `approve` command handler (option.risk usage)
- `opsswarm/config.py` — config loading with `${ENV_VAR}` expansion
- `config/test.yaml` — existing policy config format
- ADR-012: Command Outcome Model (evidence schema precedent)
