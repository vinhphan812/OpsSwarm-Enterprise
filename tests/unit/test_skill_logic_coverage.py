"""Coverage-targeted tests for opsswarm/skill_logic.py uncovered branches.

Exercises generic Exception handlers and _normalize_rca_report() conditional
branches that are not reached through the normal validation-error paths.
"""

from unittest.mock import AsyncMock, patch

import pytest

from opsswarm.models import (
    Task, IncidentContext, RootCauseArtifact, RecoveryPlan,
    ExecutionResult, VerificationResult, TaskType, Risk, RCAReport,
)
from opsswarm import skill_logic as S


# -----------------------------------------------------------------------
# _redact_dict() — else branch (non-string/non-dict/non-list values)
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_redact_dict_preserves_non_string_types():
    """Lines 143-144: non-string/non-dict/non-list values are returned as-is."""
    from opsswarm.skill_logic import _redact_dict

    data = {
        "int_val": 42,
        "float_val": 3.14,
        "bool_val": True,
        "none_val": None,
        "nested": {"email": "user@example.com"},
    }
    result = _redact_dict(data)

    # PII still redacted
    assert "user@example.com" not in str(result)
    # Non-PII scalars preserved
    assert result["int_val"] == 42
    assert result["float_val"] == 3.14
    assert result["bool_val"] is True
    assert result["none_val"] is None


@pytest.mark.unit
def test_redact_dict_empty_list():
    """Empty list is handled (iterates to nothing, returns empty list)."""
    from opsswarm.skill_logic import _redact_dict

    result = _redact_dict({"items": []})
    assert result["items"] == []


@pytest.mark.unit
def test_redact_dict_list_with_non_string_items():
    """List items that are not strings are str()-ified then redacted."""
    from opsswarm.skill_logic import _redact_dict

    data = {"items": [1, 2.5, True, None]}
    result = _redact_dict(data)
    # Each item is converted to string then passed through email redaction
    # 1, 2.5, True, None → "1", "2.5", "True", "None" — no PII, all preserved
    assert result["items"] == ["1", "2.5", "True", "None"]


@pytest.mark.unit
def test_redact_dict_list_with_mixed_types():
    """List with mixed types — strings and non-strings — all handled."""
    from opsswarm.skill_logic import _redact_dict

    data = {
        "items": [
            "clean text",
            99,
            {"inner": "user@test.com"},
        ]
    }
    result = _redact_dict(data)
    assert result["items"][0] == "clean text"
    assert result["items"][1] == "99"
    # inner dict email should be redacted
    assert "user@test.com" not in str(result)


# -----------------------------------------------------------------------
# build_tasks() — generic Exception handler (lines 68-70)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_tasks_generic_exception():
    """Lines 68-70: non-ValidationError exceptions in the try block return [].

    Patch Task.model_validate (inside the try block) to raise a
    non-ValidationError so it hits the generic except Exception handler.
    """
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"tasks": [{"id": "t1", "type": "INVESTIGATE"}]}

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )

    with patch(
        "opsswarm.skill_logic.Task.model_validate",
        side_effect=RuntimeError("unexpected"),
    ):
        # Must not raise — caught by except Exception
        result = await S.build_tasks(mock_oc, "agent", "run-id", incident)
    assert result == []


# -----------------------------------------------------------------------
# execute_task() — generic Exception handler (lines 92-99)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_generic_exception():
    """Lines 92-99: non-ValidationError exceptions return safe fallback Finding."""
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {"task_id": "t1", "finding": "ok", "confidence": 0.9}

    task = Task(id="t1", type=TaskType.INVESTIGATE, objective="obj", profile="p")
    incident = IncidentContext(issue_number=1, title="t", body="b", service="s", environment="e")

    # normalize_finding raises non-ValidationError → generic handler
    with patch("opsswarm.skill_logic.normalize_finding", side_effect=RuntimeError("INTERNAL_STACK_TRACE")):
        result = await S.execute_task(mock_oc, "agent", "run-id", incident, task)

    assert result.task_id == "t1"
    assert result.confidence == 0.0
    # The generic handler uses constant message; INTERNAL_STACK_TRACE must not appear
    assert "INTERNAL_STACK_TRACE" not in result.finding
    assert "error" in result.finding.lower()


# -----------------------------------------------------------------------
# synthesize_root_cause() — generic Exception handler (lines 166-172)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_root_cause_generic_exception():
    """Lines 166-172: non-ValidationError exceptions return uncertain RCA."""
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )

    with patch(
        "opsswarm.skill_logic.normalize_root_cause_artifact",
        side_effect=RuntimeError("unexpected failure"),
    ):
        result = await S.synthesize_root_cause(
            mock_oc, "agent", "run-id", incident, [], []
        )

    assert result.status == "uncertain"
    assert result.proximate_cause == "Unable to synthesize root cause"


# -----------------------------------------------------------------------
# make_recovery_plan() — generic Exception handler (lines 187-189)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_recovery_plan_generic_exception():
    """Lines 187-189: non-ValidationError exceptions return empty RecoveryPlan."""
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )
    root = RootCauseArtifact(proximate_cause="p", root_cause="r")

    with patch(
        "opsswarm.skill_logic.normalize_recovery_plan",
        side_effect=RuntimeError("unexpected failure"),
    ):
        result = await S.make_recovery_plan(mock_oc, "agent", "run-id", incident, root, [])

    assert result.options == []


# -----------------------------------------------------------------------
# execute_recovery() — generic Exception handler (lines 208-215)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_recovery_generic_exception():
    """Lines 208-215: non-ValidationError exceptions return failed ExecutionResult."""
    from opsswarm.models import RemediationOption
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )
    root = RootCauseArtifact(proximate_cause="p", root_cause="r")
    option = RemediationOption(id="o1", description="restart service", risk=Risk.SAFE_WRITE)

    with patch(
        "opsswarm.skill_logic.ExecutionResult.model_validate",
        side_effect=RuntimeError("INTERNAL_STACK_TRACE"),
    ):
        result = await S.execute_recovery(mock_oc, "agent", "run-id", incident, root, option)

    assert result.success is False
    # Constant message is used — INTERNAL_STACK_TRACE must not appear
    assert "INTERNAL_STACK_TRACE" not in result.summary
    assert result.evidence == []  # no raw evidence leaked


# -----------------------------------------------------------------------
# verify_recovery() — generic Exception handler (lines 234-241)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_recovery_generic_exception():
    """Lines 234-241: non-ValidationError exceptions return failed VerificationResult."""
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )
    execution = ExecutionResult(option_id="o1", success=True, summary="ok", evidence=[])

    with patch(
        "opsswarm.skill_logic.VerificationResult.model_validate",
        side_effect=RuntimeError("INTERNAL_STACK_TRACE"),
    ):
        result = await S.verify_recovery(mock_oc, "agent", "run-id", incident, execution)

    assert result.verified is False
    # Constant message is used — INTERNAL_STACK_TRACE must not appear
    assert "INTERNAL_STACK_TRACE" not in result.summary
    assert result.evidence == []  # no raw evidence leaked
    assert result.confidence == 0.0


# -----------------------------------------------------------------------
# make_extra_task() — generic Exception handler (lines 260-268)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_extra_task_generic_exception():
    """Lines 260-268: non-ValidationError exceptions return fallback Task."""
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=1, title="t", body="b", service="s", environment="e"
    )

    with patch(
        "opsswarm.skill_logic.Task.model_validate",
        side_effect=RuntimeError("unexpected failure"),
    ):
        result = await S.make_extra_task(mock_oc, "agent", "run-id", incident, "check CPU")

    assert result.id == "extra-fallback"
    assert result.type == TaskType.INVESTIGATE
    assert "check CPU" in result.objective


# -----------------------------------------------------------------------
# synthesize_rca() — generic Exception handler (lines 301-306)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_rca_generic_exception():
    """Lines 301-306: non-ValidationError exceptions return safe RCAReport fallback.

    Patch _normalize_rca_report (called inside the try block) to raise
    RuntimeError — this hits the generic except Exception handler (not
    ValidationError) and exercises the safe fallback.
    """
    mock_oc = AsyncMock()
    mock_oc.run_json.return_value = {}  # Valid response

    incident = IncidentContext(
        issue_number=42, title="t", body="b", service="s", environment="e"
    )
    root = RootCauseArtifact(
        proximate_cause="network timeout",
        root_cause="misconfigured LB",
        causal_chain=["LB misconfig", "timeout"],
        confidence=0.7,
    )
    findings = []

    with patch(
        "opsswarm.skill_logic._normalize_rca_report",
        side_effect=RuntimeError("INTERNAL_STACK_TRACE"),
    ):
        result = await S.synthesize_rca(
            mock_oc, "agent", "run-id", incident, root, findings, []
        )

    # Safe fallback path taken: run_id and issue_number set from parameters
    assert result.run_id == "run-id"
    assert result.issue_number == 42


# -----------------------------------------------------------------------
# _normalize_rca_report() — conditional branches
# -----------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_rca_report_camelCase_aliases():
    """Lines 317-320: camelCase aliases (rootCause, proximateCause) are converted."""
    raw = {
        "rootCause": "LB misconfiguration",
        "proximateCause": "timeout",
    }
    result = S._normalize_rca_report(raw)
    assert "root_cause" in result
    assert result["root_cause"] == "LB misconfiguration"
    assert result["proximate_cause"] == "timeout"
    # camelCase keys are removed
    assert "rootCause" not in result
    assert "proximateCause" not in result


@pytest.mark.unit
def test_normalize_rca_report_causal_chain_alias():
    """Lines 321-322: causalChain alias is converted."""
    raw = {"causalChain": ["step 1", "step 2"]}
    result = S._normalize_rca_report(raw)
    assert "causal_chain" in result
    assert result["causal_chain"] == ["step 1", "step 2"]
    assert "causalChain" not in result


@pytest.mark.unit
def test_normalize_rca_report_contributing_factors():
    """Lines 323-324: contributingFactors setdefault."""
    raw = {"contributingFactors": ["factor A", "factor B"]}
    result = S._normalize_rca_report(raw)
    assert "contributing_factors" in result
    assert result["contributing_factors"] == ["factor A", "factor B"]
    assert "contributingFactors" not in result


@pytest.mark.unit
def test_normalize_rca_report_what_went_well():
    """Lines 325-326: whatWentWell setdefault."""
    raw = {"whatWentWell": ["fast detection", "clear runbook"]}
    result = S._normalize_rca_report(raw)
    assert "what_went_well" in result
    assert result["what_went_well"] == ["fast detection", "clear runbook"]


@pytest.mark.unit
def test_normalize_rca_report_what_went_poorly():
    """Lines 327-328: whatWentPoorly setdefault."""
    raw = {"whatWentPoorly": ["slow rollback"]}
    result = S._normalize_rca_report(raw)
    assert "what_went_poorly" in result
    assert result["what_went_poorly"] == ["slow rollback"]


@pytest.mark.unit
def test_normalize_rca_report_lessons_learned():
    """Lines 329-330: lessonsLearned setdefault."""
    raw = {"lessonsLearned": ["add health checks"]}
    result = S._normalize_rca_report(raw)
    assert "lessons_learned" in result
    assert result["lessons_learned"] == ["add health checks"]


@pytest.mark.unit
def test_normalize_rca_report_corrective_actions_string():
    """Lines 331-343: correctiveActions with string items → normalized dicts."""
    raw = {
        "correctiveActions": [
            "Fix the load balancer config",
            "Add monitoring for latency",
        ]
    }
    result = S._normalize_rca_report(raw)
    assert "corrective_actions" in result
    assert len(result["corrective_actions"]) == 2
    assert result["corrective_actions"][0]["description"] == "Fix the load balancer config"
    assert result["corrective_actions"][0]["priority"] == "medium"
    assert result["corrective_actions"][1]["description"] == "Add monitoring for latency"


@pytest.mark.unit
def test_normalize_rca_report_corrective_actions_dict():
    """Lines 332-343: correctiveActions with dict items → merged with defaults."""
    raw = {
        "correctiveActions": [
            {
                "description": "Restart the service",
                "priority": "high",
                "owner": "platform-team",
            },
            {
                "action": "Rollback release",  # 'action' key as fallback for 'description'
                "priority": "low",
            },
        ]
    }
    result = S._normalize_rca_report(raw)
    actions = result["corrective_actions"]
    assert actions[0]["description"] == "Restart the service"
    assert actions[0]["priority"] == "high"
    assert actions[0]["owner"] == "platform-team"
    assert actions[1]["description"] == "Rollback release"
    assert actions[1]["priority"] == "low"
    assert actions[1]["owner"] is None


@pytest.mark.unit
def test_normalize_rca_report_timeline():
    """Lines 344-354: timeline events normalized from dict."""
    raw = {
        "timeline": [
            {"timestamp": "2026-09-27T10:00:00Z", "actor": "alice", "action": "deployed"},
            {"timestamp": "2026-09-27T10:05:00Z", "actor": "bob", "action": "alert fired"},
        ]
    }
    result = S._normalize_rca_report(raw)
    assert "timeline" in result
    timeline = result["timeline"]
    assert len(timeline) == 2
    assert timeline[0]["timestamp"] == "2026-09-27T10:00:00Z"
    assert timeline[0]["actor"] == "alice"
    assert timeline[0]["action"] == "deployed"


@pytest.mark.unit
def test_normalize_rca_report_no_change_for_snake_case():
    """Already snake_case keys are left unchanged."""
    raw = {
        "root_cause": "LB misconfig",
        "proximate_cause": "timeout",
        "causal_chain": ["step 1"],
    }
    result = S._normalize_rca_report(raw)
    assert result["root_cause"] == "LB misconfig"
    assert result["proximate_cause"] == "timeout"
    assert result["causal_chain"] == ["step 1"]
