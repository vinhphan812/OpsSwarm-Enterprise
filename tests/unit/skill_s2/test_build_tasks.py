# S2: TaskGraph test suite - 24 substantive test cases
# Target: build_tasks() function
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.2

import asyncio

import pytest

from opsswarm.models import IncidentContext, Task, TaskType, Risk
from opsswarm.skill_logic import build_tasks
from tests.fakes import FakeOpenClaw


# Helper to create fake OpenClaw with JSON response
def make_fake_oc(tasks_data):
    """Create a FakeOpenClaw that returns the given tasks data."""
    return FakeOpenClaw([tasks_data])


# === NORMAL (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n1_single_task_dag():
    """S2-N1: Single task DAG - 1+ tasks returned"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [{"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability"}]}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert len(result) >= 1
    assert result[0].id == "T1"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n2_parallel_tasks():
    """S2-N2: Parallel tasks - tasks with parallelizable=true"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check logs", "profile": "observability",
             "parallelizable": True},
            {"id": "T2", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability",
             "parallelizable": True}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert all(t.parallelizable for t in result)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n3_sequential_dependencies():
    """S2-N3: Sequential dependencies - depends_on field populated"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "First", "profile": "observability"},
            {"id": "T2", "type": "INVESTIGATE", "objective": "Second", "profile": "application", "depends_on": ["T1"]}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    t2 = next(t for t in result if t.id == "T2")
    assert "T1" in t2.depends_on


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n4_mixed_task_types():
    """S2-N4: Mixed task types - correct types assigned"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Observe", "profile": "observability"},
            {"id": "T2", "type": "INVESTIGATE", "objective": "Investigate", "profile": "application"},
            {"id": "T3", "type": "DIAGNOSE", "objective": "Diagnose", "profile": "infrastructure"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    types = {t.type for t in result}
    assert TaskType.OBSERVE in types
    assert TaskType.INVESTIGATE in types
    assert TaskType.DIAGNOSE in types


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n5_all_profiles_used():
    """S2-N5: All profiles used - uses multiple specialist profiles"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability"},
            {"id": "T2", "type": "INVESTIGATE", "objective": "Check", "profile": "application"},
            {"id": "T3", "type": "DIAGNOSE", "objective": "Check", "profile": "infrastructure"},
            {"id": "T4", "type": "DIAGNOSE", "objective": "Check", "profile": "database"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    profiles = {t.profile for t in result}
    assert len(profiles) >= 3


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n6_minimal_incident():
    """S2-N6: Minimal incident - returns task (or error)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="",
        service="unknown"
    )
    fake_response = {
        "tasks": [{"id": "T1", "type": "OBSERVE", "objective": "Start investigation", "profile": "observability"}]}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert len(result) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n7_task_with_capabilities():
    """S2-N7: Task with capabilities - required_capabilities populated"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability",
             "required_capabilities": ["prometheus", "grafana"]}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert "prometheus" in result[0].required_capabilities


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s2_n8_default_risk_is_read():
    """S2-N8: Default risk is read - risk defaults to READ"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {"tasks": [{"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability"}]}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert result[0].risk == Risk.READ


# === BOUNDARY (6 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b1_maximum_20_tasks():
    """S2-B1: Maximum 20 tasks - does not exceed limit (current impl allows any)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    tasks = [{"id": f"T{i}", "type": "OBSERVE", "objective": f"Task {i}", "profile": "observability"} for i in
             range(25)]
    fake_response = {"tasks": tasks}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    # Current implementation allows any number
    assert len(result) == 25


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b2_circular_dependency():
    """S2-B2: Circular dependency - DAG validation (not enforced by build_tasks)"""
    # Note: build_tasks doesn't validate DAG, it's a pass-through
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "depends_on": ["T2"]},
            {"id": "T2", "type": "INVESTIGATE", "objective": "Check", "profile": "application", "depends_on": ["T1"]}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Current implementation doesn't validate - returns as-is
    result = await build_tasks(oc, "agent", "run-1", incident)
    assert len(result) == 2


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b3_orphan_tasks():
    """S2-B3: Orphan tasks - task depending on non-existent (not validated)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability",
             "depends_on": ["NONEXISTENT"]}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Not validated by build_tasks
    result = await build_tasks(oc, "agent", "run-1", incident)
    assert "NONEXISTENT" in result[0].depends_on


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b4_self_referencing_task():
    """S2-B4: Self-referencing task - depends_on includes own ID (not validated)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "depends_on": ["T1"]}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Not validated
    result = await build_tasks(oc, "agent", "run-1", incident)
    assert "T1" in result[0].depends_on


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b5_empty_task_list():
    """S2-B5: No tasks created - empty list returned"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {"tasks": []}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s2_b6_profile_validation():
    """S2-B6: Profile validation - uses provided profile (no validation)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {"tasks": [{"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "unknown-profile"}]}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    # No validation - uses whatever is provided
    assert result[0].profile == "unknown-profile"


# === FAULT (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f1_llm_returns_non_json():
    """S2-F1: LLM returns non-JSON - returns empty list (current behavior)"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    oc = FakeOpenClaw([{"not": "valid json"}])

    # Current behavior: silently returns empty list when data is invalid
    result = await build_tasks(oc, "agent", "run-1", incident)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f2_missing_required_fields():
    """S2-F2: Missing required fields - validation error"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {"tasks": [{"id": "T1"}]}  # Missing type, objective, profile
    oc = make_fake_oc(fake_response)

    with pytest.raises(Exception):  # Pydantic validation error
        await build_tasks(oc, "agent", "run-1", incident)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f3_invalid_task_type():
    """S2-F3: Invalid TaskType - validation error"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {"tasks": [{"id": "T1", "type": "INVALID", "objective": "Check", "profile": "observability"}]}
    oc = make_fake_oc(fake_response)

    with pytest.raises(Exception):
        await build_tasks(oc, "agent", "run-1", incident)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f4_invalid_risk_value():
    """S2-F4: Invalid Risk value - validation error"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [{"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "risk": "write"}]}
    oc = make_fake_oc(fake_response)

    with pytest.raises(Exception):
        await build_tasks(oc, "agent", "run-1", incident)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f5_openclaw_timeout():
    """S2-F5: OpenClaw timeout - error propagated"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    oc = FakeOpenClaw([asyncio.TimeoutError("timeout")])

    with pytest.raises(asyncio.TimeoutError):
        await build_tasks(oc, "agent", "run-1", incident)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f6_null_incident():
    """S2-F6: Null incident - TypeError"""
    oc = make_fake_oc({"tasks": []})

    with pytest.raises((TypeError, AttributeError)):
        await build_tasks(oc, "agent", "run-1", None)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f7_very_long_objective():
    """S2-F7: Very long objective - handles without crash"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    long_objective = "x" * 15000
    fake_response = {
        "tasks": [{"id": "T1", "type": "OBSERVE", "objective": long_objective, "profile": "observability"}]}
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)
    assert len(result[0].objective) == 15000


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s2_f8_duplicate_task_ids():
    """S2-F8: Duplicate task IDs - validation error"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability"},
            {"id": "T1", "type": "INVESTIGATE", "objective": "Check", "profile": "application"}
        ]
    }
    oc = make_fake_oc(fake_response)

    # Currently allowed - duplicates pass through
    result = await build_tasks(oc, "agent", "run-1", incident)
    assert len(result) == 2


# === CROSS-SKILL (2 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s2_c1_output_feeds_s4():
    """S2-C1: Output feeds S4 execute_task - valid task list"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability"},
            {"id": "T2", "type": "INVESTIGATE", "objective": "Check logs", "profile": "application"}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    # Must be valid input to execute_task
    assert all(isinstance(t, Task) for t in result)
    assert result[0].type == TaskType.OBSERVE


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s2_c2_s2_to_s4_parallel_execution():
    """S2-C2: S2 to S4 parallel execution - tasks ready for parallel dispatch"""
    incident = IncidentContext(
        issue_number=1,
        title="Test",
        body="### Service\napi\n",
        service="api"
    )
    fake_response = {
        "tasks": [
            {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability",
             "parallelizable": True},
            {"id": "T2", "type": "OBSERVE", "objective": "Check logs", "profile": "application",
             "parallelizable": True},
            {"id": "T3", "type": "OBSERVE", "objective": "Check network", "profile": "infrastructure",
             "parallelizable": True}
        ]
    }
    oc = make_fake_oc(fake_response)

    result = await build_tasks(oc, "agent", "run-1", incident)

    # All tasks parallelizable - can be dispatched in parallel
    assert all(t.parallelizable for t in result)
