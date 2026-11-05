# ADR-013: Trusted Capability Registry for Deterministic Approval

**Status:** Proposed
**Created:** 2026-09-28
**Related:** Issue #24, PR #32, ADR-012, Issue #134, PR #133

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

**Amendment (Issue #134, PR #133).** The registry alone is not sufficient. The registry
matches on command text, so it cannot express "this *operation identity* is safe"; it can
only express "this *text* is safe". Three gaps remained and are now closed:

1. A **free-text model label could still authorise autonomous execution** when the
   registry did not match, because the fallback path fell back to `option.risk`.
2. An **allow-list registry entry could re-authorise a destructive operation**, because
   the registry won unconditionally on a match.
3. A **model-supplied capability list could authorise autonomous execution**, because
   `RemediationOption.capabilities` is emitted by the model and its membership in the
   operator vocabulary was treated as proof of a declared operation identity.
4. A **registry prefix match could authorise a compound command**, because the pattern
   was applied to the whole description rather than to each chained command.

The deterministic trusted classifier (`opsswarm/trusted_classification.py`) now governs
registry misses, the model label can only escalate risk, a deny-level destructive marker
vetoes any registry match, model-supplied capabilities can only escalate risk, and a
description that chains several commands is resolved command by command.

`PolicyEngine.classify_operation()` is retained for backward compatibility as a
free-text heuristic helper. It is no longer part of the resolution path; the trusted
classifier replaces it there.

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
1. deny-level destructive marker       →  destructive (vetoes a registry match)
2. capability-registry rule match      →  use registry risk
3. deterministic trusted classifier    →  use classified risk (applied after registry miss)
4. option.risk                         →  model-supplied risk may only raise the resolved risk
```

The registry is authoritative on a match: it may raise *and* lower the model-supplied
label, and it may reclassify an operation as `safe_write`/`read` even when the model
called it `risky_write`.

This ADR adds one exception to "registry always wins": a **deny-level destructive marker**
(data loss, namespace destruction, bulk deletion) is never re-authorised by a registry
rule. A registry entry that classifies an operation as `risky_write` or `safe_write` cannot
make an irreversible operation executable, and a human approval cannot override it.

Operations not matched by the registry are resolved by the deterministic trusted
classifier (`opsswarm/trusted_classification.py`). The classifier is not a free-text
heuristic: it inspects the operation description against an operator-owned vocabulary and
inspects destructive and risky markers across the description and the declared
capabilities. An operation that is not a declared identity is *unknown* and is classified
as `risky_write`, which routes it to a human approval gate. A model-supplied risk label
is never sufficient for autonomous execution.

#### Trust boundary: what may authorise autonomous execution

Only two operator-owned sources may authorise autonomous execution:

1. a **capability-registry rule** matched against the operation text; or
2. the **operation description** being exactly an operator-declared operation identity
   (a controlled vocabulary term such as `cache.refresh`).

`RemediationOption.capabilities` is **not** an authorisation input. The S3 model emits
it in the recovery-plan JSON and no operator validates its membership, so a capability
list that claims a safe identity cannot make an operation safe. Capabilities are inspected
only for destructive and risky markers, where they can **escalate** risk — never lower it.
The description is the field that is actually executed, so it is the only model-supplied
field that may carry a declared operation identity, and the match is exact.

#### Compound commands

A description may chain several commands (`;`, `&&`, `||`, `|`, a newline, a command
substitution, or a backtick). A registry rule in `prefix` mode matches the beginning of
the text, so matching the whole description would let an allow-listed first command
authorise a destructive command chained behind it. The description is therefore split into
its individual command segments (separators inside quotes are ignored), each segment is
resolved independently, and the most severe segment decides the outcome. Autonomous
execution additionally requires **every** segment to be authorised individually.

#### Precedence pseudocode

```python
def resolve_risk(option: RemediationOption, registry: CapabilityRegistry) -> Risk:
    effective = None
    for segment in split_operation_segments(option.description):
        trusted = classify_trusted_operation(segment, option.capabilities)
        if trusted.deny_level:
            # Step 0: deny-level destructive markers are never re-authorised
            return Risk.DESTRUCTIVE

        # Step 1: registry override (always wins on match, per segment)
        registry_result = registry.lookup(segment)
        if registry_result is not None and registry_result.matched:
            segment_effective = registry_result.registry_risk
        else:
            # Step 2: trusted classifier, then the model label may only raise
            segment_effective = trusted.effective_risk
            if _RISK_ORDER[option.risk] > _RISK_ORDER[segment_effective]:
                segment_effective = option.risk

        if effective is None or _RISK_ORDER[segment_effective] > _RISK_ORDER[effective]:
            effective = segment_effective
    return effective
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

**Decision: Fail-closed for autonomous execution.**

| Scenario | Behaviour |
|----------|----------|
| Production registry is missing or unreadable | Production startup fails because the registry is required. |
| Registry file has invalid YAML or an unknown version | Raise `ValueError` at startup; block until fixed. |
| No rule matches the operation | Apply the deterministic trusted classifier. Recognised safe/read operations may run only if policy allows; risky operations require human approval; destructive operations are denied. Unknown operations require human approval. The model label alone never authorises automatic execution. |
| Rule matches but `risk` value is invalid | Raise `ValueError` at startup (validation is done once on load, not at match time). |

The production registry is required because autonomous remediation must not depend on a
model-provided risk label. Non-production configurations may omit the registry; in that case
the trusted classifier still governs, and unknown operations require human approval.

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
| D3 | Registry wins on match, except that a deny-level destructive marker vetoes the match; deterministic trusted classification is the next authority; model risk can only escalate, never authorise. Model-supplied capabilities are not an authorisation input (they can only escalate risk), and a compound command is resolved command by command | Deterministic approval requires operator policy as source of truth; a model-authored claim must never authorise execution |
| D4 | Git-tracked, PR-reviewed, startup validation, no hot reload; production registry required | Policy-as-code discipline; missing production policy blocks autonomous execution |
| D5 | Missing production registry blocks startup; unmatched operation is classified conservatively; unknown requires approval; destructive is denied | Model-supplied risk is never sufficient for autonomous execution |

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
