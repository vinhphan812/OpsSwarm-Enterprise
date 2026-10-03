"""Coverage-targeted tests for opsswarm/policy.py uncovered branches.

Exercises:
- classify_plan() branches: INPUT (requires_business_input=True),
  DENY (no options), DECISION (multiple options), AUTO, APPROVAL, DENY (policy deny)
- resolve_effective_risk_plan(): option path, no-option path
- _resolve_registry_path(): empty/None path, absolute path, relative path
"""

import pytest

from opsswarm.models import Risk, RecoveryPlan, RemediationOption
from opsswarm.policy import PolicyEngine, _resolve_registry_path


# -----------------------------------------------------------------------
# classify_plan() branches
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_classify_plan_input_branch():
    """Branches lines 43-44: requires_business_input=True returns INPUT."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(
        requires_business_input=True,
        business_input_question="Which rollout strategy?",
        options=[],
    )
    code, msg = eng.classify_plan(plan)
    assert code == "INPUT"
    assert "Which rollout strategy?" in msg


@pytest.mark.unit
def test_classify_plan_input_default_message():
    """Branches lines 43-44: requires_business_input=True with None question."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(
        requires_business_input=True,
        business_input_question=None,
        options=[],
    )
    code, msg = eng.classify_plan(plan)
    assert code == "INPUT"
    assert "Business input required" in msg


@pytest.mark.unit
def test_classify_plan_no_options_denied():
    """Branches lines 45-46: empty options returns DENY."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(options=[])
    code, msg = eng.classify_plan(plan)
    assert code == "DENY"
    assert "No remediation options" in msg


@pytest.mark.unit
def test_classify_plan_multiple_options_decision():
    """Branches lines 47-48: multiple options returns DECISION."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(
        options=[
            RemediationOption(id="a", description="restart", risk=Risk.SAFE_WRITE),
            RemediationOption(id="b", description="rollback", risk=Risk.SAFE_WRITE),
        ]
    )
    code, msg = eng.classify_plan(plan)
    assert code == "DECISION"
    assert "Multiple" in msg


@pytest.mark.unit
def test_classify_plan_single_auto():
    """Branches lines 49-52: single option with AUTO policy returns AUTO."""
    eng = PolicyEngine(
        {"policy": {"safe_write": "AUTO"}}
    )
    plan = RecoveryPlan(
        options=[RemediationOption(id="x", description="safe", risk=Risk.SAFE_WRITE)]
    )
    code, msg = eng.classify_plan(plan)
    assert code == "AUTO"


@pytest.mark.unit
def test_classify_plan_single_approval():
    """Branches lines 53-54: single option with HUMAN_APPROVAL returns APPROVAL."""
    eng = PolicyEngine(
        {"policy": {"risky_write": "HUMAN_APPROVAL"}}
    )
    plan = RecoveryPlan(
        options=[RemediationOption(id="x", description="risky", risk=Risk.RISKY_WRITE)]
    )
    code, msg = eng.classify_plan(plan)
    assert code == "APPROVAL"


@pytest.mark.unit
def test_classify_plan_single_deny():
    """Branches line 55: single option with DENY policy returns DENY."""
    eng = PolicyEngine(
        {"policy": {"destructive": "DENY"}}
    )
    plan = RecoveryPlan(
        options=[RemediationOption(id="x", description="drop", risk=Risk.DESTRUCTIVE)]
    )
    code, msg = eng.classify_plan(plan)
    assert code == "DENY"
    assert "destructive" in msg.lower()


# -----------------------------------------------------------------------
# resolve_effective_risk_plan()
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_resolve_effective_risk_plan_with_option():
    """Branches line 145-150: plan with options uses first/recommended option."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(
        options=[
            RemediationOption(id="opt-a", description="restart", risk=Risk.SAFE_WRITE),
            RemediationOption(id="opt-b", description="rollback", risk=Risk.RISKY_WRITE),
        ],
        recommended_option="opt-b",
    )
    eff, rr, cr = eng.resolve_effective_risk_plan(plan, Risk.READ)
    # "rollback" → no registry → classify → RISKY_WRITE → escalation
    assert eff == Risk.RISKY_WRITE
    assert rr is None


@pytest.mark.unit
def test_resolve_effective_risk_plan_empty_options():
    """Branches line 151: empty options falls back to model risk."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(options=[])
    eff, rr, cr = eng.resolve_effective_risk_plan(plan, Risk.RISKY_WRITE)
    assert eff == Risk.RISKY_WRITE


@pytest.mark.unit
def test_resolve_effective_risk_plan_no_recommended_uses_first():
    """Branches line 148: no recommended_option uses first option."""
    eng = PolicyEngine({})
    plan = RecoveryPlan(
        options=[RemediationOption(id="first", description="restart", risk=Risk.SAFE_WRITE)]
    )
    eff, rr, cr = eng.resolve_effective_risk_plan(plan, Risk.RISKY_WRITE)
    # "restart" → no registry → classify → RISKY_WRITE (order 1) > model RISKY_WRITE (order 1)
    # → no escalation → result = model RISKY_WRITE
    assert eff == Risk.RISKY_WRITE


# -----------------------------------------------------------------------
# _resolve_registry_path()
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_resolve_registry_path_empty_string():
    """Branches line 168-169: empty string returns None."""
    result = _resolve_registry_path("")
    assert result is None


@pytest.mark.unit
def test_resolve_registry_path_none():
    """Branches line 168-169: None returns None."""
    result = _resolve_registry_path(None)
    assert result is None


@pytest.mark.unit
def test_resolve_registry_path_absolute():
    """Branches lines 171-172: absolute path returned as-is."""
    result = _resolve_registry_path("D:/some/abs/path.yaml")
    # Path might be normalized on Windows (forward slashes → backslashes)
    assert "abs" in result and "path.yaml" in result


@pytest.mark.unit
def test_resolve_registry_path_relative():
    """Branches line 173: relative path returned as-is (resolved from cwd)."""
    result = _resolve_registry_path("config/registry.yaml")
    assert "registry.yaml" in result


# -----------------------------------------------------------------------
# action() — existing but add explicit branch coverage
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_action_unknown_risk_defaults_to_deny():
    """action() returns 'DENY' for unmapped risk values (cfg.get default)."""
    eng = PolicyEngine({})
    # Risk.READ maps to "read" → not in empty cfg → defaults to "DENY"
    assert eng.action(Risk.READ) == "DENY"
