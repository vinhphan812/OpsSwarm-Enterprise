"""Fault injection tests for Issue #31: OpenClaw JSON output violates Pydantic contracts.

Tests that malformed JSON from OpenClaw is handled gracefully across all
skill_logic.py call-sites that call model_validate() on OpenClaw output.

Acceptance: malformed JSON from OpenClaw is handled gracefully — never propagates
as an unhandled exception that would abort incident processing.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from opsswarm.models import (
    Task,
    Finding,
    RecoveryPlan,
    ExecutionResult,
    VerificationResult,
    RootCauseArtifact,
    IncidentContext,
    TaskType,
    Risk,
)
from opsswarm import skill_logic as S


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_incident() -> IncidentContext:
    return IncidentContext(
        issue_number=1,
        title="Test incident",
        body="Test body",
        service="test-service",
        environment="test",
        severity="SEV3",
    )


@pytest.fixture
def mock_task() -> Task:
    return Task(
        id="t1",
        type=TaskType.INVESTIGATE,
        objective="Investigate the issue",
        profile="observability-investigator",
        risk=Risk.READ,
    )


# --------------------------------------------------------------------------- #
# build_tasks — malformed OpenClaw JSON
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_build_tasks_non_dict_response(mock_incident):
    """OpenClaw returns a string or list instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    result = await S.build_tasks(oc_mock, "agent", "run-1", mock_incident)

    assert result == []
    oc_mock.run_json.assert_awaited_once()


@pytest.mark.fault
@pytest.mark.asyncio
async def test_build_tasks_missing_tasks_key(mock_incident):
    """OpenClaw returns a dict but lacks the 'tasks' key — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={"something": "else"})

    result = await S.build_tasks(oc_mock, "agent", "run-1", mock_incident)

    assert result == []


@pytest.mark.fault
@pytest.mark.asyncio
async def test_build_tasks_tasks_is_none(mock_incident):
    """OpenClaw returns dict with tasks=null — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={"tasks": None})

    result = await S.build_tasks(oc_mock, "agent", "run-1", mock_incident)

    assert result == []


@pytest.mark.fault
@pytest.mark.asyncio
async def test_build_tasks_tasks_is_string(mock_incident):
    """OpenClaw returns dict with tasks as a string — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={"tasks": "not a list"})

    result = await S.build_tasks(oc_mock, "agent", "run-1", mock_incident)

    assert result == []


@pytest.mark.fault
@pytest.mark.asyncio
async def test_build_tasks_invalid_task_item(mock_incident):
    """OpenClaw returns a list with an item that violates Task Pydantic contract."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "tasks": [
            {"id": "t1"},  # missing required 'type', 'objective', 'profile'
            {"type": "not_a_tasktype"},  # invalid enum
        ]
    })

    result = await S.build_tasks(oc_mock, "agent", "run-1", mock_incident)

    # Invalid items are dropped; no crash
    assert isinstance(result, list)


# --------------------------------------------------------------------------- #
# execute_task — malformed OpenClaw JSON (existing try/except coverage)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_execute_task_non_dict_response(mock_incident, mock_task):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    result = await S.execute_task(oc_mock, "agent", "run-1", mock_incident, mock_task)

    assert isinstance(result, Finding)
    assert result.task_id == mock_task.id
    assert result.confidence == 0.0
    # Non-dict triggers the generic "Unexpected error" fallback (except Exception branch)
    assert "unexpected error" in result.finding.lower()


@pytest.mark.fault
@pytest.mark.asyncio
async def test_execute_task_missing_required_fields(mock_incident, mock_task):
    """OpenClaw returns a dict missing required Finding fields — gracefully degrades."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "finding": "something",
        # missing task_id, evidence
    })

    result = await S.execute_task(oc_mock, "agent", "run-1", mock_incident, mock_task)

    assert isinstance(result, Finding)
    assert result.task_id == mock_task.id


# --------------------------------------------------------------------------- #
# execute_recovery — malformed OpenClaw JSON (no prior try/except)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_execute_recovery_non_dict_response(mock_incident):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    root = RootCauseArtifact(
        proximate_cause="test",
        root_cause="test",
    )
    option = MagicMock()
    option.id = "opt-1"
    option.model_dump_json = MagicMock(return_value="{}")

    result = await S.execute_recovery(oc_mock, "agent", "run-1", mock_incident, root, option)

    assert isinstance(result, ExecutionResult)
    assert result.success is False
    assert "not a dict" in result.summary or "not" in result.summary.lower()


@pytest.mark.fault
@pytest.mark.asyncio
async def test_execute_recovery_invalid_fields(mock_incident):
    """OpenClaw returns a dict with wrong field types — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": "yes",  # should be bool
        "summary": 12345,  # should be str
    })

    root = RootCauseArtifact(proximate_cause="test", root_cause="test")
    option = MagicMock()
    option.id = "opt-1"
    option.model_dump_json = MagicMock(return_value="{}")

    result = await S.execute_recovery(oc_mock, "agent", "run-1", mock_incident, root, option)

    assert isinstance(result, ExecutionResult)
    # Fallback: success should be False (not the invalid "yes")
    assert result.success is False


@pytest.mark.fault
@pytest.mark.asyncio
async def test_execute_recovery_missing_required_fields(mock_incident):
    """OpenClaw returns a dict missing required ExecutionResult fields."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={"summary": "partial only"})

    root = RootCauseArtifact(proximate_cause="test", root_cause="test")
    option = MagicMock()
    option.id = "opt-1"
    option.model_dump_json = MagicMock(return_value="{}")

    result = await S.execute_recovery(oc_mock, "agent", "run-1", mock_incident, root, option)

    assert isinstance(result, ExecutionResult)
    assert result.success is False


# --------------------------------------------------------------------------- #
# verify_recovery — malformed OpenClaw JSON (no prior try/except)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_verify_recovery_non_dict_response(mock_incident):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    execution = MagicMock()
    execution.model_dump_json = MagicMock(return_value="{}")

    result = await S.verify_recovery(oc_mock, "agent", "run-1", mock_incident, execution)

    assert isinstance(result, VerificationResult)
    assert result.verified is False


@pytest.mark.fault
@pytest.mark.asyncio
async def test_verify_recovery_invalid_fields(mock_incident):
    """OpenClaw returns a dict with wrong field types — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "verified": "yes",  # should be bool
        "summary": 999,     # should be str
    })

    execution = MagicMock()
    execution.model_dump_json = MagicMock(return_value="{}")

    result = await S.verify_recovery(oc_mock, "agent", "run-1", mock_incident, execution)

    assert isinstance(result, VerificationResult)
    assert result.verified is False
    assert result.confidence == 0.0


@pytest.mark.fault
@pytest.mark.asyncio
async def test_verify_recovery_missing_required_fields(mock_incident):
    """OpenClaw returns a dict missing required VerificationResult fields."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={"confidence": 0.5})

    execution = MagicMock()
    execution.model_dump_json = MagicMock(return_value="{}")

    result = await S.verify_recovery(oc_mock, "agent", "run-1", mock_incident, execution)

    assert isinstance(result, VerificationResult)
    assert result.verified is False


# --------------------------------------------------------------------------- #
# synthesize_root_cause — malformed OpenClaw JSON (existing try/except)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_synthesize_root_cause_non_dict_response(mock_incident):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    result = await S.synthesize_root_cause(oc_mock, "agent", "run-1", mock_incident, [], [])

    assert isinstance(result, RootCauseArtifact)
    assert result.status == "uncertain"


@pytest.mark.fault
@pytest.mark.asyncio
async def test_synthesize_root_cause_invalid_fields(mock_incident):
    """OpenClaw returns a dict with wrong field types — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "status": "confirmed",
        "confidence": "high",  # should be float
        "causal_chain": "not a list",  # should be list
    })

    result = await S.synthesize_root_cause(oc_mock, "agent", "run-1", mock_incident, [], [])

    assert isinstance(result, RootCauseArtifact)


# --------------------------------------------------------------------------- #
# make_recovery_plan — malformed OpenClaw JSON (existing try/except)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_make_recovery_plan_non_dict_response(mock_incident):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    root = RootCauseArtifact(proximate_cause="test", root_cause="test")
    result = await S.make_recovery_plan(oc_mock, "agent", "run-1", mock_incident, root, [])

    assert isinstance(result, RecoveryPlan)
    assert result.options == []


@pytest.mark.fault
@pytest.mark.asyncio
async def test_make_recovery_plan_invalid_fields(mock_incident):
    """OpenClaw returns a dict with wrong field types — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "options": "not a list",
        "confidence": "high",
    })

    root = RootCauseArtifact(proximate_cause="test", root_cause="test")
    result = await S.make_recovery_plan(oc_mock, "agent", "run-1", mock_incident, root, [])

    assert isinstance(result, RecoveryPlan)
    assert result.options == []


# --------------------------------------------------------------------------- #
# make_extra_task — malformed OpenClaw JSON (no prior try/except)
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_make_extra_task_non_dict_response(mock_incident):
    """OpenClaw returns a string instead of a dict — must not crash."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value="not a dict")

    result = await S.make_extra_task(oc_mock, "agent", "run-1", mock_incident, "do something")

    # Without validation, model_validate raises ValidationError which is unhandled
    # This test documents the pre-fix behavior — after the fix it should return a Task
    # For now: with no try/except, this WILL raise ValidationError (Issue #31)
    # The fix should catch it, but since we haven't added it yet, we expect the exception.
    # AFTER the fix below, this test verifies no exception propagates.
    try:
        result = await S.make_extra_task(oc_mock, "agent", "run-1", mock_incident, "do something")
        assert isinstance(result, Task)
    except Exception:
        # Pre-fix: ValidationError propagates (Issue #31)
        # Post-fix: wrapped gracefully
        pytest.fail("make_extra_task should handle non-dict response gracefully")


@pytest.mark.fault
@pytest.mark.asyncio
async def test_make_extra_task_invalid_task_fields(mock_incident):
    """OpenClaw returns a dict with invalid Task field values."""
    oc_mock = AsyncMock()
    oc_mock.run_json = AsyncMock(return_value={
        "id": "xt1",
        "type": "not_a_task_type",
        "objective": 123,
        "profile": "unknown-profile",
    })

    try:
        result = await S.make_extra_task(oc_mock, "agent", "run-1", mock_incident, "do something")
        assert isinstance(result, Task)
    except Exception:
        pytest.fail("make_extra_task should handle invalid field values gracefully")


# --------------------------------------------------------------------------- #
# Edge cases: OpenClawClient._extract_json fallback itself can fail
# --------------------------------------------------------------------------- #

@pytest.mark.fault
@pytest.mark.asyncio
async def test_openclaw_returns_completely_empty_response():
    """OpenClaw returns empty bytes — _extract_json must not raise unhandled."""
    from opsswarm.openclaw import OpenClawClient

    client = OpenClawClient(binary="openclaw")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        with pytest.raises(Exception) as exc_info:
            await client.run_text("agent", "session", "prompt")
        # Either OpenClawError (no assistant text) or JSONDecodeError is acceptable
        # as this is genuinely malformed output
        assert "No assistant text" in str(exc_info.value) or "JSONDecodeError" in type(exc_info.value).__name__


@pytest.mark.fault
@pytest.mark.asyncio
async def test_openclaw_json_decode_error():
    """OpenClaw returns invalid JSON bytes — _extract_json re-raises JSONDecodeError."""
    from opsswarm.openclaw import OpenClawClient

    client = OpenClawClient(binary="openclaw")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"{ invalid json", b""))
        mock_exec.return_value = mock_proc

        # _extract_json attempts to parse, then falls back to bounded salvage,
        # both of which fail on "{ invalid json" — JSONDecodeError propagates
        # as the final fallback in run_text's text extraction path.
        # This is acceptable: the caller (skill_logic) wraps the result in try/except.
        with pytest.raises(json.JSONDecodeError):
            await client.run_text("agent", "session", "prompt")
