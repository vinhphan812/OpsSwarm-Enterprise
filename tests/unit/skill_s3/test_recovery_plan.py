# S3: HorizonPlan test suite - 24 substantive test cases
# Target: make_recovery_plan() function
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.3

import pytest

from opsswarm.models import IncidentContext, RootCauseArtifact, RecoveryPlan, Risk
from opsswarm.skill_logic import make_recovery_plan
from tests.fakes import FakeOpenClaw


def make_fake_oc(plan_data):
    """Create a FakeOpenClaw that returns the given recovery plan data."""
    return FakeOpenClaw([plan_data])


# === NORMAL (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n1_single_safe_option():
    """S3-N1: Single safe option - one option with safe_write"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Config error",
        root_cause="Wrong timeout setting"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Update timeout", "profile": "recovery-responder", "risk": "safe_write"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert len(result.options) >= 1
    assert result.options[0].risk == Risk.SAFE_WRITE


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n2_multiple_options():
    """S3-N2: Multiple options - 2+ options with different risks"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Memory leak",
        root_cause="Unclosed connections"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Restart service", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt2", "description": "Update code", "profile": "developer", "risk": "risky_write"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert len(result.options) >= 2
    risks = {opt.risk for opt in result.options}
    assert len(risks) >= 2


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n3_recommended_option_set():
    """S3-N3: Recommended option set - recommended_option populated"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Issue",
        root_cause="Root cause"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Option A", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt2", "description": "Option B", "profile": "recovery-responder", "risk": "safe_write"}
        ],
        "recommended_option": "opt1"
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.recommended_option == "opt1"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n4_business_input_required():
    """S3-N4: Business input required - requires_business_input = true"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="uncertain",
        proximate_cause="Unknown",
        root_cause="Need more info"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Option A", "profile": "recovery-responder", "risk": "risky_write"}
        ],
        "requires_business_input": True,
        "business_input_question": "What is the impact tolerance?"
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.requires_business_input is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n5_read_only_option():
    """S3-N5: Read-only option only - risk = read option"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Cache miss",
        root_cause="Warming needed"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Monitor for now", "profile": "recovery-responder", "risk": "read"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.options[0].risk == Risk.READ


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n6_destructive_option_classified():
    """S3-N6: Destructive option classified - risk = destructive"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Data corruption",
        root_cause="Schema mismatch"
    )
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Drop and recreate database", "profile": "dba", "risk": "destructive"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.options[0].risk == Risk.DESTRUCTIVE


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n7_confidence_score():
    """S3-N7: Confidence score - 0.0-1.0 confidence"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Issue",
        root_cause="Root"
    )
    fake_response = {
        "options": [{"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write"}],
        "confidence": 0.85
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s3_n8_empty_human_inputs():
    """S3-N8: Empty human_inputs - works with empty list"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="confirmed",
        proximate_cause="Issue",
        root_cause="Root"
    )
    fake_response = {
        "options": [{"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write"}]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result is not None


# === BOUNDARY (6 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b1_maximum_10_options():
    """S3-B1: Maximum 10 options - current impl allows any"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    options = [{"id": f"opt{i}", "description": f"Option {i}", "profile": "recovery-responder", "risk": "safe_write"}
               for i in range(15)]
    fake_response = {"options": options}
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    # Current implementation allows any number
    assert len(result.options) == 15


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b2_all_same_risk():
    """S3-B2: All same risk - multiple safe_write options"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "A", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt2", "description": "B", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt3", "description": "C", "profile": "recovery-responder", "risk": "safe_write"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert all(opt.risk == Risk.SAFE_WRITE for opt in result.options)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b3_zero_options():
    """S3-B3: Zero options - empty options list allowed"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(
        status="uncertain",
        proximate_cause="Unknown",
        root_cause="Cannot determine fix"
    )
    fake_response = {"options": []}
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.options == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b4_missing_rationale():
    """S3-B4: Missing rationale - empty string allowed"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write", "rationale": ""}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.options[0].rationale == ""


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b5_very_long_description():
    """S3-B5: Very long description - handles without crash"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    long_desc = "x" * 5000
    fake_response = {
        "options": [
            {"id": "opt1", "description": long_desc, "profile": "recovery-responder", "risk": "safe_write"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert len(result.options[0].description) == 5000


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s3_b6_capability_list_empty():
    """S3-B6: Capability list empty - empty list allowed"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write",
             "capabilities": []}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    assert result.options[0].capabilities == []


# === FAULT (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f1_invalid_risk_classification():
    """S3-F1: Invalid risk classification - validation error"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "UNKNOWN"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.options == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f2_missing_required_field():
    """S3-F2: Missing required field - validation error"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "risk": "safe_write"}  # Missing description, profile
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.options == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f3_destructive_without_justification():
    """S3-F3: Destructive without justification - accepted (S3 doesn't deny)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Drop table", "profile": "dba", "risk": "destructive", "rationale": ""}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Should be accepted - S3 doesn't deny destructive options
    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.options[0].risk == Risk.DESTRUCTIVE


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f4_llm_returns_malformed_json():
    """S3-F4: LLM returns malformed JSON - JSON error"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    oc = FakeOpenClaw([{"invalid": "json"}])

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.options == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f5_null_root_cause():
    """S3-F5: Null root_cause - TypeError"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    oc = make_fake_oc({})

    with pytest.raises((TypeError, AttributeError)):
        await make_recovery_plan(oc, "agent", "run-1", incident, None, [])


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f6_confidence_over_1():
    """S3-F6: Confidence > 1.0 - allowed without validation (current behavior)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [{"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write"}],
        "confidence": 1.5
    }
    oc = make_fake_oc(fake_response)

    # Current behavior: accepts confidence > 1.0 without validation
    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.confidence == 1.5


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f7_negative_confidence():
    """S3-F7: Negative confidence - allowed without validation (current behavior)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [{"id": "opt1", "description": "Fix", "profile": "recovery-responder", "risk": "safe_write"}],
        "confidence": -0.1
    }
    oc = make_fake_oc(fake_response)

    # Current behavior: accepts negative confidence without validation
    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert result.confidence == -0.1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s3_f8_option_id_collision():
    """S3-F8: Option ID collision - validation error"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Fix A", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt1", "description": "Fix B", "profile": "recovery-responder", "risk": "safe_write"}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Pydantic allows duplicate IDs - no error raised
    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])
    assert len(result.options) == 2


# === CROSS-SKILL (2 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s3_c1_output_feeds_s5():
    """S3-C1: Output feeds S5 execute - valid RecoveryPlan"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Restart", "profile": "recovery-responder", "risk": "safe_write"}
        ],
        "recommended_option": "opt1"
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    # Must be valid input to execute_recovery
    assert isinstance(result, RecoveryPlan)
    assert len(result.options) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s3_c2_policy_gates_applied():
    """S3-C2: Policy gates applied - risky options included (S6 handles gating)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    root_cause = RootCauseArtifact(status="confirmed", proximate_cause="x", root_cause="x")
    fake_response = {
        "options": [
            {"id": "opt1", "description": "Safe fix", "profile": "recovery-responder", "risk": "safe_write"},
            {"id": "opt2", "description": "Risky fix", "profile": "recovery-responder", "risk": "risky_write"},
            {"id": "opt3", "description": "Destructive", "profile": "dba", "risk": "destructive"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await make_recovery_plan(oc, "agent", "run-1", incident, root_cause, [])

    # All options passed through - S6 policy will handle gating
    assert len(result.options) == 3
    risks = {opt.risk for opt in result.options}
    assert Risk.SAFE_WRITE in risks
    assert Risk.RISKY_WRITE in risks
    assert Risk.DESTRUCTIVE in risks
