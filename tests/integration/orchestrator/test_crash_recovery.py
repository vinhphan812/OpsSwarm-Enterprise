"""Integration tests for process-boundary crash and restart recovery.

These tests verify that:
1. Non-terminal runs are persisted correctly
2. Process crashes don't lose state or produce duplicates
3. Evidence is preserved across restart boundaries
4. Command outcomes survive process restart

Issue #9: Crash recovery reliability
"""

import json
from pathlib import Path

import pytest
import yaml

from opsswarm.commands import parse_command
from opsswarm.models import RunState, RunRecord, CommandOutcome
from opsswarm.orchestrator import Orchestrator
from opsswarm.reconciliation import ReconciliationManager
from opsswarm.store import RunStore
from tests.fakes import FakeGitHub, FakeOpenClaw


@pytest.fixture
def cfg():
    return yaml.safe_load(open('config/test.yaml'))


@pytest.fixture
def issue():
    return {
        'number': 1,
        'title': '[Incident] booking fails',
        'body': '## Incident\n\n### Service\nbooking-api\n\n### Symptoms\nHTTP 500\n\n### Customer impact\nCheckout blocked\n\n### Environment\nproduction\n',
        'labels': [{'name': 'opsswarm'}, {'name': 'sev:2'}],
        'user': {'login': 'dev'}
    }


def investigation_and_rca():
    """Standard investigation + RCA response sequence."""
    return [
        # S1: Parse incident
        {'tasks': [
            {'id': 'T1', 'type': 'OBSERVE', 'objective': 'inspect metrics',
             'profile': 'observability-investigator', 'required_capabilities': ['metrics.read'],
             'risk': 'read', 'depends_on': [], 'parallelizable': True, 'expected_output': 'Finding',
             'status': 'PENDING'}
        ]},
        # S4: Finding
        {'task_id': 'T1', 'finding': 'errors rose after deploy', 'evidence': ['metric:5xx', 'deploy:v3'],
         'hypothesis': 'bad deploy', 'confidence': 0.95, 'recommended_next_action': 'rollback', 'raw': {}},
        # RCA: Root cause
        {'status': 'confirmed', 'proximate_cause': 'bad deploy', 'root_cause': 'missing regression gate',
         'causal_chain': ['v3 deploy', 'connection leak', '5xx'], 'evidence_refs': ['metric:5xx', 'deploy:v3'],
         'confidence': 0.93, 'remediation_options': ['rollback'], 'human_input_question': None,
         'corrective_actions': ['add regression gate']},
    ]


def waiting_approval_responses():
    """Response sequence that ends in WAITING_APPROVAL state."""
    return investigation_and_rca() + [
        # S3: Recovery plan with risky option that requires approval
        {'options': [
            {'id': 'rollback', 'description': 'rollback', 'profile': 'recovery-responder',
             'risk': 'risky_write', 'estimated_recovery': '3m', 'rationale': 'best',
             'capabilities': ['deploy.rollback']}
        ], 'recommended_option': 'rollback', 'confidence': 0.9,
            'requires_business_input': False, 'business_input_question': None},
    ]


@pytest.mark.integration
class TestCrashRecovery:
    """Test process-boundary crash and restart recovery."""

    @pytest.mark.asyncio
    async def test_persisted_run_recovers_after_restart(self, tmp_path, cfg, issue):
        """Test that a run in WAITING_APPROVAL state survives process restart."""
        # Create a temporary data directory
        data_dir = str(tmp_path / "runtime")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Phase 1: Create a run and advance to WAITING_APPROVAL
        responses = waiting_approval_responses()
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(responses)
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        # Start the issue and progress to WAITING_APPROVAL
        run1 = await orch1.start_issue(1)

        # Verify we're in WAITING_APPROVAL state
        assert run1.state == RunState.WAITING_APPROVAL, f"Expected WAITING_APPROVAL, got {run1.state}"
        run_id = run1.run_id

        # Capture state for verification
        initial_evidence = orch1.ev.list(run_id)
        initial_evidence_kinds = [e['kind'] for e in initial_evidence]

        # Phase 2: Simulate process crash - create new Orchestrator instance
        # This is what happens after a process restart
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])  # No responses needed for recovery
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Phase 3: Verify recovered state
        recovered_run = orch2.runs.get(1)
        assert recovered_run is not None, "Run should be recovered after restart"
        assert recovered_run.run_id == run_id, "Run ID should be preserved"
        assert recovered_run.state == RunState.WAITING_APPROVAL, \
            f"State should be WAITING_APPROVAL after recovery, got {recovered_run.state}"

        # Verify evidence is preserved (not duplicated)
        recovered_evidence = orch2.ev.list(run_id)
        assert len(recovered_evidence) == len(initial_evidence), \
            "Evidence count should be preserved after recovery (no duplicates)"
        recovered_kinds = [e['kind'] for e in recovered_evidence]
        assert recovered_kinds == initial_evidence_kinds, \
            "Evidence kinds should match after recovery"

        print(f"✓ Run {run_id} recovered to WAITING_APPROVAL state")

    @pytest.mark.asyncio
    async def test_no_duplicate_side_effects_after_recovery(self, tmp_path, cfg, issue):
        """Test that restart doesn't produce duplicate side effects."""
        data_dir = str(tmp_path / "runtime2")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Phase 1: Create run and add evidence
        responses = waiting_approval_responses()
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(responses)
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        run1 = await orch1.start_issue(1)
        run_id = run1.run_id

        # Get initial evidence count
        initial_count = len(orch1.ev.list(run_id))
        initial_evidence_keys = {e.get('signature') for e in orch1.ev.list(run_id)}

        # Phase 2: Simulate restart
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Phase 3: Check for duplicates
        recovered_evidence = orch2.ev.list(run_id)
        recovered_count = len(recovered_evidence)
        recovered_signatures = {e.get('signature') for e in recovered_evidence}

        # Verify no duplicate signatures
        assert recovered_signatures == initial_evidence_keys, \
            "Evidence signatures should match (no duplicates)"

        # Verify evidence count is unchanged
        assert recovered_count == initial_count, \
            f"Evidence count should not increase after restart: {initial_count} -> {recovered_count}"

        print(f"✓ No duplicate side effects: {recovered_count} evidence records preserved")

    @pytest.mark.asyncio
    async def test_command_outcomes_survive_restart(self, tmp_path, cfg, issue):
        """Test that command outcomes (RECEIVED/EXECUTED) persist across restart."""
        data_dir = str(tmp_path / "runtime3")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Phase 1: Create run with a command marked as received
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(waiting_approval_responses())
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        run1 = await orch1.start_issue(1)
        run_id = run1.run_id

        # Simulate receiving a command (like /opsswarm approve)
        comment_id = "GITHUB_COMMENT_123"
        run1.mark_command_received(comment_id)
        run1.mark_command_executing(comment_id)
        run1.mark_command_confirmed(comment_id)
        orch1.store.save(run1)

        # Verify command was marked as confirmed
        assert run1.is_command_confirmed(comment_id), "Command should be marked confirmed"
        assert run1.get_command_outcome(comment_id) == CommandOutcome.CONFIRMED.value

        # Phase 2: Simulate restart - reload run from disk
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Phase 3: Verify command outcome persisted
        recovered_run = orch2.runs.get(1)
        assert recovered_run is not None, "Run should be recovered"

        # Command should still be marked as confirmed after restart
        assert recovered_run.is_command_confirmed(comment_id), \
            "Command outcome should persist across restart"
        assert recovered_run.get_command_outcome(comment_id) == CommandOutcome.CONFIRMED.value

        # Also verify legacy field for backward compatibility
        assert comment_id in recovered_run.executed_commands, \
            "Legacy executed_commands should also persist"

        print(f"✓ Command outcome persisted across restart: {comment_id}")

    @pytest.mark.asyncio
    async def test_checkpoints_survive_restart(self, tmp_path, cfg, issue):
        """Test that checkpoints are preserved and loadable after restart."""
        data_dir = str(tmp_path / "runtime4")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Create store with checkpoints enabled
        store = RunStore(data_dir, enable_checkpoints=True)

        # Create a run
        run = RunRecord(run_id="test-checkpoint-run", issue_number=999)
        run.state = RunState.EXECUTING
        run.checkpoint_sequence = 0

        # Save initial run
        store.save(run)

        # Create a checkpoint
        checkpoint_data = '{"phase": "execution", "task_id": "T1"}'
        store.save_checkpoint(run, checkpoint_data)

        # Verify checkpoint file exists
        checkpoint_file = Path(data_dir) / "runs" / f"{run.run_id}.checkpoint"
        assert checkpoint_file.exists(), "Checkpoint file should exist"

        # Phase 2: Simulate restart - load checkpoint
        store2 = RunStore(data_dir, enable_checkpoints=True)
        loaded_checkpoint = store2.load_checkpoint(run.run_id)

        assert loaded_checkpoint is not None, "Checkpoint should be loadable after restart"
        assert loaded_checkpoint.run_id == run.run_id, "Run ID should match"
        assert loaded_checkpoint.checkpoint_sequence == 1, "Checkpoint sequence should increment"
        assert loaded_checkpoint.state == RunState.EXECUTING, "State should be preserved"

        print(f"✓ Checkpoint {loaded_checkpoint.checkpoint_sequence} survived restart")

    @pytest.mark.asyncio
    async def test_recovery_manager_finds_non_terminal_runs(self, tmp_path, cfg, issue):
        """Test that ReconciliationManager correctly identifies non-terminal runs."""
        data_dir = str(tmp_path / "runtime5")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Create runs in different states
        store = RunStore(data_dir)

        # Non-terminal run (WAITING_APPROVAL)
        run1 = RunRecord(run_id="non-terminal-1", issue_number=101)
        run1.state = RunState.WAITING_APPROVAL

        # Terminal run (RESOLVED)
        run2 = RunRecord(run_id="terminal-resolved", issue_number=102)
        run2.state = RunState.RESOLVED

        # Terminal run (ABORTED)
        run3 = RunRecord(run_id="terminal-aborted", issue_number=103)
        run3.state = RunState.ABORTED

        # Non-terminal run (EXECUTING)
        run4 = RunRecord(run_id="non-terminal-2", issue_number=104)
        run4.state = RunState.EXECUTING

        # Save all runs
        store.save(run1)
        store.save(run2)
        store.save(run3)
        store.save(run4)

        # Create reconciliation manager
        recon = ReconciliationManager(data_dir)

        # Load non-terminal runs
        non_terminal = recon.load_non_terminal_runs()
        non_terminal_ids = {r.run_id for r in non_terminal}

        # Verify only non-terminal runs are returned
        assert "non-terminal-1" in non_terminal_ids, "WAITING_APPROVAL should be non-terminal"
        assert "non-terminal-2" in non_terminal_ids, "EXECUTING should be non-terminal"
        assert "terminal-resolved" not in non_terminal_ids, "RESOLVED should be terminal"
        assert "terminal-aborted" not in non_terminal_ids, "ABORTED should be terminal"

        print(f"✓ Non-terminal runs identified correctly: {non_terminal_ids}")

    @pytest.mark.asyncio
    async def test_atomic_write_prevents_corruption(self, tmp_path):
        """Test that atomic writes prevent partial file corruption."""
        data_dir = str(tmp_path / "runtime6")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        store = RunStore(data_dir, enable_atomic_writes=True)

        # Create and save a run
        run = RunRecord(run_id="atomic-test", issue_number=201)
        run.state = RunState.WAITING_APPROVAL

        store.save(run)

        # Verify the file exists and is valid JSON
        run_file = Path(data_dir) / "runs" / f"{run.run_id}.json"
        assert run_file.exists(), "Run file should exist"

        # Verify no stale tmp files
        tmp_file = Path(data_dir) / "runs" / f".{run.run_id}.tmp"
        assert not tmp_file.exists(), "No stale tmp file should exist"

        # Verify content is valid JSON
        with open(run_file) as f:
            loaded = json.load(f)
        assert loaded['run_id'] == run.run_id, "Run ID should match"
        assert loaded['state'] == 'WAITING_APPROVAL', "State should match"

        print(f"✓ Atomic write verified: no temp file leftover")

    @pytest.mark.asyncio
    async def test_run_state_transitions_persist(self, tmp_path, cfg, issue):
        """Test that full state transition sequence persists across restart."""
        data_dir = str(tmp_path / "runtime7")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Create responses that go all the way to RESOLVED
        full_responses = waiting_approval_responses() + [
            # S5: Execution result
            {'option_id': 'rollback', 'success': True, 'summary': 'rolled back',
             'evidence': ['receipt:2'], 'ambiguous': False, 'raw': {}},
            # S7: Verification
            {'verified': True, 'summary': 'service restored', 'evidence': ['sli:ok'],
             'confidence': 0.98, 'raw': {}},
        ]

        # Create a full run through multiple states
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(full_responses)
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        run1 = await orch1.start_issue(1)
        run_id = run1.run_id

        # Record the state sequence
        state_sequence = [run1.state]

        # Approve and continue to completion
        await orch1.handle_comment(
            1, 'dev', '/opsswarm approve rollback', 'maintain',
            parse_command('/opsswarm approve rollback')
        )
        state_sequence.append(orch1.runs[1].state)

        # Verify we progressed to terminal state
        assert state_sequence[-1] == RunState.RESOLVED

        # Now simulate restart - should still be resolved
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Verify final state persisted
        recovered_run = orch2.runs.get(1)
        assert recovered_run is not None, "Run should be recovered"
        assert recovered_run.state == state_sequence[-1], \
            f"Final state should persist: expected {state_sequence[-1]}, got {recovered_run.state}"

        print(f"✓ State sequence persisted: {[s.value for s in state_sequence]}")


@pytest.mark.integration
class TestEvidenceDedupAfterRestart:
    """Test that evidence deduplication works correctly after restart."""

    @pytest.mark.asyncio
    async def test_duplicate_evidence_skipped_after_restart(self, tmp_path, cfg, issue):
        """Test that evidence with same signature is deduplicated after restart."""
        data_dir = str(tmp_path / "runtime8")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Phase 1: Create run and add evidence
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(waiting_approval_responses())
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        run1 = await orch1.start_issue(1)
        run_id = run1.run_id

        # Add a custom evidence (different from those created by the workflow)
        # Using a unique kind and payload to ensure it's new
        custom_payload = {
            'task_id': 'T-custom',
            'finding': 'custom crash recovery test finding',
            'evidence': ['test:evidence'],
            'confidence': 0.99
        }
        eid1, is_dup1 = orch1.ev.append(run_id, 'test.custom_finding', custom_payload)
        assert is_dup1 is False, "First evidence should not be duplicate"

        # Phase 2: Simulate restart
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Phase 3: Try to add same evidence (should be deduplicated)
        # The evidence store should load existing signatures from disk
        eid2, is_dup2 = orch2.ev.append(run_id, 'test.custom_finding', custom_payload)

        assert is_dup2 is True, "Same evidence should be detected as duplicate after restart"

        print(f"✓ Evidence deduplication works after restart")

    @pytest.mark.asyncio
    async def test_idempotency_keys_preserved_after_restart(self, tmp_path, cfg, issue):
        """Test that webhook idempotency keys persist across restart."""
        data_dir = str(tmp_path / "runtime9")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        delivery_id = "webhook-delivery-abc123"

        # Phase 1: Create run with idempotency key
        gh = FakeGitHub(issue)
        oc = FakeOpenClaw(waiting_approval_responses())
        orch1 = Orchestrator(cfg, gh, oc, data_dir, enable_recovery=False)

        run1 = await orch1.start_issue(1, delivery_id=delivery_id)

        # Verify idempotency key was stored
        assert delivery_id in run1.idempotency_keys, "Idempotency key should be stored"

        # Phase 2: Simulate restart
        gh2 = FakeGitHub(issue)
        oc2 = FakeOpenClaw([])
        orch2 = Orchestrator(cfg, gh2, oc2, data_dir, enable_recovery=True)

        # Phase 3: Try to start same issue with same delivery ID
        # Should return existing run (not create duplicate)
        run2 = await orch2.start_issue(1, delivery_id=delivery_id)

        # Should get existing run (idempotency check works)
        assert run2.run_id == run1.run_id, "Should return existing run for duplicate delivery"
        assert run2.idempotency_keys is not None, "Idempotency keys should persist"

        print(f"✓ Idempotency keys preserved: {delivery_id}")
