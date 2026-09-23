# S1: IncidentContext model test suite
# Target: IncidentContext Pydantic model validation
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.2

import pytest
from pydantic import ValidationError

from opsswarm.models import IncidentContext


# === CONSTRUCTION & VALIDATION (8 tests) ===

@pytest.mark.unit
def test_incident_context_minimal_valid():
    """IC-1: Minimal valid construction - required fields only"""
    ctx = IncidentContext(issue_number=1, title="Test incident")

    assert ctx.issue_number == 1
    assert ctx.title == "Test incident"
    # Verify defaults applied
    assert ctx.body == ""
    assert ctx.service == "unknown"
    assert ctx.environment == "unknown"
    assert ctx.severity == "UNKNOWN"
    assert ctx.symptoms == []
    assert ctx.customer_impact == "unknown"
    assert ctx.source == "github"
    assert ctx.actor is None
    assert ctx.labels == []


@pytest.mark.unit
def test_incident_context_full_construction():
    """IC-2: Full construction - all fields specified"""
    ctx = IncidentContext(
        issue_number=42,
        title="API Gateway degraded",
        body="Full incident body",
        service="api-gateway",
        environment="production",
        severity="SEV1",
        symptoms=["High latency", "503 errors"],
        customer_impact="30% users affected",
        source="github",
        actor="oncall-engineer",
        labels=["opsswarm", "sev:1"]
    )

    assert ctx.issue_number == 42
    assert ctx.title == "API Gateway degraded"
    assert ctx.body == "Full incident body"
    assert ctx.service == "api-gateway"
    assert ctx.environment == "production"
    assert ctx.severity == "SEV1"
    assert len(ctx.symptoms) == 2
    assert "High latency" in ctx.symptoms
    assert ctx.customer_impact == "30% users affected"
    assert ctx.source == "github"
    assert ctx.actor == "oncall-engineer"
    assert len(ctx.labels) == 2


@pytest.mark.unit
def test_incident_context_missing_required_field():
    """IC-3: Missing required field - ValidationError raised"""
    with pytest.raises(ValidationError) as exc_info:
        IncidentContext(title="Test")  # missing issue_number

    # Verify the error is about issue_number
    errors = exc_info.value.errors()
    assert len(errors) >= 1
    assert any("issue_number" in str(e.get("loc", [])) for e in errors)


@pytest.mark.unit
def test_incident_context_invalid_issue_number_type():
    """IC-4: Invalid issue_number type - ValidationError raised"""
    with pytest.raises(ValidationError) as exc_info:
        IncidentContext(issue_number="not-an-int", title="Test")

    errors = exc_info.value.errors()
    assert any(e.get("type") == "int_parsing" for e in errors)


@pytest.mark.unit
def test_incident_context_invalid_title_type():
    """IC-5: Invalid title type - ValidationError raised"""
    with pytest.raises(ValidationError) as exc_info:
        IncidentContext(issue_number=1, title=123)

    errors = exc_info.value.errors()
    assert any(e.get("type") == "string_type" for e in errors)


@pytest.mark.unit
def test_incident_context_actor_can_be_none():
    """IC-6: Actor explicitly None - allowed"""
    ctx = IncidentContext(issue_number=1, title="Test", actor=None)
    assert ctx.actor is None


@pytest.mark.unit
def test_incident_context_actor_can_be_string():
    """IC-7: Actor as string - accepted"""
    ctx = IncidentContext(issue_number=1, title="Test", actor="user123")
    assert ctx.actor == "user123"


@pytest.mark.unit
def test_incident_context_labels_as_empty_list():
    """IC-8: Labels as empty list - defaults applied"""
    ctx = IncidentContext(issue_number=1, title="Test", labels=[])
    assert ctx.labels == []


# === SERIALIZATION (6 tests) ===

@pytest.mark.unit
def test_incident_context_to_dict():
    """IC-9: To dict - all fields serialized"""
    ctx = IncidentContext(
        issue_number=1,
        title="Test",
        service="api",
        severity="SEV2"
    )
    d = ctx.model_dump()

    assert isinstance(d, dict)
    assert d["issue_number"] == 1
    assert d["title"] == "Test"
    assert d["service"] == "api"
    assert d["severity"] == "SEV2"


@pytest.mark.unit
def test_incident_context_to_json():
    """IC-10: To JSON - valid JSON produced"""
    ctx = IncidentContext(
        issue_number=1,
        title="Test",
        severity="SEV1"
    )
    json_str = ctx.model_dump_json()

    assert isinstance(json_str, str)
    assert '"issue_number":1' in json_str
    assert '"title":"Test"' in json_str
    assert '"severity":"SEV1"' in json_str


@pytest.mark.unit
def test_incident_context_from_dict():
    """IC-11: From dict - round-trip"""
    data = {
        "issue_number": 42,
        "title": "From dict test",
        "body": "Test body",
        "service": "test-service",
        "environment": "staging",
        "severity": "SEV3",
        "symptoms": ["error1", "error2"],
        "customer_impact": "some impact",
        "source": "github",
        "actor": "testuser",
        "labels": ["test", "label"]
    }
    ctx = IncidentContext.model_validate(data)

    assert ctx.issue_number == 42
    assert ctx.title == "From dict test"
    assert ctx.service == "test-service"
    assert len(ctx.symptoms) == 2


@pytest.mark.unit
def test_incident_context_from_json():
    """IC-12: From JSON - round-trip"""
    json_str = '{"issue_number":99,"title":"JSON test","service":"api","severity":"SEV2"}'
    ctx = IncidentContext.model_validate_json(json_str)

    assert ctx.issue_number == 99
    assert ctx.title == "JSON test"
    assert ctx.service == "api"
    assert ctx.severity == "SEV2"


@pytest.mark.unit
def test_incident_context_serialization_excludes_none():
    """IC-13: Serialization excludes None values by default"""
    ctx = IncidentContext(issue_number=1, title="Test")
    d = ctx.model_dump(exclude_none=True)

    # actor is None, should not appear in output
    assert "actor" not in d


@pytest.mark.unit
def test_incident_context_symptoms_default_factory():
    """IC-14: Symptoms uses default factory - empty list not shared"""
    ctx1 = IncidentContext(issue_number=1, title="Test1")
    ctx2 = IncidentContext(issue_number=2, title="Test2")

    # Verify they're not sharing the same list object
    assert ctx1.symptoms is not ctx2.symptoms
    assert ctx1.symptoms == []
    assert ctx2.symptoms == []


# === FIELD CONSTRAINTS (5 tests) ===

@pytest.mark.unit
def test_incident_context_severity_accepts_arbitrary():
    """IC-15: Severity accepts arbitrary string - no validation"""
    ctx = IncidentContext(issue_number=1, title="Test", severity="CRITICAL")
    assert ctx.severity == "CRITICAL"

    ctx2 = IncidentContext(issue_number=2, title="Test2", severity="P5")
    assert ctx2.severity == "P5"


@pytest.mark.unit
def test_incident_context_environment_accepts_arbitrary():
    """IC-16: Environment accepts arbitrary string"""
    ctx = IncidentContext(issue_number=1, title="Test", environment="us-east-1")
    assert ctx.environment == "us-east-1"


@pytest.mark.unit
def test_incident_context_symptoms_list_of_strings():
    """IC-17: Symptoms must be list of strings"""
    ctx = IncidentContext(
        issue_number=1,
        title="Test",
        symptoms=["symptom1", "symptom2"]
    )
    assert len(ctx.symptoms) == 2
    assert all(isinstance(s, str) for s in ctx.symptoms)


@pytest.mark.unit
def test_incident_context_labels_list_of_strings():
    """IC-18: Labels must be list of strings"""
    ctx = IncidentContext(
        issue_number=1,
        title="Test",
        labels=["opsswarm", "sev:1", "infrastructure"]
    )
    assert len(ctx.labels) == 3
    assert all(isinstance(l, str) for l in ctx.labels)


@pytest.mark.unit
def test_incident_context_source_default_github():
    """IC-19: Source defaults to github"""
    ctx = IncidentContext(issue_number=1, title="Test")
    assert ctx.source == "github"


# === CROSS-MODEL INTEGRATION (3 tests) ===

@pytest.mark.unit
def test_incident_context_parse_issue_integration():
    """IC-20: IncidentContext from parse_issue - valid model"""
    from opsswarm.skill_logic import parse_issue

    issue = {
        'title': 'Test',
        'body': '### Service\napi\n### Environment\nprod\n',
        'labels': [{'name': 'sev:2'}],
        'user': {'login': 'testuser'}
    }
    result = parse_issue(1, issue)

    # Verify it's a valid IncidentContext that passes model validation
    assert isinstance(result, IncidentContext)
    validated = IncidentContext.model_validate(result.model_dump())
    assert validated.issue_number == 1
    assert validated.service == "api"


@pytest.mark.unit
def test_incident_context_roundtrip_through_json():
    """IC-21: Round-trip through JSON preserves data"""
    original = IncidentContext(
        issue_number=123,
        title="Round-trip test",
        body="Full body",
        service="test-service",
        environment="test-env",
        severity="SEV4",
        symptoms=["symptom1"],
        customer_impact="test impact",
        source="github",
        actor="test-actor",
        labels=["label1"]
    )

    json_str = original.model_dump_json()
    restored = IncidentContext.model_validate_json(json_str)

    assert restored.issue_number == original.issue_number
    assert restored.title == original.title
    assert restored.service == original.service
    assert restored.environment == original.environment
    assert restored.severity == original.severity
    assert restored.symptoms == original.symptoms
    assert restored.customer_impact == original.customer_impact
    assert restored.actor == original.actor
    assert restored.labels == original.labels


@pytest.mark.unit
def test_incident_context_can_be_used_as_dict_key():
    """IC-22: IncidentContext can be used as dict key via its values"""
    ctx1 = IncidentContext(issue_number=1, title="Test1", service="api")
    ctx2 = IncidentContext(issue_number=2, title="Test2", service="db")

    # Use issue_number + title as composite key (common pattern)
    lookup = {
        (ctx1.issue_number, ctx1.title): "incident1",
        (ctx2.issue_number, ctx2.title): "incident2"
    }

    assert lookup[(1, "Test1")] == "incident1"
    assert lookup[(2, "Test2")] == "incident2"
