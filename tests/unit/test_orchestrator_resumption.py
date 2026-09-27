from unittest.mock import AsyncMock, MagicMock

import pytest

from opsswarm.models import RunState, RunRecord, CheckpointType
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load(open('config/test.yaml'))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_state_transition_investigating(cfg, tmp_path):
    """handle_comment resume with STATE_TRANSITION (INVESTIGATING) calls _investigate."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.STATE_TRANSITION.value,
            "state": RunState.INVESTIGATING.value
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.INVESTIGATING
    eng.runs[1] = run

    eng._investigate = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng._investigate.assert_called_once_with(run)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_state_transition_planning(cfg, tmp_path):
    """handle_comment resume with STATE_TRANSITION (PLANNING) calls _plan."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.STATE_TRANSITION.value,
            "state": RunState.PLANNING.value
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.PLANNING
    eng.runs[1] = run

    eng._plan = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng._plan.assert_called_once_with(run)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_checkpoint_state_transition_executing(cfg, tmp_path):
    """handle_comment resume with STATE_TRANSITION (EXECUTING) calls _verify."""
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))

    eng.ev.get_last_checkpoint = MagicMock(return_value={
        "payload": {
            "checkpoint_type": CheckpointType.STATE_TRANSITION.value,
            "state": RunState.EXECUTING.value
        }
    })

    run = RunRecord(run_id="test-run", issue_number=1)
    run.state = RunState.EXECUTING
    run.execution = MagicMock()  # Needs execution data for _verify to trigger
    eng.runs[1] = run

    eng._verify = AsyncMock()

    cmd = MagicMock()
    cmd.name = "resume"

    await eng.handle_comment(1, "reader", "resume", "read", cmd)

    eng._verify.assert_called_once_with(run)
