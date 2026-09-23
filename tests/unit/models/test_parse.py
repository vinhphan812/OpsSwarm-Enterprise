import pytest

from opsswarm.skill_logic import parse_issue


@pytest.mark.unit
def test_issue_parse():
    issue = {'title': '[Incident] booking fails',
             'body': '## Incident\n\n### Service\nbooking-api\n\n### Symptoms\nHTTP 500\n\n### Customer impact\nCheckout blocked\n\n### Environment\nproduction\n',
             'labels': [{'name': 'opsswarm'}, {'name': 'sev:2'}], 'user': {'login': 'u'}}
    x = parse_issue(12, issue)
    assert x.service == 'booking-api' and x.environment == 'production' and x.severity == 'SEV2'
