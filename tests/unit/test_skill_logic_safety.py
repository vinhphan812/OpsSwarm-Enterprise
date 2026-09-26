from unittest.mock import AsyncMock, patch

import pytest

from opsswarm.models import Task, IncidentContext, RootCauseArtifact, TaskType
from opsswarm.skill_logic import execute_task, synthesize_root_cause, make_recovery_plan


@pytest.mark.asyncio
async def test_execute_task_sanitization():
    mock_oc = AsyncMock()
    # Data that definitely contains PII
    malformed_data = {"key": "secret", "value": "PII_VALUE"}
    mock_oc.run_json.return_value = malformed_data
    task = Task(id="1", type=TaskType.INVESTIGATE, objective="test objective", profile="test-profile")
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    # This triggers the exception inside execute_task
    with patch("opsswarm.skill_logic.normalize_finding", side_effect=Exception("Normalizer fail")):
        result = await execute_task(mock_oc, "agent", "run", incident, task)

        # Assert evidence is redacted (the current implementation puts the raw dict as string!)
        assert "PII_VALUE" not in str(result.evidence)
        assert "secret" not in str(result.evidence)
        assert "Validation failed" in result.finding


@pytest.mark.asyncio
async def test_synthesize_root_cause_does_not_crash():
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"bad": "data"}
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    with patch("opsswarm.skill_logic.normalize_root_cause_artifact", side_effect=Exception("Normalizer fail")):
        # This should not raise an exception if fixed
        await synthesize_root_cause(mock_oc, "agent", "run", incident, [], {})


@pytest.mark.asyncio
async def test_make_recovery_plan_does_not_crash():
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"bad": "data"}
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")
    mock_root = RootCauseArtifact(proximate_cause="test", root_cause="none")

    with patch("opsswarm.skill_logic.normalize_recovery_plan", side_effect=Exception("Normalizer fail")):
        # This should not raise an exception if fixed
        await make_recovery_plan(mock_oc, "agent", "run", incident, mock_root, {})
