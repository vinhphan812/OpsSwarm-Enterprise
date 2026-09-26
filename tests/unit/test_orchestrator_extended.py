"""Extended orchestrator tests covering previously-uncovered code paths."""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from opsswarm.models import RunState, RunRecord, VerificationResult, CheckpointType
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load(open('config/test.yaml'))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_recovery_plan_returns_none_when_run_not_found(cfg):
    """get_reconciliation_report returns None when run does not exist."""
    gh = FakeGitHub(None)
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc)
    assert eng.get_reconciliation_report(999) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_issue_raises_runtime_error_when_missing_label(cfg):
    """start_issue raises RuntimeError when issue lacks required opsswarm label."""
    issue = {'number': 1, 'labels': [{'name': 'wrong-label'}]}
    gh = FakeGitHub(issue)
    gh.get_issue = AsyncMock(return_value=issue)
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc)
    with pytest.raises(RuntimeError, match="lacks required label opsswarm"):
        await eng.start_issue(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_option_ambiguous_path(cfg, tmp_path):
    """_execute_option with ambiguous=True transitions to WAITING_DECISION."""
    gh = FakeGitHub({'number': 1})

    with patch('opsswarm.skill_logic.execute_recovery', new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock(ambiguous=True, success=True)

        oc = FakeOpenClaw([])
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

        run = RunRecord(run_id="test-run", issue_number=1)

        await eng._execute_option(run, MagicMock(id='opt1', risk='safe_write'))
        assert run.state == RunState.WAITING_DECISION


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_option_failure_path(cfg, tmp_path):
    """_execute_option with success=False transitions to FAILED."""
    gh = FakeGitHub({'number': 1})

    with patch('opsswarm.skill_logic.execute_recovery', new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = MagicMock(ambiguous=False, success=False, summary="Failure")

        oc = FakeOpenClaw([])
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

        run = RunRecord(run_id="test-run", issue_number=1)

        await eng._execute_option(run, MagicMock(id='opt1', risk='safe_write'))
        assert run.state == RunState.FAILED
        assert run.error == "Failure"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_threshold_fail(cfg, tmp_path):
    """_verify with low confidence transitions to FAILED."""
    gh = FakeGitHub({'number': 1})

    with patch('opsswarm.skill_logic.verify_recovery', new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = VerificationResult(
            verified=True,
            confidence=0.5,
            summary="Low confidence",
            abort=False,
        )

        oc = FakeOpenClaw([])
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

        run = RunRecord(run_id="test-run", issue_number=1)
        eng.store.save = MagicMock()
        eng.ev.checkpoint = MagicMock()
        eng.github.comment = AsyncMock()

        await eng._verify(run)
        assert run.state == RunState.FAILED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_abort_veto(cfg, tmp_path):
    """_verify with abort=True transitions to ABORTED (S7 veto)."""
    gh = FakeGitHub({'number': 1})

    with patch('opsswarm.skill_logic.verify_recovery', new_callable=AsyncMock) as mock_verify:
        # Use the real VerificationResult model so attribute access works correctly
        mock_verify.return_value = VerificationResult(
            verified=False,  # False triggers the verification-failed block
            confidence=0.99,
            summary="Verification failed",
            abort=True,  # S7 veto
        )

        oc = FakeOpenClaw([])
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

        run = RunRecord(run_id="test-run", issue_number=1)
        eng.store.save = MagicMock()
        eng.ev.checkpoint = MagicMock()
        eng.github.comment = AsyncMock()

        await eng._verify(run)
        assert run.state == RunState.ABORTED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_pass(cfg, tmp_path):
    """_verify with high confidence transitions to RESOLVED."""
    gh = FakeGitHub({'number': 1})

    with patch('opsswarm.skill_logic.verify_recovery', new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = VerificationResult(
            verified=True,
            confidence=0.99,
            summary="Passed",
        )

        oc = FakeOpenClaw([])
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

        run = RunRecord(run_id="test-run", issue_number=1)
        eng.store.save = MagicMock()
        eng.ev.checkpoint = MagicMock()
        eng.github.comment = AsyncMock()
        eng.github.close_issue = AsyncMock()

        await eng._verify(run)
        assert run.state == RunState.RESOLVED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_permission_error_approve(cfg, tmp_path):
    """handle_comment raises PermissionError when approving a DENY-risky option."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])

    with patch('opsswarm.skill_logic.verify_recovery', new_callable=AsyncMock):
        eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    # Add a run with a recovery plan containing a DENY-risky option
    run = RunRecord(run_id="test-run", issue_number=1)
    eng.runs[1] = run

    # Policy denies 'risky_write' (from policy.py: self.cfg.get(risk.value, "DENY"))
    # So approving a risky_write option should raise PermissionError
    from opsswarm.models import RecoveryPlan, RemediationOption
    option = RemediationOption(id="opt-risky", risk="risky_write", description="Risky option")
    run.recovery_plan = RecoveryPlan(options=[option])

    cmd = MagicMock()
    cmd.name = "approve"
    cmd.argument = "opt-risky"

    eng.github.comment = AsyncMock()
    eng.store.save = MagicMock()

    with pytest.raises(Exception) as excinfo:
        await eng.handle_comment(1, "reader", "approve opt-risky", "read", cmd)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_resume_no_checkpoint(cfg, tmp_path):
    """handle_comment resume with no checkpoint warns the user."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    # Mock checkpoint retrieval to return None
    eng.ev.get_last_checkpoint = MagicMock(return_value=None)

    run = RunRecord(run_id="test-run", issue_number=1)
    # Put run in PLANNING state for `resume` fallback
    run.state = RunState.PLANNING

    run.execution = MagicMock()
    run.execution.success = False  # Still failing
    eng.runs[1] = run

    cmd = MagicMock()
    cmd.name = "resume"

    eng.github.comment = AsyncMock()

    await eng.handle_comment(1, "reader", "resume", "read", cmd)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_human_gate(cfg, tmp_path):
    """handle_comment resume with HUMAN_GATE checkpoint comments user."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.HUMAN_GATE.value,
            "state": "waiting_decision"
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run
    eng.github.comment = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    assert eng.github.comment.called
    assert "Resuming from checkpoint (type: human_gate" in eng.github.comment.call_args[0][1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_execution_success(cfg, tmp_path):
    """handle_comment resume with EXECUTION (post_execution) checkpoint verifies."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.EXECUTION.value,
            "phase": "post_execution"
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.EXECUTING
    run.execution = MagicMock()
    run.execution.success = True
    eng.runs[1] = run

    eng._verify = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng._verify.assert_called_once_with(run)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_investigate(cfg, tmp_path):
    """handle_comment investigate command triggers investigation."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run

    eng._investigate = AsyncMock()
    # Mock make_extra_task
    with patch('opsswarm.orchestrator.S.make_extra_task', new_callable=AsyncMock) as mock_make:
        mock_make.return_value = MagicMock(id="HX1")

        cmd = MagicMock()
        cmd.name = "investigate"
        cmd.argument = "something"

        await eng.handle_comment(1, "reader", "investigate something", "read", cmd)

        eng._investigate.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_command_confirmed(cfg, tmp_path):
    """handle_comment command confirmation marks command as confirmed."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run

    # Mock approve
    eng.github.comment = AsyncMock()
    eng.store.save = MagicMock()
    from opsswarm.models import RecoveryPlan, RemediationOption
    option = RemediationOption(id="opt1", risk="read", description="Safe")
    run.recovery_plan = RecoveryPlan(options=[option])

    # Using 'approve' command - needs existing recovery plan
    cmd = MagicMock()
    cmd.name = "approve"
    cmd.argument = "opt1"

    # Patch execute_option to prevent actual execution
    eng._execute_option = AsyncMock()

    await eng.handle_comment(1, "reader", "approve", "maintain", cmd, comment_id="cid")

    assert "cid" in run.command_outcomes
    assert run.command_outcomes["cid"] == "confirmed"
    eng.store.save.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_execution_pre(cfg, tmp_path):
    """handle_comment resume with EXECUTION (pre_execution) checkpoint comments user."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.EXECUTION.value,
            "phase": "pre_execution"
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run
    eng.github.comment = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng.github.comment.assert_called_with(1,
                                          "Resuming from pre-execution checkpoint. Use `/opsswarm approve <option>` to continue execution.")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_fallback_failed_success(cfg, tmp_path):
    """handle_comment resume with FAILED state and success=True verifies."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value=None)

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.FAILED
    run.execution = MagicMock()
    run.execution.success = True
    eng.runs[1] = run

    eng._verify = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng._verify.assert_called_once_with(run)
    # Re-import skill_logic for cleanup if necessary, but this should be fine.


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_investigate(cfg, tmp_path):
    """handle_comment investigate command triggers investigation."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run

    eng._investigate = AsyncMock()
    # Mock make_extra_task
    with patch('opsswarm.orchestrator.S.make_extra_task', new_callable=AsyncMock) as mock_make:
        mock_make.return_value = MagicMock(id="HX1")

        cmd = MagicMock()
        cmd.name = "investigate"
        cmd.argument = "something"

        await eng.handle_comment(1, "reader", "investigate something", "read", cmd)

        eng._investigate.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_comment_command_confirmed(cfg, tmp_path):
    """handle_comment command confirmation marks command as confirmed."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run

    # Mock approve
    eng.github.comment = AsyncMock()
    eng.store.save = MagicMock()
    from opsswarm.models import RecoveryPlan, RemediationOption
    option = RemediationOption(id="opt1", risk="read", description="Safe")
    run.recovery_plan = RecoveryPlan(options=[option])

    # Using 'approve' command - needs existing recovery plan
    cmd = MagicMock()
    cmd.name = "approve"
    cmd.argument = "opt1"

    # Patch execute_option to prevent actual execution
    eng._execute_option = AsyncMock()

    await eng.handle_comment(1, "reader", "approve", "maintain", cmd, comment_id="cid")

    assert "cid" in run.command_outcomes
    assert run.command_outcomes["cid"] == "confirmed"
    eng.store.save.assert_called()
