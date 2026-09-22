import yaml, pytest
from opsswarm.orchestrator import Orchestrator
from opsswarm.commands import parse_command
from opsswarm.models import RunState
from tests.fakes import FakeGitHub, FakeOpenClaw

@pytest.fixture
def cfg(): return yaml.safe_load(open('config/test.yaml'))

@pytest.fixture
def issue(): return {'number':1,'title':'[Incident] booking fails','body':'## Incident\n\n### Service\nbooking-api\n\n### Symptoms\nHTTP 500\n\n### Customer impact\nCheckout blocked\n\n### Environment\nproduction\n','labels':[{'name':'opsswarm'},{'name':'sev:2'}],'user':{'login':'dev'}}


def investigation_and_rca():
    return [
      {'tasks':[{'id':'T1','type':'OBSERVE','objective':'inspect metrics','profile':'observability-investigator','required_capabilities':['metrics.read'],'risk':'read','depends_on':[],'parallelizable':True,'expected_output':'Finding','status':'PENDING'}]},
      {'task_id':'T1','finding':'errors rose after deploy','evidence':['metric:5xx','deploy:v3'],'hypothesis':'bad deploy','confidence':0.95,'recommended_next_action':'rollback','raw':{}},
      {'status':'confirmed','proximate_cause':'bad deploy','root_cause':'missing regression gate','causal_chain':['v3 deploy','connection leak','5xx'],'evidence_refs':['metric:5xx','deploy:v3'],'confidence':0.93,'remediation_options':['rollback'],'human_input_question':None,'corrective_actions':['add regression gate']},
    ]

@pytest.mark.asyncio
async def test_safe_auto_resolves(tmp_path,cfg,issue):
    responses=investigation_and_rca()+[
      {'options':[{'id':'refresh','description':'refresh cache','profile':'recovery-responder','risk':'safe_write','estimated_recovery':'1m','rationale':'safe','capabilities':['cache.refresh']}],'recommended_option':'refresh','confidence':0.9,'requires_business_input':False,'business_input_question':None},
      {'option_id':'refresh','success':True,'summary':'cache refreshed','evidence':['receipt:1'],'ambiguous':False,'raw':{}},
      {'verified':True,'summary':'service healthy','evidence':['sli:ok'],'confidence':0.99,'raw':{}},
    ]
    gh=FakeGitHub(issue); oc=FakeOpenClaw(responses); eng=Orchestrator(cfg,gh,oc,str(tmp_path))
    r=await eng.start_issue(1)
    assert r.state==RunState.RESOLVED and gh.closed==[1]

@pytest.mark.asyncio
async def test_risky_pauses_then_approval_resolves(tmp_path,cfg,issue):
    responses=investigation_and_rca()+[
      {'options':[{'id':'rollback','description':'rollback','profile':'recovery-responder','risk':'risky_write','estimated_recovery':'3m','rationale':'best','capabilities':['deploy.rollback']}],'recommended_option':'rollback','confidence':0.9,'requires_business_input':False,'business_input_question':None},
      {'option_id':'rollback','success':True,'summary':'rolled back','evidence':['receipt:2'],'ambiguous':False,'raw':{}},
      {'verified':True,'summary':'service restored','evidence':['sli:ok'],'confidence':0.98,'raw':{}},
    ]
    gh=FakeGitHub(issue); oc=FakeOpenClaw(responses); eng=Orchestrator(cfg,gh,oc,str(tmp_path))
    r=await eng.start_issue(1); assert r.state==RunState.WAITING_APPROVAL and not gh.closed
    await eng.handle_comment(1,'dev','/opsswarm approve rollback','maintain',parse_command('/opsswarm approve rollback'))
    assert r.state==RunState.RESOLVED and gh.closed==[1]

@pytest.mark.asyncio
async def test_free_text_never_approves(tmp_path,cfg,issue):
    responses=investigation_and_rca()+[
      {'options':[{'id':'rollback','description':'rollback','profile':'recovery-responder','risk':'risky_write','estimated_recovery':'3m','rationale':'best','capabilities':[]}],'recommended_option':'rollback','confidence':0.9,'requires_business_input':False,'business_input_question':None},
    ]
    gh=FakeGitHub(issue); oc=FakeOpenClaw(responses); eng=Orchestrator(cfg,gh,oc,str(tmp_path))
    r=await eng.start_issue(1); n=len(oc.calls)
    await eng.handle_comment(1,'dev','rollback looks fine','maintain',None)
    assert r.state==RunState.WAITING_APPROVAL and len(oc.calls)==n

@pytest.mark.asyncio
async def test_readonly_user_cannot_approve(tmp_path,cfg,issue):
    responses=investigation_and_rca()+[
      {'options':[{'id':'rollback','description':'rollback','profile':'recovery-responder','risk':'risky_write','estimated_recovery':'3m','rationale':'best','capabilities':[]}],'recommended_option':'rollback','confidence':0.9,'requires_business_input':False,'business_input_question':None},
    ]
    gh=FakeGitHub(issue); oc=FakeOpenClaw(responses); eng=Orchestrator(cfg,gh,oc,str(tmp_path)); r=await eng.start_issue(1)
    with pytest.raises(PermissionError): await eng.handle_comment(1,'reader','/opsswarm approve rollback','read',parse_command('/opsswarm approve rollback'))
    assert r.state==RunState.WAITING_APPROVAL
