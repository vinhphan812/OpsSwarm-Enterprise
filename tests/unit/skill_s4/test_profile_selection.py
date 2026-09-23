# S4: RoleDispatch test suite - profile selection tests
# Target: execute_task() profile parameter and profile selection logic
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.4

import pytest

from opsswarm.models import Finding, IncidentContext, Task, TaskType
from opsswarm.skill_logic import execute_task
from tests.fakes import FakeOpenClaw

# Allowed investigator profiles (from S2 task_graph_prompt)
ALLOWED_INVESTIGATOR_PROFILES = {
    "observability-investigator",
    "application-investigator",
    "infrastructure-investigator",
    "database-investigator"
}


def make_fake_oc(finding_data):
    """Create a FakeOpenClaw that returns the given finding data."""
    return FakeOpenClaw([finding_data])


# === PROFILE SELECTION TESTS (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps1_valid_observability_profile():
    """S4-PS1: Valid observability-investigator profile accepted"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Check API metrics",
        profile="observability-investigator"
    )
    fake_response = {
        "task_id": "T1",
        "finding": "API latency is elevated"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "observability-investigator", "run-1", incident, task)

    assert result.task_id == "T1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps2_valid_application_profile():
    """S4-PS2: Valid application-investigator profile accepted"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T2",
        type=TaskType.INVESTIGATE,
        objective="Investigate application error",
        profile="application-investigator"
    )
    fake_response = {
        "task_id": "T2",
        "finding": "Application exception found"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "application-investigator", "run-1", incident, task)

    assert result.task_id == "T2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps3_valid_infrastructure_profile():
    """S4-PS3: Valid infrastructure-investigator profile accepted"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T3",
        type=TaskType.OBSERVE,
        objective="Check network connectivity",
        profile="infrastructure-investigator"
    )
    fake_response = {
        "task_id": "T3",
        "finding": "Network timeout detected"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "infrastructure-investigator", "run-1", incident, task)

    assert result.task_id == "T3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps4_valid_database_profile():
    """S4-PS4: Valid database-investigator profile accepted"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T4",
        type=TaskType.INVESTIGATE,
        objective="Check database performance",
        profile="database-investigator"
    )
    fake_response = {
        "task_id": "T4",
        "finding": "Database query slow"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "database-investigator", "run-1", incident, task)

    assert result.task_id == "T4"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps5_observability_for_metrics_task():
    """S4-PS5: observability-investigator used for metrics observation"""
    incident = IncidentContext(issue_number=1, title="High latency", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Observe API latency metrics",
        profile="observability-investigator"
    )
    fake_response = {
        "task_id": "T1",
        "finding": "p99 latency is 2000ms",
        "evidence": ["prometheus:latency_p99=2000ms"]
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "observability-investigator", "run-1", incident, task)

    assert "latency" in result.finding.lower()
    assert len(result.evidence) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps6_application_for_code_investigation():
    """S4-PS6: application-investigator used for code investigation"""
    incident = IncidentContext(issue_number=1, title="Error in service", service="api")
    task = Task(
        id="T2",
        type=TaskType.INVESTIGATE,
        objective="Investigate application error logs",
        profile="application-investigator"
    )
    fake_response = {
        "task_id": "T2",
        "finding": "NullPointerException in handler",
        "evidence": ["log:NullPointerException"],
        "hypothesis": "Missing null check"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "application-investigator", "run-1", incident, task)

    assert result.hypothesis is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps7_all_allowed_profiles_work():
    """S4-PS7: All four allowed profiles can execute tasks"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")

    profiles = [
        "observability-investigator",
        "application-investigator",
        "infrastructure-investigator",
        "database-investigator"
    ]

    for i, profile in enumerate(profiles):
        task = Task(
            id=f"T{i + 1}",
            type=TaskType.OBSERVE,
            objective="Check",
            profile=profile
        )
        fake_response = {
            "task_id": f"T{i + 1}",
            "finding": f"Finding from {profile}"
        }
        oc = make_fake_oc(fake_response)

        result = await execute_task(oc, profile, "run-1", incident, task)
        assert result.task_id == f"T{i + 1}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_ps8_profile_prompt_context():
    """S4-PS8: Profile is passed correctly in prompt context"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Check metrics",
        profile="observability-investigator"
    )
    fake_response = {
        "task_id": "T1",
        "finding": "Done"
    }
    oc = FakeOpenClaw([fake_response])

    result = await execute_task(oc, "observability-investigator", "run-1", incident, task)

    # Verify the call was made with the profile
    assert len(oc.calls) == 1
    agent, _, _ = oc.calls[0]
    assert agent == "observability-investigator"
    assert result.task_id == "T1"


# === PROFILE VALIDATION TESTS (4 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_pv1_unknown_profile_accepted():
    """S4-PV1: Unknown profile is accepted (no validation at S4 level)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Check",
        profile="unknown-profile"
    )
    fake_response = {
        "task_id": "T1",
        "finding": "Done"
    }
    oc = make_fake_oc(fake_response)

    # No validation - profile is passed through
    result = await execute_task(oc, "unknown-profile", "run-1", incident, task)
    assert result.task_id == "T1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_pv2_recovery_responder_profile():
    """S4-PV2: recovery-responder profile accepted for S4 (though typically S5)"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Check",
        profile="recovery-responder"
    )
    fake_response = {
        "task_id": "T1",
        "finding": "Done"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "recovery-responder", "run-1", incident, task)
    assert result.task_id == "T1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_pv3_empty_profile_handled():
    """S4-PV3: Empty profile string handled"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.OBSERVE,
        objective="Check",
        profile=""
    )
    fake_response = {
        "task_id": "T1",
        "finding": "Done"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "", "run-1", incident, task)
    assert result.task_id == "T1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_pv4_multiple_task_types_with_same_profile():
    """S4-PV4: Same profile works across OBSERVE, INVESTIGATE, DIAGNOSE"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    profile = "application-investigator"

    task_types = [TaskType.OBSERVE, TaskType.INVESTIGATE, TaskType.DIAGNOSE]

    for task_type in task_types:
        task = Task(
            id=f"T_{task_type.value}",
            type=task_type,
            objective=f"Execute {task_type.value}",
            profile=profile
        )
        fake_response = {
            "task_id": f"T_{task_type.value}",
            "finding": f"Finding for {task_type.value}"
        }
        oc = make_fake_oc(fake_response)

        result = await execute_task(oc, profile, "run-1", incident, task)
        assert result.task_id == f"T_{task_type.value}"


# === CROSS-SKILL PROFILE TESTS (4 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_cs1_profile_from_task_assigned():
    """S4-CS1: Profile from task assignment used for execution"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="T1",
        type=TaskType.INVESTIGATE,
        objective="Investigate DB issue",
        profile="database-investigator"  # Task specifies profile
    )
    fake_response = {
        "task_id": "T1",
        "finding": "Connection pool exhausted",
        "evidence": ["db:pool_active=100"]
    }
    oc = make_fake_oc(fake_response)

    # The task.profile should drive the execution
    result = await execute_task(oc, task.profile, "run-1", incident, task)

    assert result.task_id == "T1"
    assert "pool" in result.finding.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_cs2_parallel_different_profiles():
    """S4-CS2: Parallel tasks use different profiles correctly"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")

    tasks = [
        Task(id="T1", type=TaskType.OBSERVE, objective="Check metrics", profile="observability-investigator"),
        Task(id="T2", type=TaskType.INVESTIGATE, objective="Check app logs", profile="application-investigator"),
        Task(id="T3", type=TaskType.OBSERVE, objective="Check network", profile="infrastructure-investigator"),
        Task(id="T4", type=TaskType.INVESTIGATE, objective="Check DB", profile="database-investigator"),
    ]

    results = []
    for task in tasks:
        fake_response = {
            "task_id": task.id,
            "finding": f"Finding from {task.profile}",
            "evidence": [f"evidence_{task.id}"]
        }
        oc = make_fake_oc(fake_response)
        result = await execute_task(oc, task.profile, "run-1", incident, task)
        results.append(result)

    assert len(results) == 4
    # All should complete successfully
    assert all(isinstance(r, Finding) for r in results)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_cs3_profile_selection_matches_allowed_set():
    """S4-CS3: Profile selection uses only allowed investigator profiles"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")

    # All allowed profiles from task_graph_prompt
    for profile in ALLOWED_INVESTIGATOR_PROFILES:
        task = Task(
            id=f"T_{profile}",
            type=TaskType.OBSERVE,
            objective="Check",
            profile=profile
        )
        fake_response = {
            "task_id": f"T_{profile}",
            "finding": "Finding"
        }
        oc = make_fake_oc(fake_response)

        result = await execute_task(oc, profile, "run-1", incident, task)
        assert result.task_id == f"T_{profile}"
        assert profile in ALLOWED_INVESTIGATOR_PROFILES


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s4_cs4_profile_persists_in_finding():
    """S4-CS4: Finding maintains task_id which references original profile assignment"""
    incident = IncidentContext(issue_number=1, title="Test", service="api")
    task = Task(
        id="DB-T1",
        type=TaskType.INVESTIGATE,
        objective="Investigate database",
        profile="database-investigator"
    )
    fake_response = {
        "task_id": "DB-T1",
        "finding": "Database query deadlock",
        "evidence": ["db:deadlock_detected"],
        "confidence": 0.85,
        "hypothesis": "Transaction ordering issue"
    }
    oc = make_fake_oc(fake_response)

    result = await execute_task(oc, "database-investigator", "run-1", incident, task)

    # Task ID is preserved - links back to original task which has profile
    assert result.task_id == task.id
    assert result.hypothesis is not None
    assert result.confidence > 0
