from opsswarm.policy import PolicyEngine
from opsswarm.models import *

def engine(): return PolicyEngine({'policy':{'read':'AUTO','safe_write':'AUTO','risky_write':'HUMAN_APPROVAL','destructive':'DENY'}})

def test_single_safe_auto():
    p=RecoveryPlan(options=[RemediationOption(id='x',description='safe',risk=Risk.SAFE_WRITE)])
    assert engine().classify_plan(p)[0]=='AUTO'

def test_risky_requires_approval():
    p=RecoveryPlan(options=[RemediationOption(id='x',description='restart',risk=Risk.RISKY_WRITE)])
    assert engine().classify_plan(p)[0]=='APPROVAL'

def test_multiple_is_decision():
    p=RecoveryPlan(options=[RemediationOption(id='a',description='a',risk=Risk.SAFE_WRITE),RemediationOption(id='b',description='b',risk=Risk.SAFE_WRITE)])
    assert engine().classify_plan(p)[0]=='DECISION'

def test_destructive_denied():
    p=RecoveryPlan(options=[RemediationOption(id='x',description='drop',risk=Risk.DESTRUCTIVE)])
    assert engine().classify_plan(p)[0]=='DENY'
