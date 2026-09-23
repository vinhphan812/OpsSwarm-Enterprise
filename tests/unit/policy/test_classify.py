import pytest

from opsswarm.models import *
from opsswarm.policy import PolicyEngine


def engine(): return PolicyEngine(
    {'policy': {'read': 'AUTO', 'safe_write': 'AUTO', 'risky_write': 'HUMAN_APPROVAL', 'destructive': 'DENY'}})


@pytest.mark.unit
def test_single_safe_auto():
    p = RecoveryPlan(options=[RemediationOption(id='x', description='safe', risk=Risk.SAFE_WRITE)])
    assert engine().classify_plan(p)[0] == 'AUTO'


@pytest.mark.unit
def test_risky_requires_approval():
    p = RecoveryPlan(options=[RemediationOption(id='x', description='restart', risk=Risk.RISKY_WRITE)])
    assert engine().classify_plan(p)[0] == 'APPROVAL'


@pytest.mark.unit
def test_multiple_is_decision():
    p = RecoveryPlan(options=[RemediationOption(id='a', description='a', risk=Risk.SAFE_WRITE),
                              RemediationOption(id='b', description='b', risk=Risk.SAFE_WRITE)])
    assert engine().classify_plan(p)[0] == 'DECISION'


@pytest.mark.unit
def test_destructive_denied():
    p = RecoveryPlan(options=[RemediationOption(id='x', description='drop', risk=Risk.DESTRUCTIVE)])
    assert engine().classify_plan(p)[0] == 'DENY'
