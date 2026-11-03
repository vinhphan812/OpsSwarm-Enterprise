"""Regression tests for ADR-032 trusted remediation risk enforcement."""

from __future__ import annotations

import pytest

from opsswarm.models import Risk
from opsswarm.policy import PolicyEngine
from opsswarm.trusted_classification import classify_trusted_operation

POLICY = {
    "policy": {
        "read": "AUTO",
        "safe_write": "AUTO",
        "risky_write": "HUMAN_APPROVAL",
        "destructive": "DENY",
    }
}


def test_classifier_detects_destructive_even_if_model_says_safe() -> None:
    result = classify_trusted_operation("kubectl delete namespace production")
    assert result.effective_risk is Risk.DESTRUCTIVE


def test_classifier_detects_destructive_from_capability_even_if_description_is_generic() -> None:
    result = classify_trusted_operation("restore database", ["database_drop"])
    assert result.effective_risk is Risk.DESTRUCTIVE


def test_model_read_label_cannot_auto_authorise_write() -> None:
    policy = PolicyEngine(POLICY)
    effective, registry, classified = policy.resolve_effective_risk_for_option(
        "drop-db", "drop database production", Risk.READ
    )
    assert registry is None
    assert classified is Risk.DESTRUCTIVE
    assert effective is Risk.DESTRUCTIVE
    assert policy.action(effective) == "DENY"


def test_unknown_operation_is_escalated_not_auto_authorised() -> None:
    policy = PolicyEngine(POLICY)
    effective, registry, classified = policy.resolve_effective_risk_for_option(
        "mystery", "perform an opaque operational action", Risk.SAFE_WRITE
    )
    assert registry is None
    assert classified is Risk.RISKY_WRITE
    assert policy.action(effective) == "HUMAN_APPROVAL"


def test_safe_registry_operation_still_auto_authorises() -> None:
    policy = PolicyEngine(
        {
            **POLICY,
            "capability_registry": {"path": "config/capability-registry.yaml"},
        }
    )
    effective, registry, _ = policy.resolve_effective_risk_for_option(
        "scale", "kubectl scale deployment api --replicas=3", Risk.RISKY_WRITE
    )
    assert registry is not None and registry.matched
    assert effective is Risk.SAFE_WRITE
    assert policy.action(effective) == "AUTO"


def test_missing_required_production_registry_blocks_policy_creation(tmp_path) -> None:
    missing = tmp_path / "missing-registry.yaml"
    with pytest.raises(ValueError, match="Required capability registry"):
        PolicyEngine(
            {
                **POLICY,
                "capability_registry": {"path": str(missing), "required": True},
            }
        )


def test_production_registry_path_is_configured_and_required() -> None:
    import yaml

    with open("config/production.yaml", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    assert config["capability_registry"] == {
        "path": "config/capability-registry.yaml",
        "required": True,
    }


def test_known_cache_refresh_remains_safe_without_registry() -> None:
    policy = PolicyEngine(POLICY)
    effective, registry, classified = policy.resolve_effective_risk_for_option(
        "refresh", "cache.refresh", Risk.SAFE_WRITE, ["cache.refresh"]
    )
    assert registry is None
    assert classified is Risk.SAFE_WRITE
    assert effective is Risk.SAFE_WRITE
    assert policy.action(effective) == "AUTO"


@pytest.mark.unit
def test_registry_allow_list_cannot_re_authorise_destructive_operation() -> None:
    """ADR-032: a registry rule may not downgrade a destructive operation.

    The capability registry classifies "kubectl delete" as risky_write, but a
    namespace deletion is irreversible: the deny-level classifier must win.
    """
    policy = PolicyEngine(
        {
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
            **POLICY,
        }
    )
    effective, registry, _ = policy.resolve_effective_risk_for_option(
        "delete-ns", "kubectl delete namespace production", Risk.SAFE_WRITE
    )
    assert registry is not None and registry.matched
    assert effective is Risk.DESTRUCTIVE
    assert policy.action(effective) == "DENY"


@pytest.mark.unit
def test_registry_allow_list_still_authorises_declared_safe_operation() -> None:
    """ADR-032 must not break the legitimate allow-listed safe flow."""
    policy = PolicyEngine(
        {
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
            **POLICY,
        }
    )
    effective, registry, _ = policy.resolve_effective_risk_for_option(
        "scale", "kubectl scale deployment web --replicas=3", Risk.RISKY_WRITE
    )
    assert registry is not None and registry.matched
    assert effective is Risk.SAFE_WRITE
    assert policy.action(effective) == "AUTO"


@pytest.mark.unit
def test_registry_rule_risk_is_respected_for_privileged_patch() -> None:
    """The registry classifies /admin patches as human-approval operations."""
    policy = PolicyEngine(
        {
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
            **POLICY,
        }
    )
    effective, registry, _ = policy.resolve_effective_risk_for_option(
        "admin-patch", "patch /admin/settings", Risk.SAFE_WRITE
    )
    assert registry is not None and registry.matched
    assert effective is Risk.RISKY_WRITE
    assert policy.action(effective) == "HUMAN_APPROVAL"
