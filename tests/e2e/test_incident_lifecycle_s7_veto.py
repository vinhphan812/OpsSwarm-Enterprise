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
async def test_incident_lifecycle_s7_veto(tmp_path, cfg, issue):
    responses = investigation_and_rca() + [
        {'options': [{'id': 'fix', 'description': 'fix it', 'profile': 'recovery-responder', 'risk': 'safe_write'}], 'recommended_option': 'fix'},
        {'option_id': 'fix', 'success': True, 'summary': 'fixed', 'evidence': ['r1'], 'ambiguous': False, 'raw': {}},
        {'verified': False, 'summary': 'fail'}
    ]
    gh = FakeGitHub(issue);
    oc = FakeOpenClaw(responses);
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    await eng.start_issue(1)
    assert gh.closed == []
