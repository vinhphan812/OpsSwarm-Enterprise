"""Unit tests for DemoController (demo orchestrator)."""
import pytest
from datetime import datetime, timedelta, timezone
from retailtwin_api.demo_runtime.demo import DemoOrchestrator, DemoPhase
from retailtwin_api.demo_runtime.services.twin import TwinService
from retailtwin_api.demo_runtime.services.simulation import SimulationService
from retailtwin_api.demo_runtime.guard.decision_context_guard import DCG
from retailtwin_api.demo_runtime.agents.executor import ExecutorAgent
from retailtwin_api.demo_runtime.agents.verifier import VerifierAgent


FIXTURES = [
    {"slot_id": "s01", "sku": "P001", "facings": 4, "shelf_quantity": 20, "backroom_quantity": 50},
    {"slot_id": "s02", "sku": "P002", "facings": 3, "shelf_quantity": 15, "backroom_quantity": 40},
    {"slot_id": "s03", "sku": "P003", "facings": 2, "shelf_quantity": 10, "backroom_quantity": 30},
    {"slot_id": "s04", "sku": "P017", "facings": 3, "shelf_quantity": 12, "backroom_quantity": 35},
    {"slot_id": "s05", "sku": "P005", "facings": 5, "shelf_quantity": 25, "backroom_quantity": 60},
]


class TestDemoOrchestrator:
    def test_reset_returns_run_id(self):
        orch = DemoOrchestrator()
        # orchestrator uses its own DEFAULT_FIXTURES (4 slots), not the passed ones
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        result = orch.reset()
        assert "run_id" in result
        assert result["phase"] == "idle"
        assert result["slots_loaded"] == 5  # FIXTURES has 5 slots

    def test_start_normal_flow(self):
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        result = orch.start(stale_context_test=False)
        assert result["run_id"] is not None
        assert result["phase"] == "complete"
        assert result["dcg_verdict"] == "ALLOW"
        assert result["executor_committed"] is True

    def test_start_stale_context_blocked(self):
        """G04 gate: stale context test must be blocked by DCG."""
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        result = orch.start(stale_context_test=True)
        assert result["dcg_verdict"] in ("REFRESH_REQUIRED", "DENY")
        assert result["executor_committed"] is False

    def test_status_after_reset(self):
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        status = orch.status()
        assert status.phase == DemoPhase.IDLE
        assert status.run_id != ""

    def test_status_after_start(self):
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        orch.start()
        status = orch.status()
        assert status.phase == DemoPhase.COMPLETE
        assert status.dcg_verdict == "ALLOW"
        assert status.executor_committed is True

    def test_timeline_has_events(self):
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        orch.start()
        events = orch.timeline_events()
        phases = {e.phase for e in events}
        assert "event" in phases
        assert "simulate" in phases
        assert "dcg" in phases
        assert "execute" in phases
        assert "verify" in phases

    def test_reset_clears_state(self):
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        r1 = orch.status().run_id
        orch.start()
        orch.reset()
        r2 = orch.status().run_id
        assert r1 != r2  # new run_id after reset

    def test_consecutive_runs(self):
        """Two consecutive runs produce independent results."""
        orch = DemoOrchestrator()
        orch.setup(TwinService, SimulationService, DCG, ExecutorAgent, VerifierAgent, FIXTURES)
        orch.reset()
        orch.start()
        run1_verdict = orch.status().dcg_verdict
        orch.reset()
        orch.start()
        run2_verdict = orch.status().dcg_verdict
        assert run1_verdict == run2_verdict == "ALLOW"
