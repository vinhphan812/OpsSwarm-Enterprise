import pytest
import yaml
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw
from tests.integration.orchestrator.test_flows import investigation_and_rca

@pytest.fixture
def cfg(): return yaml.safe_load(open('config/test.yaml'))

@pytest.fixture
def issue(): return {'number': 1, 'title': '[Incident] fails', 'body': '...',
                     'labels': [{'name': 'opsswarm'}], 'user': {'login': 'dev'}}

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_incident_lifecycle_rejected(tmp_path, cfg, issue):
    responses = investigation_and_rca() + [
            {'options': [{'id': 'rollback', 'description': 'rollback', 'profile': 'recovery-responder', 'risk': 'risky_write'}], 'recommended_option': 'rollback',
             'requires_business_input': True, 'business_input_question': 'Approve?'}
        ]
    gh = FakeGitHub(issue);
    oc = FakeOpenClaw(responses);
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    await eng.start_issue(1)
    await eng.handle_comment(1, 'dev', '/opsswarm reject rollback', 'maintain', None)
    assert gh.closed == []
