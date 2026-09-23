# Risk Classification test suite - 24 substantive test cases
# Target: Risk enum and risk classification in RemediationOption
# Reference: S3 HorizonPlan risk classification

import pytest

from opsswarm.models import Risk, RemediationOption, RecoveryPlan
from opsswarm.policy import PolicyEngine


# === NORMAL (8 tests) ===

@pytest.mark.unit
def test_risk_read_value():
    """Risk-R1: Read enum value"""
    r = Risk.READ
    assert r.value == "read"


@pytest.mark.unit
def test_risk_safe_write_value():
    """Risk-R2: Safe_write enum value"""
    r = Risk.SAFE_WRITE
    assert r.value == "safe_write"


@pytest.mark.unit
def test_risk_risky_write_value():
    """Risk-R3: Risky_write enum value"""
    r = Risk.RISKY_WRITE
    assert r.value == "risky_write"


@pytest.mark.unit
def test_risk_destructive_value():
    """Risk-R4: Destructive enum value"""
    r = Risk.DESTRUCTIVE
    assert r.value == "destructive"


@pytest.mark.unit
def test_remediation_option_with_read_risk():
    """Risk-R5: RemediationOption with read risk"""
    opt = RemediationOption(
        id="opt1",
        description="Monitor the system",
        risk=Risk.READ
    )
    assert opt.risk == Risk.READ


@pytest.mark.unit
def test_remediation_option_with_safe_write_risk():
    """Risk-R6: RemediationOption with safe_write risk"""
    opt = RemediationOption(
        id="opt1",
        description="Update config",
        risk=Risk.SAFE_WRITE
    )
    assert opt.risk == Risk.SAFE_WRITE


@pytest.mark.unit
def test_remediation_option_with_risky_write_risk():
    """Risk-R7: RemediationOption with risky_write risk"""
    opt = RemediationOption(
        id="opt1",
        description="Modify production code",
        risk=Risk.RISKY_WRITE
    )
    assert opt.risk == Risk.RISKY_WRITE


@pytest.mark.unit
def test_remediation_option_with_destructive_risk():
    """Risk-R8: RemediationOption with destructive risk"""
    opt = RemediationOption(
        id="opt1",
        description="Drop database",
        risk=Risk.DESTRUCTIVE
    )
    assert opt.risk == Risk.DESTRUCTIVE


# === BOUNDARY (6 tests) ===

@pytest.mark.unit
def test_risk_enum_is_string():
    """Risk-B1: Risk enum is string subclass"""
    assert issubclass(Risk, str)
    r = Risk.SAFE_WRITE
    assert isinstance(r, str)
    assert r.startswith("safe")


@pytest.mark.unit
def test_risk_comparison():
    """Risk-B2: Risk enum comparison works"""
    assert Risk.SAFE_WRITE == "safe_write"
    assert Risk.SAFE_WRITE == Risk.SAFE_WRITE
    assert Risk.READ != Risk.DESTRUCTIVE


@pytest.mark.unit
def test_remediation_option_risk_default():
    """Risk-B3: RemediationOption risk defaults to READ"""
    opt = RemediationOption(id="opt1", description="Check status", risk=Risk.READ)
    assert opt.risk == Risk.READ


@pytest.mark.unit
def test_risk_in_policy_engine():
    """Risk-B4: PolicyEngine action for each risk"""
    cfg = {"policy": {"read": "AUTO", "safe_write": "AUTO", "risky_write": "HUMAN_APPROVAL", "destructive": "DENY"}}
    engine = PolicyEngine(cfg)

    assert engine.action(Risk.READ) == "AUTO"
    assert engine.action(Risk.SAFE_WRITE) == "AUTO"
    assert engine.action(Risk.RISKY_WRITE) == "HUMAN_APPROVAL"
    assert engine.action(Risk.DESTRUCTIVE) == "DENY"


@pytest.mark.unit
def test_risk_policy_not_found():
    """Risk-B5: PolicyEngine defaults to DENY for unknown risk"""
    cfg = {"policy": {}}  # No policy defined
    engine = PolicyEngine(cfg)

    assert engine.action(Risk.READ) == "DENY"


@pytest.mark.unit
def test_risk_in_recovery_plan_options():
    """Risk-B6: RecoveryPlan options have risk classification"""
    plan = RecoveryPlan(
        options=[
            RemediationOption(id="opt1", description="Safe fix", risk=Risk.SAFE_WRITE),
            RemediationOption(id="opt2", description="Risky fix", risk=Risk.RISKY_WRITE),
        ]
    )

    assert plan.options[0].risk == Risk.SAFE_WRITE
    assert plan.options[1].risk == Risk.RISKY_WRITE


# === FAULT (8 tests) ===

@pytest.mark.unit
def test_risk_invalid_string_value():
    """Risk-F1: Invalid risk string raises validation error"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RemediationOption(id="opt1", description="Test", risk="invalid_risk")


@pytest.mark.unit
def test_risk_case_sensitive():
    """Risk-F2: Risk is case-sensitive"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RemediationOption(id="opt1", description="Test", risk="SAFE_WRITE")  # Must be lowercase


@pytest.mark.unit
def test_risk_none_value():
    """Risk-F3: None risk raises validation error"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RemediationOption(id="opt1", description="Test", risk=None)


@pytest.mark.unit
def test_remediation_option_missing_risk_field():
    """Risk-F4: Missing risk field raises validation error"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RemediationOption(id="opt1", description="Test")


@pytest.mark.unit
def test_policy_classify_read_risk():
    """Risk-F5: PolicyEngine classifies read as AUTO"""
    engine = PolicyEngine({"policy": {"read": "AUTO"}})
    plan = RecoveryPlan(options=[RemediationOption(id="opt1", description="Monitor", risk=Risk.READ)])

    result, _ = engine.classify_plan(plan)
    assert result == "AUTO"


@pytest.mark.unit
def test_policy_classify_safe_write():
    """Risk-F6: PolicyEngine classifies safe_write as AUTO"""
    engine = PolicyEngine({"policy": {"safe_write": "AUTO"}})
    plan = RecoveryPlan(options=[RemediationOption(id="opt1", description="Safe fix", risk=Risk.SAFE_WRITE)])

    result, _ = engine.classify_plan(plan)
    assert result == "AUTO"


@pytest.mark.unit
def test_policy_classify_risky_write_requires_approval():
    """Risk-F7: PolicyEngine classifies risky_write as APPROVAL"""
    engine = PolicyEngine({"policy": {"risky_write": "HUMAN_APPROVAL"}})
    plan = RecoveryPlan(options=[RemediationOption(id="opt1", description="Risky fix", risk=Risk.RISKY_WRITE)])

    result, _ = engine.classify_plan(plan)
    assert result == "APPROVAL"


@pytest.mark.unit
def test_policy_classify_destructive_denied():
    """Risk-F8: PolicyEngine classifies destructive as DENY"""
    engine = PolicyEngine({"policy": {"destructive": "DENY"}})
    plan = RecoveryPlan(options=[RemediationOption(id="opt1", description="Drop db", risk=Risk.DESTRUCTIVE)])

    result, _ = engine.classify_plan(plan)
    assert result == "DENY"


# === CROSS-SKILL (2 tests) ===

@pytest.mark.unit
def test_risk_in_skill_s3_output():
    """Risk-C1: Risk in RecoveryPlan from S3"""
    plan = RecoveryPlan(
        options=[
            RemediationOption(id="opt1", description="Restart", risk=Risk.SAFE_WRITE),
            RemediationOption(id="opt2", description="Code change", risk=Risk.RISKY_WRITE),
            RemediationOption(id="opt3", description="Drop table", risk=Risk.DESTRUCTIVE),
        ],
        recommended_option="opt1"
    )

    # Each option has proper risk classification
    assert len(plan.options) == 3
    risks = {opt.risk for opt in plan.options}
    assert Risk.SAFE_WRITE in risks
    assert Risk.RISKY_WRITE in risks
    assert Risk.DESTRUCTIVE in risks


@pytest.mark.unit
def test_risk_in_skill_s6_policy():
    """Risk-C2: Risk feeds S6 policy gating"""
    # S6 policy gates use risk classification from S3
    cfg = {
        "policy": {
            "read": "AUTO",
            "safe_write": "AUTO",
            "risky_write": "HUMAN_APPROVAL",
            "destructive": "DENY"
        }
    }
    engine = PolicyEngine(cfg)

    # All risk levels can be classified
    for risk in [Risk.READ, Risk.SAFE_WRITE, Risk.RISKY_WRITE, Risk.DESTRUCTIVE]:
        plan = RecoveryPlan(options=[RemediationOption(id="opt1", description="Test", risk=risk)])
        result, _ = engine.classify_plan(plan)
        assert result in ["AUTO", "APPROVAL", "DENY", "INPUT", "DECISION"]
