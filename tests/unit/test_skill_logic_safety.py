from unittest.mock import AsyncMock, patch

import pytest

from opsswarm.models import Task, IncidentContext, RootCauseArtifact, TaskType
from opsswarm.skill_logic import execute_task, synthesize_root_cause, make_recovery_plan


@pytest.mark.asyncio
async def test_execute_task_sanitization():
    """Non-validation exceptions are caught and PII is not leaked in evidence."""
    mock_oc = AsyncMock()
    # Data that definitely contains PII
    malformed_data = {"key": "secret", "value": "PII_VALUE"}
    mock_oc.run_json.return_value = malformed_data
    task = Task(
        id="1", type=TaskType.INVESTIGATE, objective="test objective", profile="test-profile"
    )
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    # Non-ValidationError exception from normalize_finding triggers the generic handler
    with patch("opsswarm.skill_logic.normalize_finding", side_effect=Exception("Normalizer fail")):
        result = await execute_task(mock_oc, "agent", "run", incident, task)

        # Assert evidence is redacted (never raw dict as string)
        assert "PII_VALUE" not in str(result.evidence)
        assert "secret" not in str(result.evidence)
        # Generic exception path uses a safe fallback finding message
        assert "error" in result.finding.lower()


@pytest.mark.asyncio
async def test_synthesize_root_cause_does_not_crash():
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"bad": "data"}
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    with patch(
        "opsswarm.skill_logic.normalize_root_cause_artifact",
        side_effect=Exception("Normalizer fail"),
    ):
        # This should not raise an exception if fixed
        await synthesize_root_cause(mock_oc, "agent", "run", incident, [], {})


@pytest.mark.asyncio
async def test_make_recovery_plan_does_not_crash():
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"bad": "data"}
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")
    mock_root = RootCauseArtifact(proximate_cause="test", root_cause="none")

    with patch(
        "opsswarm.skill_logic.normalize_recovery_plan", side_effect=Exception("Normalizer fail")
    ):
        # This should not raise an exception if fixed
        await make_recovery_plan(mock_oc, "agent", "run", incident, mock_root, {})


@pytest.mark.asyncio
async def test_execute_task_validation_error_no_raw_input_in_finding():
    """Regression for r4111809843: Pydantic validation errors must not leak raw
    agent output into the persisted Finding.evidence list.

    The fallback Finding must contain only a constant safe message — not str(e)
    or any portion of the rejected input payload.
    """
    mock_oc = AsyncMock()
    sensitive_payload = {
        "task_id": "t99",
        "secret_token": "ghp_REAL_SECRET_1234567890",
        "email": "victim@internal.corp",
        "finding": "ok",
        "evidence": ["step1"],
        "confidence": 0.9,
    }
    mock_oc.run_json.return_value = sensitive_payload
    task = Task(id="t99", type=TaskType.INVESTIGATE, objective="obj", profile="p")
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    # Let normalize succeed but make model_validate raise with detail about input
    import pydantic

    def bad_validate(data):
        raise pydantic.ValidationError.from_exception_data(
            title="Finding",
            input_type="python",
            line_errors=[
                {
                    "type": "missing",
                    "loc": ("task_id",),
                    "msg": "Field required",
                    "input": sensitive_payload,
                    "url": "https://errors.pydantic.dev/2.0/v/missing",
                    "ctx": {},
                }
            ],
        )

    with patch("opsswarm.skill_logic.Finding.model_validate", side_effect=bad_validate):
        result = await execute_task(mock_oc, "agent", "run", incident, task)

    evidence_str = str(result.evidence)
    assert "ghp_REAL_SECRET_1234567890" not in evidence_str, (
        "Raw secret must not appear in Finding.evidence"
    )
    assert "victim@internal.corp" not in evidence_str, (
        "Raw email must not appear in Finding.evidence"
    )
    assert "Validation failed" in result.finding


@pytest.mark.asyncio
async def test_execute_task_validation_error_not_in_log(caplog):
    """Regression for r4111809862: logger.error must not interpolate the
    exception message (which can contain raw agent output) into the log record.
    """
    import logging

    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"task_id": "t1", "finding": "x"}
    task = Task(id="t1", type=TaskType.INVESTIGATE, objective="obj", profile="p")
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    sensitive = "SUPER_SECRET_API_KEY=sk-1234"

    with caplog.at_level(logging.ERROR, logger="opsswarm.skill_logic"):
        with patch(
            "opsswarm.skill_logic.normalize_finding",
            side_effect=ValueError(f"bad input: {sensitive}"),
        ):
            await execute_task(mock_oc, "agent", "run", incident, task)

    assert sensitive not in caplog.text, (
        "Exception detail (possibly containing sensitive input) must not appear in logs"
    )


@pytest.mark.asyncio
async def test_recovery_plan_validation_error_not_in_log(caplog):
    """Regression for r4111809876: recovery-plan validation errors must not
    interpolate exception details into logs.
    """
    import logging

    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"options": []}
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")
    mock_root = RootCauseArtifact(proximate_cause="p", root_cause="r")

    sensitive = "internal_host=db.prod.corp"

    with caplog.at_level(logging.ERROR, logger="opsswarm.skill_logic"):
        with patch(
            "opsswarm.skill_logic.normalize_recovery_plan",
            side_effect=ValueError(f"invalid plan: {sensitive}"),
        ):
            await make_recovery_plan(mock_oc, "agent", "run", incident, mock_root, {})

    assert sensitive not in caplog.text, (
        "Exception detail must not appear in recovery-plan error logs"
    )
