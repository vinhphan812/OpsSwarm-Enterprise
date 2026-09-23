import pytest
import yaml
from pathlib import Path
from opsswarm.models import RunState, CommandOutcome
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw

@pytest.fixture
def cfg():
    return yaml.safe_load(open('config/test.yaml'))

@pytest.fixture
def issue():
    return {
        'number': 1,
        'title': '[Incident] crash repro',
        'body': '## Incident',
        'labels': [{'name': 'opsswarm'}],
        'user': {'login': 'dev'}
    }

@pytest.mark.asyncio
async def test_crash_after_execution_before_mark(tmp_path, cfg, issue):
    """Test process crash AFTER execute_recovery success but BEFORE mark_command_executed()"""
    data_dir = str(tmp_path / "runtime")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    
    # Setup
    gh = FakeGitHub(issue)
    # Orchestrator needs recovery enabled
    # We need a response for:
    # 1. Task graph creation
    # 2. Task execution
    # 3. Root cause synthesis
    responses = [
        {"tasks": [{"id": "T1", "type": "OBSERVE", "objective": "check", "profile": "incident-manager"}]},
        {"task_id": "T1", "finding": "ok", "evidence": []},
        {"status": "confirmed", "proximate_cause": "none", "root_cause": "none"}
    ]
    orch = Orchestrator(cfg, gh, FakeOpenClaw(responses), data_dir, enable_recovery=True)
    
    # Start run (this triggers _investigate and uses the fake response)
    run = await orch.start_issue(1)
    
    # Manually mark as EXECUTING (not yet confirmed)
    comment_id = "GITHUB_COMMENT_123"
    run.mark_command_executing(comment_id)
    # Simulate the crash window
    orch.store.save(run)
    
    # Crash / Restart
    orch2 = Orchestrator(cfg, FakeGitHub(issue), FakeOpenClaw([]), data_dir, enable_recovery=True)
    
    # Check outcome state
    recovered_run = orch2.runs.get(1)
    
    assert recovered_run.get_command_outcome(comment_id) == CommandOutcome.UNKNOWN.value

    # This UNKNOWN state signals to the system: "I don't know if the write finished; 
    # the orchestrator must now verify the external state before retrying."
