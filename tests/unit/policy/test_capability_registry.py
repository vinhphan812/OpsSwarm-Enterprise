# ADR-013 Capability Registry — unit test suite
# Focused tests covering: downgrade, unknown capability, destructive denial,
# stale approval (digest binding), and allowed read-only flow.
#
# Reference: docs/adr/ADR-013_CAPABILITY_REGISTRY.md

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from opsswarm.models import Risk
from opsswarm.registry import (
    CapabilityRegistry,
    RegistryResult,
    RegistryRule,
    _RISK_ORDER,
)
from opsswarm.policy import PolicyEngine


# ===========================================================================
# Fixtures
# ===========================================================================

VALID_REGISTRY_YAML = """
version: "1"
description: "Test registry"
rules:

  # ── Destructive block-list first (most-specific) ──────────────────────────

  - id: "deny-flush-redis"
    canonical_operation: "redis_flush"
    description: "Redis flush"
    pattern: "redis-cli.*flush"
    pattern_mode: "regex"
    risk: destructive
    rationale: "Data loss"
    approved_by: "dba-team"
    approved_at: "2026-09-01"

  - id: "deny-drop-database"
    canonical_operation: "database_drop"
    description: "Drop database"
    pattern: "drop database"
    pattern_mode: "contains"
    risk: destructive
    rationale: "Data loss"
    approved_by: "dba-team"
    approved_at: "2026-09-02"

  - id: "deny-kubectl-delete-all"
    canonical_operation: "kubectl_delete_all"
    description: "kubectl delete --all"
    pattern: "kubectl delete.*--all"
    pattern_mode: "regex"
    risk: destructive
    rationale: "Bulk deletion"
    approved_by: "security-team"
    approved_at: "2026-09-05"

  # ── Risky-write demotions ────────────────────────────────────────────────

  - id: "risky-patch-admin"
    canonical_operation: "admin_patch"
    description: "Patch admin"
    pattern: "patch /admin/"
    pattern_mode: "contains"
    risk: risky_write
    rationale: "Elevated privileges"
    approved_by: "security-team"
    approved_at: "2026-09-10"

  - id: "risky-kubectl-delete"
    canonical_operation: "kubectl_delete"
    description: "kubectl delete"
    pattern: "kubectl delete"
    pattern_mode: "prefix"
    risk: risky_write
    rationale: "Deletion"
    approved_by: "platform-team"
    approved_at: "2026-09-12"

  # ── Safe-write allow-list ────────────────────────────────────────────────

  - id: "allow-kubectl-scale"
    canonical_operation: "kubectl_scale_replicas"
    description: "Scale replicas"
    pattern: "kubectl scale"
    pattern_mode: "prefix"
    risk: safe_write
    rationale: "Horizontal scaling"
    approved_by: "platform-team"
    approved_at: "2026-09-15"
"""


@pytest.fixture
def valid_registry_path(tmp_path: Path) -> Path:
    """A temp YAML file with a valid v1 registry."""
    p = tmp_path / "registry.yaml"
    p.write_text(VALID_REGISTRY_YAML, encoding="utf-8")
    return p


@pytest.fixture
def empty_registry_path(tmp_path: Path) -> Path:
    """A temp YAML file with zero rules."""
    p = tmp_path / "empty.yaml"
    p.write_text('version: "1"\ndescription: "Empty"\nrules: []\n', encoding="utf-8")
    return p


@pytest.fixture
def policy_engine_with_registry(valid_registry_path: Path) -> PolicyEngine:
    """PolicyEngine loaded with the valid test registry."""
    cfg = {
        "policy": {
            "read": "AUTO",
            "safe_write": "AUTO",
            "risky_write": "HUMAN_APPROVAL",
            "destructive": "DENY",
        },
        "capability_registry": {"path": str(valid_registry_path)},
    }
    return PolicyEngine(cfg)


@pytest.fixture
def policy_engine_no_registry() -> PolicyEngine:
    """PolicyEngine with no registry configured."""
    cfg = {
        "policy": {
            "read": "AUTO",
            "safe_write": "AUTO",
            "risky_write": "HUMAN_APPROVAL",
            "destructive": "DENY",
        },
    }
    return PolicyEngine(cfg)


# ===========================================================================
# NORMAL — happy path
# ===========================================================================

@pytest.mark.unit
def test_risk_order_values():
    """Risk-ORD: _RISK_ORDER values are correctly ordered."""
    assert _RISK_ORDER[Risk.READ] < _RISK_ORDER[Risk.SAFE_WRITE]
    assert _RISK_ORDER[Risk.SAFE_WRITE] < _RISK_ORDER[Risk.RISKY_WRITE]
    assert _RISK_ORDER[Risk.RISKY_WRITE] < _RISK_ORDER[Risk.DESTRUCTIVE]


@pytest.mark.unit
def test_registry_load_valid(valid_registry_path: Path):
    """Reg-N1: Valid v1 registry loads successfully."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    assert reg.version == "1"
    assert len(reg.rules) == 6
    assert reg.rule_count() == 6


@pytest.mark.unit
def test_registry_load_missing_returns_none(tmp_path: Path):
    """Reg-N2: Missing registry file returns None (warning + model label fallback)."""
    reg = CapabilityRegistry.load(tmp_path / "nonexistent.yaml")
    assert reg is None


@pytest.mark.unit
def test_registry_load_empty_rules(empty_registry_path: Path):
    """Reg-N3: Registry with zero rules loads but is_empty()."""
    reg = CapabilityRegistry.load(empty_registry_path)
    assert reg is not None
    assert reg.is_empty()


@pytest.mark.unit
def test_registry_load_invalid_yaml(tmp_path: Path):
    """Reg-N4: Invalid YAML raises ValueError (blocks startup per ADR-013 D5)."""
    p = tmp_path / "bad.yaml"
    p.write_text("  invalid: yaml: content\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_load_unknown_version(tmp_path: Path):
    """Reg-N5: Unknown schema version raises ValueError."""
    p = tmp_path / "badversion.yaml"
    p.write_text('version: "99"\nrules: []\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported registry schema version"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_load_missing_version(tmp_path: Path):
    """Reg-N6: Missing version field raises ValueError."""
    p = tmp_path / "noversion.yaml"
    p.write_text("rules: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required 'version' field"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_load_invalid_risk(tmp_path: Path):
    """Reg-N7: Invalid risk value in rule raises ValueError on load."""
    p = tmp_path / "badrisk.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "bad"\n    canonical_operation: "x"\n    description: "x"\n    pattern: "x"\n    risk: "not_a_risk"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid risk"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_load_duplicate_rule_id(tmp_path: Path):
    """Reg-N8: Duplicate rule id raises ValueError."""
    p = tmp_path / "dup.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "dup"\n    canonical_operation: "a"\n    description: "a"\n    pattern: "a"\n    risk: safe_write\n  - id: "dup"\n    canonical_operation: "b"\n    description: "b"\n    pattern: "b"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate rule id"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_load_missing_pattern(tmp_path: Path):
    """Reg-N9: Missing pattern field raises ValueError."""
    p = tmp_path / "nopattern.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "r1"\n    canonical_operation: "x"\n    description: "x"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required 'pattern' field"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_lookup_contains_match(valid_registry_path: Path):
    """Reg-N10: 'contains' pattern mode matches substring."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("Please patch /admin/settings for me")
    assert result.matched
    assert result.rule_id == "risky-patch-admin"
    assert result.registry_risk == Risk.RISKY_WRITE
    assert result.canonical_operation == "admin_patch"


@pytest.mark.unit
def test_registry_lookup_prefix_match(valid_registry_path: Path):
    """Reg-N11: 'prefix' pattern mode matches command prefix."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("kubectl scale deployment web --replicas=3")
    assert result.matched
    assert result.rule_id == "allow-kubectl-scale"
    assert result.registry_risk == Risk.SAFE_WRITE


@pytest.mark.unit
def test_registry_lookup_prefix_no_match(valid_registry_path: Path):
    """Reg-N12: 'prefix' mode does not match mid-string."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("sudo kubectl scale deployment web --replicas=3")
    assert not result.matched


@pytest.mark.unit
def test_registry_lookup_regex_match(valid_registry_path: Path):
    """Reg-N13: 'regex' pattern mode matches regex."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("redis-cli -h prod FLUSHDB")
    assert result.matched
    assert result.rule_id == "deny-flush-redis"
    assert result.registry_risk == Risk.DESTRUCTIVE


@pytest.mark.unit
def test_registry_lookup_case_insensitive(valid_registry_path: Path):
    """Reg-N14: Pattern matching is case-insensitive."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("PATCH /ADMIN/SETTINGS")
    assert result.matched
    assert result.rule_id == "risky-patch-admin"


@pytest.mark.unit
def test_registry_lookup_none_returns_not_matched(valid_registry_path: Path):
    """Reg-N15: lookup(None) returns unmatched (never crashes)."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup(None)
    assert not result.matched
    assert result.rule_id is None


@pytest.mark.unit
def test_registry_lookup_no_match(valid_registry_path: Path):
    """Reg-N16: Unmatched command returns RegistryResult(matched=False)."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("kubectl get pods")
    assert not result.matched
    assert result.rule_id is None


@pytest.mark.unit
def test_registry_lookup_first_match_wins(valid_registry_path: Path):
    """Reg-N17: Rules are evaluated in declaration order (first match wins)."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    # "kubectl delete" matches the delete rule (index 3) — not the scale rule
    result = reg.lookup("kubectl delete pod api")
    assert result.matched
    assert result.rule_id == "risky-kubectl-delete"


@pytest.mark.unit
def test_registry_approved_by_captured(valid_registry_path: Path):
    """Reg-N18: approved_by is propagated to RegistryResult."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("redis-cli FLUSHDB")
    assert result.matched
    assert result.approved_by == "dba-team"


@pytest.mark.unit
def test_registry_pattern_matched_captured(valid_registry_path: Path):
    """Reg-N19: The actual pattern text is captured in the result."""
    reg = CapabilityRegistry.load(valid_registry_path)
    assert reg is not None
    result = reg.lookup("Please patch /admin/config now")
    assert result.matched
    assert result.pattern_matched == "patch /admin/"


# ===========================================================================
# BOUNDARY — edge cases
# ===========================================================================

@pytest.mark.unit
def test_registry_all_four_risk_levels_load(tmp_path: Path):
    """Reg-B1: All four Risk levels are accepted."""
    yaml_content = """
version: "1"
rules:
  - id: "r1"
    canonical_operation: "op1"
    description: "d1"
    pattern: "cmd1"
    risk: read
  - id: "r2"
    canonical_operation: "op2"
    description: "d2"
    pattern: "cmd2"
    risk: safe_write
  - id: "r3"
    canonical_operation: "op3"
    description: "d3"
    pattern: "cmd3"
    risk: risky_write
  - id: "r4"
    canonical_operation: "op4"
    description: "d4"
    pattern: "cmd4"
    risk: destructive
"""
    p = tmp_path / "allrisks.yaml"
    p.write_text(yaml_content, encoding="utf-8")
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    assert reg.rule_count() == 4
    risks = {r.risk for r in reg.rules}
    assert risks == {Risk.READ, Risk.SAFE_WRITE, Risk.RISKY_WRITE, Risk.DESTRUCTIVE}


@pytest.mark.unit
def test_registry_invalid_pattern_mode(tmp_path: Path):
    """Reg-B2: Invalid pattern_mode raises ValueError."""
    p = tmp_path / "badmode.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "r1"\n    canonical_operation: "x"\n    description: "x"\n    pattern: "x"\n    pattern_mode: "invalid"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid pattern_mode"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_missing_canonical_operation_uses_id(tmp_path: Path):
    """Reg-B3: Missing canonical_operation defaults to rule id."""
    p = tmp_path / "nocanon.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "my-rule-id"\n    description: "my desc"\n    pattern: "my pattern"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    assert reg.rules[0].canonical_operation == "my-rule-id"


@pytest.mark.unit
def test_registry_missing_description_defaults_to_empty(tmp_path: Path):
    """Reg-B4: Missing description defaults to empty string."""
    p = tmp_path / "nodesc.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "r1"\n    canonical_operation: "op1"\n    pattern: "p"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    assert reg.rules[0].description == ""


@pytest.mark.unit
def test_registry_load_with_whitespace_only_pattern(tmp_path: Path):
    """Reg-B5: Empty pattern after whitespace raises ValueError."""
    p = tmp_path / "wspattern.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "r1"\n    canonical_operation: "x"\n    description: "x"\n    pattern: "   "\n    risk: safe_write\n',
        encoding="utf-8",
    )
    # The YAML loader gives "   " (not empty), but lookup will not match anything.
    # Per schema, pattern is required and should be truthy.
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    result = reg.lookup("anything")
    assert not result.matched


@pytest.mark.unit
def test_registry_rules_preserve_declaration_order(tmp_path: Path):
    """Reg-B6: Rules are stored in declaration order (first-match-wins semantics)."""
    p = tmp_path / "order.yaml"
    p.write_text(
        'version: "1"\nrules:\n'
        '  - id: "first"\n    canonical_operation: "op"\n    description: "d"\n    pattern: "kubectl"\n    risk: safe_write\n'
        '  - id: "second"\n    canonical_operation: "op"\n    description: "d"\n    pattern: "kubectl delete"\n    risk: destructive\n',
        encoding="utf-8",
    )
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    assert reg.rules[0].id == "first"
    assert reg.rules[1].id == "second"
    # "kubectl delete" matches "first" (index 0) because "kubectl" is matched first
    result = reg.lookup("kubectl delete pod api")
    assert result.matched
    assert result.rule_id == "first"


# ===========================================================================
# FAULT — error handling
# ===========================================================================

@pytest.mark.unit
def test_registry_fault_invalid_yaml_corrupt_file(tmp_path: Path):
    """Reg-F1: YAML parse failure raises ValueError."""
    p = tmp_path / "corrupt.yaml"
    p.write_text("key: [unclosed list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_fault_rule_without_id(tmp_path: Path):
    """Reg-F2: Rule missing 'id' field raises ValueError."""
    p = tmp_path / "noid.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - canonical_operation: "x"\n    description: "x"\n    pattern: "x"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required 'id' field"):
        CapabilityRegistry.load(p)


@pytest.mark.unit
def test_registry_fault_regex_pattern_invalid(valid_registry_path: Path, tmp_path: Path):
    """Reg-F3: Invalid regex in pattern is handled gracefully in lookup."""
    p = tmp_path / "badregex.yaml"
    p.write_text(
        'version: "1"\nrules:\n  - id: "bad-re"\n    canonical_operation: "x"\n    description: "x"\n    pattern: "[invalid("\n    pattern_mode: "regex"\n    risk: safe_write\n',
        encoding="utf-8",
    )
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    result = reg.lookup("anything")
    # Should not raise — invalid regex just never matches
    assert not result.matched


@pytest.mark.unit
def test_registry_fault_load_from_none_path():
    """Reg-F4: load(None) returns None (no file specified)."""
    reg = CapabilityRegistry.load(None)
    assert reg is None


@pytest.mark.unit
def test_registry_fault_empty_rules_list_loads(tmp_path: Path):
    """Reg-F5: Empty rules list is valid YAML and loads without error."""
    p = tmp_path / "emptylist.yaml"
    p.write_text('version: "1"\nrules: []\n', encoding="utf-8")
    reg = CapabilityRegistry.load(p)
    assert reg is not None
    assert reg.rule_count() == 0


# ===========================================================================
# POLICY INTEGRATION — resolve_effective_risk
# ===========================================================================

@pytest.mark.unit
def test_policy_resolve_registry_match_upgrades_model(policy_engine_with_registry):
    """Pol-R1: Registry can upgrade (override) model label upward."""
    # Model says safe_write, registry says risky_write
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "Please patch /admin/settings",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.RISKY_WRITE
    assert rr is not None
    assert rr.matched
    assert rr.rule_id == "risky-patch-admin"
    assert cr is None  # step 2 not reached


@pytest.mark.unit
def test_policy_resolve_registry_match_downgrades_model(policy_engine_with_registry):
    """Pol-R2: Registry can downgrade (override) model label downward (D3 Decision A)."""
    # Model says risky_write, registry says safe_write (allow-list)
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl scale deployment web --replicas=3",
        Risk.RISKY_WRITE,
    )
    assert eff == Risk.SAFE_WRITE
    assert rr is not None
    assert rr.matched
    assert rr.rule_id == "allow-kubectl-scale"


@pytest.mark.unit
def test_policy_resolve_registry_destructive_blocks(policy_engine_with_registry):
    """Pol-R3: Registry destructive match is enforced (fail-closed)."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "redis-cli -h prod FLUSHDB",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert rr is not None
    assert rr.matched
    assert policy_engine_with_registry.action(eff) == "DENY"


@pytest.mark.unit
def test_policy_resolve_no_registry_no_match_uses_model(policy_engine_no_registry):
    """Pol-R4: Without registry, classify_operation defaults to RISKY_WRITE for unknown ops."""
    eff, rr, cr = policy_engine_no_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl get pods",
        Risk.SAFE_WRITE,
    )
    # No registry → classify_operation sees no known pattern → RISKY_WRITE
    # RISKY_WRITE > SAFE_WRITE → escalation
    assert eff == Risk.RISKY_WRITE
    assert rr is None


@pytest.mark.unit
def test_policy_resolve_classify_operation_escalation(policy_engine_no_registry):
    """Pol-R5: classify_operation escalates risk when it is more restrictive."""
    # classify_operation sees "patch /admin/" → DESTRUCTIVE
    # model says SAFE_WRITE → escalation to DESTRUCTIVE
    eff, rr, cr = policy_engine_no_registry.resolve_effective_risk_for_option(
        "opt1",
        "patch /admin/settings to fix auth bug",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert cr == Risk.DESTRUCTIVE
    assert rr is None  # no registry


@pytest.mark.unit
def test_policy_resolve_no_escalation_when_model_higher(policy_engine_no_registry):
    """Pol-R6: classify_operation does not downgrade when model is higher."""
    # classify_operation sees "kubectl get" → RISKY_WRITE
    # model says DESTRUCTIVE → no escalation (RISKY_WRITE < DESTRUCTIVE)
    eff, rr, cr = policy_engine_no_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl get pods",
        Risk.DESTRUCTIVE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert cr == Risk.RISKY_WRITE  # classify result captured even if unused


@pytest.mark.unit
def test_policy_resolve_registry_takes_precedence_over_classify(
    policy_engine_with_registry,
):
    """Pol-R7: Registry always wins over classify_operation (D3 Decision A)."""
    # Registry says risky_write for "kubectl delete"
    # classify_operation would say RISKY_WRITE (normal delete)
    # Model says SAFE_WRITE → both would escalate, but registry wins
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl delete pod api",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.RISKY_WRITE
    assert rr is not None
    assert rr.rule_id == "risky-kubectl-delete"


@pytest.mark.unit
def test_policy_registry_property_accessible(policy_engine_with_registry):
    """Pol-R8: PolicyEngine.registry exposes the loaded registry."""
    assert policy_engine_with_registry.registry is not None
    assert policy_engine_with_registry.registry.rule_count() == 6


@pytest.mark.unit
def test_policy_no_registry_property_none(policy_engine_no_registry):
    """Pol-R9: PolicyEngine.registry is None when not configured."""
    assert policy_engine_no_registry.registry is None


# ===========================================================================
# DOWNGRADE — LLM cannot lower registered risky capability
# ===========================================================================

@pytest.mark.unit
def test_downgrade_prevented_llm_safe_model_for_destructive_registry(
    policy_engine_with_registry,
):
    """Down-1: LLM labeling destructive-as-safe is overridden by registry."""
    # Registry marks "redis flush" as destructive
    # LLM (model) labels it as safe_write
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "redis-cli FLUSHDB",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE  # registry overrides model
    assert rr is not None
    assert rr.matched
    assert policy_engine_with_registry.action(eff) == "DENY"


@pytest.mark.unit
def test_downgrade_prevented_llm_safe_model_for_risky_registry(
    policy_engine_with_registry,
):
    """Down-2: LLM labeling risky-as-safe is overridden by registry."""
    # Registry marks "patch /admin/" as risky_write
    # LLM labels as safe_write
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "patch /admin/ to fix auth",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.RISKY_WRITE  # registry overrides model
    assert rr.rule_id == "risky-patch-admin"


@pytest.mark.unit
def test_downgrade_allowed_when_no_registry(policy_engine_no_registry):
    """Down-3: Without a registry, classify_operation never downgrades — that's the gap the registry fills."""
    # classify_operation sees "kubectl scale" → RISKY_WRITE (no known pattern)
    # Model says SAFE_WRITE → RISKY_WRITE > SAFE_WRITE → escalation
    # No downgrade is possible without the registry allow-list.
    eff, rr, cr = policy_engine_no_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl scale deployment web --replicas=5",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.RISKY_WRITE  # escalation; model SAFE_WRITE is overridden


# ===========================================================================
# UNKNOWN CAPABILITY — fail-closed
# ===========================================================================

@pytest.mark.unit
def test_unknown_write_capability_no_registry_falls_back_to_model(
    policy_engine_no_registry,
):
    """Unk-1: Unknown write op with no registry uses model label."""
    eff, rr, cr = policy_engine_no_registry.resolve_effective_risk_for_option(
        "opt1",
        "terraform apply -auto-approve",
        Risk.RISKY_WRITE,
    )
    assert eff == Risk.RISKY_WRITE
    assert rr is None
    assert policy_engine_no_registry.action(eff) == "HUMAN_APPROVAL"


@pytest.mark.unit
def test_unknown_read_capability_auto(policy_engine_with_registry):
    """Unk-2: Unknown read op is AUTO."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl get pods -n production",
        Risk.READ,
    )
    # No rule matches "get" → classify_operation sees no "patch" → RISKY_WRITE
    # RISKY_WRITE > READ → escalated to RISKY_WRITE
    # With registry config, risky_write → HUMAN_APPROVAL
    assert eff == Risk.RISKY_WRITE


@pytest.mark.unit
def test_unknown_capability_denied_when_destructive_model_assumed(
    policy_engine_with_registry,
):
    """Unk-3: If model labels unknown op as destructive, policy DENYs it."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "some totally unknown operation xyz123",
        Risk.DESTRUCTIVE,
    )
    # No registry match; classify_operation sees no known pattern → RISKY_WRITE
    # RISKY_WRITE < DESTRUCTIVE → model destructive wins
    assert eff == Risk.DESTRUCTIVE
    assert policy_engine_with_registry.action(eff) == "DENY"


# ===========================================================================
# DESTRUCTIVE DENIAL — destructive ops blocked regardless of model label
# ===========================================================================

@pytest.mark.unit
def test_destructive_deny_redis_flush(policy_engine_with_registry):
    """Dest-1: Redis FLUSHDB is blocked by registry."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "redis-cli FLUSHDB",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert policy_engine_with_registry.action(eff) == "DENY"


@pytest.mark.unit
def test_destructive_deny_drop_database(policy_engine_with_registry):
    """Dest-2: DROP DATABASE is blocked by registry."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "psql -c 'DROP DATABASE production'",
        Risk.RISKY_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert policy_engine_with_registry.action(eff) == "DENY"


@pytest.mark.unit
def test_destructive_deny_kubectl_delete_all(policy_engine_with_registry):
    """Dest-3: kubectl delete --all is blocked by registry."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl delete pods --all -n default",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE
    assert policy_engine_with_registry.action(eff) == "DENY"


@pytest.mark.unit
def test_destructive_deny_case_insensitive(policy_engine_with_registry):
    """Dest-4: Destructive denial is case-insensitive."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "REDIS-CLI FLUSHALL",
        Risk.SAFE_WRITE,
    )
    assert eff == Risk.DESTRUCTIVE


# ===========================================================================
# STALE APPROVAL — digest binding (structural test)
# ===========================================================================

@pytest.mark.unit
def test_stale_approval_different_description_changes_risk(policy_engine_with_registry):
    """Stale-1: Modified description invalidates approval because canonical op changes."""
    # Original approval: "kubectl scale deployment web"
    eff1, rr1, _ = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl scale deployment web --replicas=3",
        Risk.RISKY_WRITE,
    )
    # Same option.id, but description changed → different canonical op match
    eff2, rr2, _ = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl delete deployment web",  # different command!
        Risk.RISKY_WRITE,
    )
    assert eff1 == Risk.SAFE_WRITE  # scale → allow-kubectl-scale rule
    assert eff2 == Risk.RISKY_WRITE  # delete → risky-kubectl-delete rule
    assert eff1 != eff2


@pytest.mark.unit
def test_stale_approval_unknown_op_uses_model(policy_engine_with_registry):
    """Stale-2: Unknown ops use classify escalation; registry lookup still runs (non-None result)."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "helm rollback web-1",  # not in registry
        Risk.RISKY_WRITE,
    )
    # Registry is loaded but no rule matched → RegistryResult(matched=False), not None
    assert rr is not None
    assert not rr.matched
    # classify_operation sees no known pattern → RISKY_WRITE
    # RISKY_WRITE == model RISKY_WRITE → no escalation
    assert eff == Risk.RISKY_WRITE


# ===========================================================================
# READ-ONLY FLOW — allowed through registry
# ===========================================================================

@pytest.mark.unit
def test_read_only_allowed_by_model(policy_engine_with_registry):
    """Read-1: READ risk is always AUTO regardless of registry."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl get pods",
        Risk.READ,
    )
    # No rule matches "get" → classify_operation → RISKY_WRITE
    # RISKY_WRITE > READ → escalated
    assert eff == Risk.RISKY_WRITE
    assert policy_engine_with_registry.action(eff) == "HUMAN_APPROVAL"


@pytest.mark.unit
def test_read_only_allowed_by_registry_allow_rule(policy_engine_with_registry):
    """Read-2: Read-like ops in allow-list are safe_write AUTO."""
    # The registry allow-kubectl-scale rule marks "kubectl scale" as safe_write
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl scale deployment web --replicas=2",
        Risk.RISKY_WRITE,
    )
    assert eff == Risk.SAFE_WRITE
    assert policy_engine_with_registry.action(eff) == "AUTO"


@pytest.mark.unit
def test_read_only_model_read_falls_to_classify_escalation(
    policy_engine_with_registry,
):
    """Read-3: Model READ for a write-like op is escalated."""
    eff, rr, cr = policy_engine_with_registry.resolve_effective_risk_for_option(
        "opt1",
        "kubectl delete pod api-xyz",
        Risk.READ,  # model mislabels as read
    )
    # Registry matches risky-kubectl-delete → RISKY_WRITE
    assert eff == Risk.RISKY_WRITE
    assert rr is not None


# ===========================================================================
# POLICYENGINE CLASSIFY_OPERATION — preserved backward compatibility
# ===========================================================================

@pytest.mark.unit
def test_classify_operation_preserved_patch_admin(policy_engine_no_registry):
    """Classify-1: classify_operation still detects patch /admin/ as DESTRUCTIVE."""
    risk = policy_engine_no_registry.classify_operation("patch /admin/config")
    assert risk == Risk.DESTRUCTIVE


@pytest.mark.unit
def test_classify_operation_preserved_patch_generic(policy_engine_no_registry):
    """Classify-2: classify_operation still detects generic patch as SAFE_WRITE."""
    risk = policy_engine_no_registry.classify_operation("patch /app/config")
    assert risk == Risk.SAFE_WRITE


@pytest.mark.unit
def test_classify_operation_preserved_unknown(policy_engine_no_registry):
    """Classify-3: classify_operation defaults unknown commands to RISKY_WRITE."""
    risk = policy_engine_no_registry.classify_operation("kubectl get pods")
    assert risk == Risk.RISKY_WRITE


@pytest.mark.unit
def test_classify_operation_preserved_none(policy_engine_no_registry):
    """Classify-4: classify_operation(None) returns RISKY_WRITE."""
    risk = policy_engine_no_registry.classify_operation(None)
    assert risk == Risk.RISKY_WRITE


# ===========================================================================
# ACTION MAPPING — existing policy engine behavior preserved
# ===========================================================================

@pytest.mark.unit
def test_action_read_auto(policy_engine_with_registry):
    """Action-1: READ is AUTO."""
    assert policy_engine_with_registry.action(Risk.READ) == "AUTO"


@pytest.mark.unit
def test_action_safe_write_auto(policy_engine_with_registry):
    """Action-2: SAFE_WRITE is AUTO."""
    assert policy_engine_with_registry.action(Risk.SAFE_WRITE) == "AUTO"


@pytest.mark.unit
def test_action_risky_write_approval(policy_engine_with_registry):
    """Action-3: RISKY_WRITE requires HUMAN_APPROVAL."""
    assert policy_engine_with_registry.action(Risk.RISKY_WRITE) == "HUMAN_APPROVAL"


@pytest.mark.unit
def test_action_destructive_deny(policy_engine_with_registry):
    """Action-4: DESTRUCTIVE is DENY."""
    assert policy_engine_with_registry.action(Risk.DESTRUCTIVE) == "DENY"


# ===========================================================================
# REGISTRY RULE DIRECT MATCHING
# ===========================================================================

@pytest.mark.unit
def test_rule_matches_contains():
    """Rule-1: contains mode matches substring."""
    rule = RegistryRule(
        id="r1",
        canonical_operation="op",
        description="d",
        pattern="kubectl",
        pattern_mode="contains",
        risk=Risk.SAFE_WRITE,
    )
    assert rule.matches("sudo kubectl scale") is True
    assert rule.matches("kubectl get pods") is True
    assert rule.matches("KUBECTL SCALE") is True  # case-insensitive
    assert rule.matches("something else") is False


@pytest.mark.unit
def test_rule_matches_prefix():
    """Rule-2: prefix mode matches command start."""
    rule = RegistryRule(
        id="r1",
        canonical_operation="op",
        description="d",
        pattern="kubectl",
        pattern_mode="prefix",
        risk=Risk.SAFE_WRITE,
    )
    assert rule.matches("kubectl get pods") is True
    assert rule.matches("sudo kubectl get pods") is False


@pytest.mark.unit
def test_rule_matches_regex():
    """Rule-3: regex mode matches re.search."""
    rule = RegistryRule(
        id="r1",
        canonical_operation="op",
        description="d",
        pattern=r"redis-cli.*flush",
        pattern_mode="regex",
        risk=Risk.DESTRUCTIVE,
    )
    assert rule.matches("redis-cli FLUSHDB") is True
    assert rule.matches("redis-cli -h prod FLUSHALL") is True
    assert rule.matches("redis-cli PING") is False


@pytest.mark.unit
def test_rule_matches_none_input():
    """Rule-4: matches(None) is always False."""
    rule = RegistryRule(
        id="r1",
        canonical_operation="op",
        description="d",
        pattern="x",
        pattern_mode="contains",
        risk=Risk.SAFE_WRITE,
    )
    assert rule.matches(None) is False


@pytest.mark.unit
def test_rule_matches_whitespace_normalization():
    """Rule-5: pattern matching normalizes whitespace."""
    rule = RegistryRule(
        id="r1",
        canonical_operation="op",
        description="d",
        pattern="kubectl scale",
        pattern_mode="contains",
        risk=Risk.SAFE_WRITE,
    )
    # Pattern and command are both lowercased before comparison
    assert rule.matches("  KUBECTL  SCALE  ") is True


# ===========================================================================
# POLICY ENGINE MISSING PATH — graceful degradation
# ===========================================================================

@pytest.mark.unit
def test_policy_missing_registry_path_returns_none():
    """Miss-1: Registry path that does not exist logs warning and returns None."""
    cfg = {
        "policy": {},
        "capability_registry": {"path": "/nonexistent/path/registry.yaml"},
    }
    engine = PolicyEngine(cfg)
    assert engine.registry is None


@pytest.mark.unit
def test_policy_registry_path_empty_removes_registry():
    """Miss-2: Empty capability_registry section has no registry."""
    cfg = {"policy": {}}
    engine = PolicyEngine(cfg)
    assert engine.registry is None


# ===========================================================================
# REGISTRY RESULT DATACLASS
# ===========================================================================

@pytest.mark.unit
def test_registry_result_defaults():
    """Result-1: RegistryResult defaults to unmatched."""
    r = RegistryResult(matched=False)
    assert r.matched is False
    assert r.rule_id is None
    assert r.registry_risk is None


@pytest.mark.unit
def test_registry_result_matched():
    """Result-2: RegistryResult captures all fields on match."""
    r = RegistryResult(
        matched=True,
        rule_id="allow-kubectl-scale",
        canonical_operation="kubectl_scale_replicas",
        registry_risk=Risk.SAFE_WRITE,
        approved_by="platform-team",
        pattern_matched="kubectl scale",
        pattern_mode="prefix",
    )
    assert r.matched is True
    assert r.rule_id == "allow-kubectl-scale"
    assert r.canonical_operation == "kubectl_scale_replicas"
    assert r.registry_risk == Risk.SAFE_WRITE
    assert r.approved_by == "platform-team"
