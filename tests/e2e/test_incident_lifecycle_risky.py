import pytest
import yaml

from opsswarm.models import RunState
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw
from tests.integration.orchestrator.test_flows import investigation_and_rca
from opsswarm.commands import parse_command

@pytest.fixture
def cfg(): return yaml.safe_load(open('config/test.yaml'))

@pytest.fixture
def issue(): return {'number': 1, 'title': '[Incident] booking fails',
                     'body': '## Incident',
                     'labels': [{'name': 'opsswarm'}, {'name': 'sev:2'}], 'user': {'login': 'dev'}}

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_incident_lifecycle_risky(tmp_path, cfg, issue):
    responses = investigation_and_rca() + [
        {'options': [
            {'id': 'rollback', 'description': 'rollback', 'profile': 'recovery-responder', 'risk': 'risky_write',
             'estimated_recovery': '3m', 'rationale': 'best', 'capabilities': ['deploy.rollback']}],
            'recommended_option': 'rollback', 'confidence': 0.9, 'requires_business_input': False},
        {'option_id': 'rollback', 'success': True, 'summary': 'rolled back', 'evidence': ['receipt:2'],
         'ambiguous': False, 'raw': {}},
        {'verified': True, 'summary': 'service restored', 'evidence': ['sli:ok'], 'confidence': 0.98, 'raw': {}},
    ]
    gh = FakeGitHub(issue);
    oc = FakeOpenClaw(responses);
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    r = await eng.start_issue(1);
    assert r.state == RunState.WAITING_APPROVAL and not gh.closed
    await eng.handle_comment(1, 'dev', '/opsswarm approve rollback', 'maintain',
                             parse_command('/opsswarm approve rollback'))
    assert r.state == RunState.RESOLVED and gh.closed == [1]
