from unittest.mock import MagicMock

import pytest

from opsswarm.models import RunRecord, CommandOutcome
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load(open('config/test.yaml'))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recover_runs_executing_command_to_unknown(cfg, tmp_path):
    """Run recovery marks EXECUTING commands in crash window as UNKNOWN."""
    gh = FakeGitHub(None)
    oc = FakeOpenClaw([])
    eng = Orchestrator(cfg, gh, oc, str(tmp_path), enable_recovery=False)  # Disable auto-recovery

    run = RunRecord(run_id="test-run", issue_number=1)
    run.command_outcomes = {"cmd1": CommandOutcome.EXECUTING.value}
    eng.runs[1] = run
    eng.store.save = MagicMock()

    # Mock reconciliation manager
    eng.reconciliation.load_non_terminal_runs = MagicMock(return_value=[run])
    eng.reconciliation.recover_run = MagicMock(return_value=MagicMock(recovered=True, message="Recovered"))

    eng._recover_runs()

    assert run.command_outcomes["cmd1"] == CommandOutcome.UNKNOWN.value
    eng.store.save.assert_called()
    assert eng.reconciliation.recover_run.called
