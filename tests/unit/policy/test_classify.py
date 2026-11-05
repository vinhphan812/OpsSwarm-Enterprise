import pytest

from opsswarm.models import RecoveryPlan, RemediationOption, Risk
from opsswarm.policy import PolicyEngine


def engine():
    return PolicyEngine(
        {
            "policy": {
                "read": "AUTO",
                "safe_write": "AUTO",
                "risky_write": "HUMAN_APPROVAL",
                "destructive": "DENY",
            }
        }
    )


@pytest.mark.unit
def test_single_safe_auto():
    # ADR-013 D3: autonomous execution requires a declared operation identity.
    p = RecoveryPlan(
        options=[RemediationOption(id="x", description="cache.refresh", risk=Risk.SAFE_WRITE)]
    )
    assert engine().classify_plan(p)[0] == "AUTO"


@pytest.mark.unit
def test_single_undeclared_operation_requires_approval():
    """ADR-013 D3: a model risk label alone never authorises autonomous execution."""
    p = RecoveryPlan(options=[RemediationOption(id="x", description="safe", risk=Risk.SAFE_WRITE)])
    assert engine().classify_plan(p)[0] == "APPROVAL"


@pytest.mark.unit
def test_risky_requires_approval():
    p = RecoveryPlan(
        options=[RemediationOption(id="x", description="restart", risk=Risk.RISKY_WRITE)]
    )
    assert engine().classify_plan(p)[0] == "APPROVAL"


@pytest.mark.unit
def test_multiple_is_decision():
    p = RecoveryPlan(
        options=[
            RemediationOption(id="a", description="a", risk=Risk.SAFE_WRITE),
            RemediationOption(id="b", description="b", risk=Risk.SAFE_WRITE),
        ]
    )
    assert engine().classify_plan(p)[0] == "DECISION"


@pytest.mark.unit
def test_destructive_denied():
    p = RecoveryPlan(options=[RemediationOption(id="x", description="drop", risk=Risk.DESTRUCTIVE)])
    assert engine().classify_plan(p)[0] == "DENY"
