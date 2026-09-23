import pytest

from opsswarm.openclaw import OpenClawClient


@pytest.mark.unit
def test_json_parser_plain_and_fenced():
    assert OpenClawClient._extract_json('{"a":1}') == {'a': 1}
    assert OpenClawClient._extract_json('```json\n{"a":2}\n```') == {'a': 2}
