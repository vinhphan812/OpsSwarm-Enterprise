from unittest.mock import MagicMock

import pytest

from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    import yaml
    return yaml.safe_load(open('config/test.yaml'))


@pytest.mark.asyncio
async def test_recover_runs_missing_run_in_self_runs(cfg, tmp_path):
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    # disable recovery in init
    eng = Orchestrator(cfg, gh, oc, str(tmp_path), enable_recovery=False)

    # Create a non-terminal run
    from opsswarm.models import RunRecord, RunState
    nr = RunRecord(run_id="run1", issue_number=101)
    nr.state = RunState.WAITING_APPROVAL

    # Mock load_non_terminal_runs to return it
    eng.reconciliation.load_non_terminal_runs = MagicMock(return_value=[nr])

    # Make sure it's not in self.runs
    eng.runs = {}

    # Mock save
    eng.store.save = MagicMock()

    # Mock recovery_result
    eng.reconciliation.recover_run = MagicMock(return_value=MagicMock(recovered=True, message="ok"))

    # Run recovery
    eng._recover_runs()

    # Verify recovery_run was called with nr
    eng.reconciliation.recover_run.assert_called_with(nr)


@pytest.mark.asyncio
async def test_recover_runs_failed_recovery(cfg, tmp_path):
    gh = FakeGitHub({'number': 1})
    oc = FakeOpenClaw([])
    # disable recovery in init
    eng = Orchestrator(cfg, gh, oc, str(tmp_path), enable_recovery=False)

    # Create a non-terminal run
    from opsswarm.models import RunRecord
    nr = RunRecord(run_id="run1", issue_number=101)

    # Mock load_non_terminal_runs
    eng.reconciliation.load_non_terminal_runs = MagicMock(return_value=[nr])
    eng.runs = {101: nr}

    # Mock recover_run to return failed
    eng.reconciliation.recover_run = MagicMock(return_value=MagicMock(recovered=False, message="failed"))

    # Run recovery
    eng._recover_runs()

    # Verify recover_run was called
    eng.reconciliation.recover_run.assert_called_with(nr)
