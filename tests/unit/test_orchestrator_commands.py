"""Extended orchestrator tests covering command handling paths: abort, provide, reject."""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from opsswarm.models import RunState, RunRecord, RecoveryPlan, RemediationOption
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load(open('config/test.yaml'))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_command_abort(cfg, tmp_path):
    """handle_comment abort command sets ABORTED state."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run
    eng.store.save = MagicMock()
    eng.github.comment = AsyncMock()

    cmd = MagicMock()
    cmd.name = "abort"
    cmd.argument = ""

    await eng.handle_comment(1, "tester", "abort", "maintain", cmd)

    assert run.state == RunState.ABORTED
    assert "Aborted" in run.error
    assert eng.github.comment.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_command_provide(cfg, tmp_path):
    """handle_comment provide command adds input and re-investigates."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run
    eng.store.save = MagicMock()
    eng._save = AsyncMock()
    eng._investigate = AsyncMock()

    cmd = MagicMock()
    cmd.name = "provide"
    cmd.argument = "new input"

    await eng.handle_comment(1, "tester", "provide new input", "maintain", cmd)

    assert len(run.human_inputs) == 1
    assert run.human_inputs[0]["text"] == "new input"
    eng._investigate.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_command_reject(cfg, tmp_path):
    """handle_comment reject command sets REJECTED status and WAITING_DECISION."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    # Assuming decision exists for rejection
    run.decision = MagicMock()
    eng.runs[1] = run
    eng.store.save = MagicMock()
    eng.github.comment = AsyncMock()

    cmd = MagicMock()
    cmd.name = "reject"
    cmd.argument = ""

    await eng.handle_comment(1, "tester", "reject", "maintain", cmd)

    assert run.decision.status == "REJECTED"
    assert run.state == RunState.WAITING_DECISION
    assert eng.github.comment.call_count == 1
