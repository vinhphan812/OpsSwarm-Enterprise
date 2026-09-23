import pytest
import yaml

from opsswarm.models import RunState
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw
from tests.integration.orchestrator.test_flows import investigation_and_rca

@pytest.fixture
def cfg(): return yaml.safe_load(open('config/test.yaml'))

@pytest.fixture
def issue(): return {'number': 1, 'title': '[Incident] booking fails',
                     'body': '## Incident\n\n### Service\nbooking-api\n\n### Symptoms\nHTTP 500\n\n### Customer impact\nCheckout blocked\n\n### Environment\nproduction\n',
                     'labels': [{'name': 'opsswarm'}, {'name': 'sev:2'}], 'user': {'login': 'dev'}}

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_incident_lifecycle_safe(tmp_path, cfg, issue):
    responses = investigation_and_rca() + [
        {'options': [
            {'id': 'refresh', 'description': 'refresh cache', 'profile': 'recovery-responder', 'risk': 'safe_write',
             'estimated_recovery': '1m', 'rationale': 'safe', 'capabilities': ['cache.refresh']}],
            'recommended_option': 'refresh', 'confidence': 0.9, 'requires_business_input': False,
            'business_input_question': None},
        {'option_id': 'refresh', 'success': True, 'summary': 'cache refreshed', 'evidence': ['receipt:1'],
         'ambiguous': False, 'raw': {}},
        {'verified': True, 'summary': 'service healthy', 'evidence': ['sli:ok'], 'confidence': 0.99, 'raw': {}},
    ]
    gh = FakeGitHub(issue);
    oc = FakeOpenClaw(responses);
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    r = await eng.start_issue(1)
    assert r.state == RunState.RESOLVED and gh.closed == [1]
