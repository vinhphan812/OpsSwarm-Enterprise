"""Regression tests for ADR-013 D3 trusted remediation risk enforcement."""

from __future__ import annotations

import pytest

from opsswarm.models import RecoveryPlan, RemediationOption, Risk
from opsswarm.policy import PolicyEngine
from opsswarm.trusted_classification import (
    classify_trusted_operation,
    known_operation_ids,
    split_operation_segments,
)

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


def test_model_capability_cannot_authorise_destructive_description() -> None:
    """A model-claimed capability must not authorise a destructive operation."""
    policy = PolicyEngine(POLICY)
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="cache.refresh",
                    description="kubectl delete pod api",
                    risk=Risk.SAFE_WRITE,
                    capabilities=["cache.refresh"],
                )
            ]
        )
    )
    assert action == "APPROVAL"


def test_model_capability_cannot_authorise_deny_level_description() -> None:
    """A model-claimed capability must not downgrade a deny-level operation."""
    policy = PolicyEngine(POLICY)
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="cache.refresh",
                    description="terminate the postgres cluster and remove all customer data",
                    risk=Risk.SAFE_WRITE,
                    capabilities=["cache.refresh"],
                )
            ]
        )
    )
    assert action == "DENY"


def test_model_capability_cannot_authorise_unknown_or_claimed_read() -> None:
    policy = PolicyEngine(POLICY)
    option = RemediationOption(
        id="unknown",
        description="opaque shell operation",
        risk=Risk.READ,
        capabilities=["metrics.read", "SAFE_WRITE"],
    )
    action, _ = policy.classify_plan(RecoveryPlan(options=[option]))
    assert action == "APPROVAL"


def test_description_declared_identity_still_authorises() -> None:
    """The declared operation identity in the description is still honoured."""
    policy = PolicyEngine(POLICY)
    option = RemediationOption(
        id="refresh",
        description="cache.refresh",
        risk=Risk.SAFE_WRITE,
        capabilities=[],
    )
    action, _ = policy.classify_plan(RecoveryPlan(options=[option]))
    assert action == "AUTO"


def test_compound_description_cannot_hide_behind_allow_listed_prefix() -> None:
    """A chained command must not inherit the allow-list of its first segment."""
    policy = PolicyEngine(
        {
            **POLICY,
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
        }
    )
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="scale-then-delete",
                    description=(
                        "kubectl scale deployment web --replicas=3; kubectl delete pod api"
                    ),
                    risk=Risk.SAFE_WRITE,
                    capabilities=[],
                )
            ]
        )
    )
    assert action == "APPROVAL"


def test_compound_description_cannot_hide_sql_delete_behind_allow_listed_prefix() -> None:
    policy = PolicyEngine(
        {
            **POLICY,
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
        }
    )
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="scale-then-sql",
                    description=(
                        "kubectl scale deployment web --replicas=3; psql -c 'DELETE FROM users'"
                    ),
                    risk=Risk.SAFE_WRITE,
                    capabilities=[],
                )
            ]
        )
    )
    assert action == "APPROVAL"


def test_compound_description_with_destructive_segment_is_denied() -> None:
    policy = PolicyEngine(
        {
            **POLICY,
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
        }
    )
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="scale-then-rm",
                    description="kubectl scale deployment web --replicas=3 && rm -rf /",
                    risk=Risk.SAFE_WRITE,
                    capabilities=[],
                )
            ]
        )
    )
    assert action == "DENY"


def test_allow_listed_single_command_still_auto_authorises() -> None:
    """The compound-command guard must not break the legitimate allow-list flow."""
    policy = PolicyEngine(
        {
            **POLICY,
            "capability_registry": {
                "path": "config/capability-registry.yaml",
                "required": True,
            },
        }
    )
    action, _ = policy.classify_plan(
        RecoveryPlan(
            options=[
                RemediationOption(
                    id="scale",
                    description="kubectl scale deployment web --replicas=3",
                    risk=Risk.RISKY_WRITE,
                    capabilities=[],
                )
            ]
        )
    )
    assert action == "AUTO"


@pytest.mark.unit
def test_split_operation_segments_handles_every_separator() -> None:
    """Every shell chaining construct must produce separate segments."""
    segments = split_operation_segments("a; b && c || d | e\nf `g` $(h)")
    assert segments == ["a", "b", "c", "d", "e", "f", "g", "h"]


@pytest.mark.unit
def test_split_operation_segments_ignores_separators_inside_quotes() -> None:
    """A quoted argument must not be torn apart."""
    segments = split_operation_segments("psql -c 'DELETE FROM a; b'")
    assert segments == ["psql -c 'DELETE FROM a; b'"]


@pytest.mark.unit
def test_split_operation_segments_handles_empty_description() -> None:
    assert split_operation_segments("") == []
    assert split_operation_segments(None) == []
    assert split_operation_segments("   ") == []


@pytest.mark.unit
def test_known_operation_ids_contains_both_vocabularies() -> None:
    ids = known_operation_ids()
    assert "cache.refresh" in ids
    assert "metrics.read" in ids


@pytest.mark.unit
def test_capability_claiming_read_identity_does_not_authorise() -> None:
    """A model-claimed read capability must not authorise an unknown operation."""
    policy = PolicyEngine(POLICY)
    option = RemediationOption(
        id="x",
        description="read the incident timeline and export it",
        risk=Risk.READ,
        capabilities=["metrics.read"],
    )
    action, _ = policy.classify_plan(RecoveryPlan(options=[option]))
    assert action == "APPROVAL"


@pytest.mark.unit
def test_declared_read_identity_still_authorises() -> None:
    policy = PolicyEngine(POLICY)
    option = RemediationOption(
        id="x",
        description="metrics.read",
        risk=Risk.READ,
        capabilities=[],
    )
    action, _ = policy.classify_plan(RecoveryPlan(options=[option]))
    assert action == "AUTO"


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
    """ADR-013 D3: a registry rule may not downgrade a destructive operation.

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
    """ADR-013 D3 must not break the legitimate allow-listed safe flow."""
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
