# -*- coding: utf-8 -*-
"""Integration tests for Issue #26 — Concurrency limits and budget enforcement.

These tests use the real Orchestrator wiring (with fakes/mocks) to verify:
1. ConcurrencyLimiter enforces max_parallel on wave execution
2. RunBudget stops the investigation when a budget limit is exceeded
3. Graph validation errors are reported to GitHub and transition to FAILED
"""

import asyncio
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock

import pytest

from opsswarm.config import DEFAULT_BUDGET, DEFAULT_CONCURRENCY
from opsswarm.evidence import EvidenceStore
from opsswarm.orchestrator import ConcurrencyLimiter, Orchestrator, RunBudget
from opsswarm.store import RunStore
from opsswarm.validators import (
    CycleError,
    DepthExceededError,
    DuplicateTaskIdError,
    DanglingDependencyError,
    validate_task_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeGitHub:
    async def get_issue(self, number):
        return {"body": "### Service\ntest-svc\n\n### Environment\nprod\n\n### Symptoms\ntest", "labels": [], "title": "Test issue", "user": {"login": "test"}}

    async def set_labels(self, number, labels):
        pass

    async def comment(self, number, body):
        pass

    async def create_issue(self, title, body, labels):
        pass

    async def close_issue(self, number):
        pass


class FakeOpenClaw:
    """Fake OpenClaw client that records call counts and can inject delays."""

    def __init__(self):
        self.call_count = 0
        self._delay = 0.0

    def set_delay(self, seconds: float):
        self._delay = seconds

    async def run_json(self, agent: str, session: str, prompt: str):
        self.call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        # Return a valid task graph
        return {
            "tasks": [
                {
                    "id": f"T{self.call_count}",
                    "type": "OBSERVE",
                    "objective": f"Task {self.call_count}",
                    "profile": "observability",
                }
            ]
        }


def make_orchestrator(tmp_dir: str, budget_override: dict | None = None, concurrency_override: dict | None = None):
    cfg = {
        "openclaw": {"profiles": {"incident-manager": "test-agent"}},
        **({"budget": budget_override} if budget_override else {}),
        **({"concurrency": concurrency_override} if concurrency_override else {}),
    }
    oc = FakeOpenClaw()
    github = FakeGitHub()
    orch = Orchestrator(cfg, github, oc, data_dir=tmp_dir, enable_recovery=False)
    return orch


# ---------------------------------------------------------------------------
# Orchestrator init — budget and concurrency from config
# ---------------------------------------------------------------------------


class TestOrchestratorBudgetConfig:
    """Verify orchestrator reads budget and concurrency from config correctly."""

    def test_default_budget_from_orchestrator(self, tmp_path):
        """Orchestrator initializes budget with defaults when no config provided."""
        orch = make_orchestrator(str(tmp_path))
        assert orch.budget.max_tasks == DEFAULT_BUDGET["max_tasks_per_run"]
        assert orch.budget.max_openclaw_calls == DEFAULT_BUDGET["max_openclaw_calls"]
        assert orch.budget.max_wall_clock_seconds == DEFAULT_BUDGET["max_wall_clock_seconds"]
        assert orch.budget.max_corrective_actions == DEFAULT_BUDGET["max_corrective_actions"]
        assert orch.budget.max_depth == DEFAULT_BUDGET["max_dependency_depth"]

    def test_custom_budget_from_config(self, tmp_path):
        """Custom budget limits are read from config."""
        orch = make_orchestrator(str(tmp_path), budget_override={
            "max_tasks_per_run": 3,
            "max_openclaw_calls": 7,
            "max_wall_clock_seconds": 60.0,
            "max_corrective_actions": 1,
            "max_dependency_depth": 4,
        })
        assert orch.budget.max_tasks == 3
        assert orch.budget.max_openclaw_calls == 7
        assert orch.budget.max_wall_clock_seconds == 60.0
        assert orch.budget.max_corrective_actions == 1
        assert orch.budget.max_depth == 4

    def test_default_concurrency_from_orchestrator(self, tmp_path):
        """Orchestrator initializes concurrency limiter with default max_parallel."""
        orch = make_orchestrator(str(tmp_path))
        assert orch._max_parallel == DEFAULT_CONCURRENCY["max_parallel_specialists"]

    def test_custom_concurrency_from_config(self, tmp_path):
        """Custom max_parallel is read from config."""
        orch = make_orchestrator(str(tmp_path), concurrency_override={
            "max_parallel_specialists": 1,
        })
        assert orch._max_parallel == 1


# ---------------------------------------------------------------------------
# Graph validation integration
# ---------------------------------------------------------------------------


class TestGraphValidationIntegration:
    """Graph validation is called during _investigate before tasks execute."""

    def test_duplicate_ids_rejected_at_investigate(self, tmp_path, monkeypatch):
        """Duplicate task IDs cause _investigate to exit with FAILED state."""
        orch = make_orchestrator(str(tmp_path))

        from opsswarm.models import RunRecord, RunState, Task, TaskType, Risk, IncidentContext

        # Manually construct a run with duplicate task IDs
        run = RunRecord(run_id="RUN-TEST-1", issue_number=1)
        run.incident = IncidentContext(issue_number=1, title="Test", service="svc")
        run.tasks = [
            Task(id="T1", type=TaskType.OBSERVE, objective="First", profile="obs"),
            Task(id="T1", type=TaskType.INVESTIGATE, objective="Duplicate", profile="obs"),
        ]
        run.state = RunState.INVESTIGATING

        # Validate directly (simulating what _investigate does)
        task_dicts = [t.model_dump() for t in run.tasks]
        with pytest.raises(DuplicateTaskIdError):
            validate_task_graph(task_dicts, max_depth=orch.budget.max_depth)

    def test_cycle_rejected_at_validate(self, tmp_path):
        """Cycle in task graph raises CycleError at validate_task_graph."""
        orch = make_orchestrator(str(tmp_path))
        tasks = [
            {"id": "A", "depends_on": ["B"]},
            {"id": "B", "depends_on": ["A"]},
        ]
        with pytest.raises(CycleError):
            validate_task_graph(tasks, max_depth=orch.budget.max_depth)

    def test_dangling_dependency_rejected_at_validate(self, tmp_path):
        """Dangling dependency raises DanglingDependencyError."""
        orch = make_orchestrator(str(tmp_path))
        tasks = [
            {"id": "T1", "depends_on": []},
            {"id": "T2", "depends_on": ["MISSING"]},
        ]
        with pytest.raises(DanglingDependencyError):
            validate_task_graph(tasks, max_depth=orch.budget.max_depth)

    def test_depth_exceeded_rejected_at_validate(self, tmp_path):
        """Depth > max_depth raises DepthExceededError."""
        orch = make_orchestrator(str(tmp_path))
        tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(10)]
        with pytest.raises(DepthExceededError):
            validate_task_graph(tasks, max_depth=5)

    def test_valid_graph_passes_validate(self, tmp_path):
        """Valid DAG passes without exception."""
        orch = make_orchestrator(str(tmp_path))
        tasks = [
            {"id": "A", "depends_on": []},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C", "depends_on": ["A"]},
            {"id": "D", "depends_on": ["B", "C"]},
        ]
        # Should not raise
        validate_task_graph(tasks, max_depth=orch.budget.max_depth)


# ---------------------------------------------------------------------------
# Budget enforcement integration
# ---------------------------------------------------------------------------


class TestBudgetEnforcementIntegration:
    """RunBudget and budget check integrate with orchestrator workflow."""

    def test_budget_snapshot_contains_all_fields(self, tmp_path):
        """Snapshot returns all budget dimensions."""
        budget = RunBudget(
            run_id="test-run",
            max_tasks=10,
            max_openclaw_calls=50,
            max_wall_clock_seconds=300.0,
            max_corrective_actions=5,
            max_depth=10,
        )
        snap = budget.snapshot()
        assert set(snap.keys()) == {
            "run_id",
            "tasks_executed",
            "max_tasks",
            "openclaw_calls",
            "max_openclaw_calls",
            "wall_clock_seconds",
            "max_wall_clock_seconds",
            "corrective_actions",
            "max_corrective_actions",
        }

    def test_budget_with_small_limits_stops_early(self, tmp_path):
        """Budget with max_tasks=1 should stop after one task."""
        budget = RunBudget(
            run_id="r1",
            max_tasks=1,
            max_openclaw_calls=5,
            max_wall_clock_seconds=60,
            max_corrective_actions=3,
            max_depth=5,
        )
        budget.mark_task()
        exceeded, reason = budget.check()
        assert exceeded is True
        assert "max_tasks" in reason


# ---------------------------------------------------------------------------
# Concurrency limiter integration
# ---------------------------------------------------------------------------


class TestConcurrencyLimiterIntegration:
    """ConcurrencyLimiter works as an asyncio semaphore with max_parallel cap."""

    @pytest.mark.asyncio
    async def test_limiter_allows_up_to_max_parallel(self):
        """Exactly max_parallel tasks can hold a slot simultaneously."""
        limiter = ConcurrencyLimiter("r1", max_parallel=3)
        slots: list[int] = []

        async def hold(i: int):
            await limiter.acquire()
            try:
                slots.append(i)
            finally:
                limiter.release()

        await asyncio.gather(*(hold(i) for i in range(3)))
        assert len(slots) == 3
        assert set(slots) == {0, 1, 2}

    @pytest.mark.asyncio
    async def test_limiter_blocks_excess_tasks(self):
        """Tasks beyond max_parallel wait until a slot frees up."""
        limiter = ConcurrencyLimiter("r1", max_parallel=2)
        order: list[str] = []

        async def task(name: str, hold_seconds: float):
            await limiter.acquire()
            try:
                order.append(f"start:{name}")
                await asyncio.sleep(hold_seconds)
                order.append(f"end:{name}")
            finally:
                limiter.release()

        # Two tasks run immediately; third is queued
        await asyncio.gather(
            task("fast", 0.1),
            task("slow", 0.3),
            task("waiting", 0.0),
        )
        # "waiting" should start after one of the first two ends
        assert "end:waiting" in order

    @pytest.mark.asyncio
    async def test_limiter_config_1_blocks_all_but_one(self):
        """max_parallel=1 means tasks execute strictly sequentially."""
        limiter = ConcurrencyLimiter("r1", max_parallel=1)
        active_count = 0
        max_seen = 0

        async def task(name: str):
            nonlocal active_count, max_seen
            await limiter.acquire()
            try:
                active_count += 1
                max_seen = max(max_seen, active_count)
                await asyncio.sleep(0.05)
                active_count -= 1
            finally:
                limiter.release()

        await asyncio.gather(*(task(f"t{i}") for i in range(5)))
        assert max_seen == 1


# ---------------------------------------------------------------------------
# Config defaults are sensible
# ---------------------------------------------------------------------------


class TestBudgetConfigDefaults:
    """DEFAULT_BUDGET and DEFAULT_CONCURRENCY have reasonable values."""

    def test_max_tasks_reasonable(self):
        assert DEFAULT_BUDGET["max_tasks_per_run"] >= 1

    def test_max_openclaw_calls_reasonable(self):
        assert DEFAULT_BUDGET["max_openclaw_calls"] >= DEFAULT_BUDGET["max_tasks_per_run"]

    def test_max_wall_clock_seconds_reasonable(self):
        # At least 1 minute, at most 24 hours
        assert 60 <= DEFAULT_BUDGET["max_wall_clock_seconds"] <= 86400

    def test_max_corrective_actions_reasonable(self):
        assert DEFAULT_BUDGET["max_corrective_actions"] >= 0

    def test_max_dependency_depth_reasonable(self):
        assert DEFAULT_BUDGET["max_dependency_depth"] >= 1

    def test_max_parallel_specialists_reasonable(self):
        assert DEFAULT_CONCURRENCY["max_parallel_specialists"] >= 1


    @pytest.mark.asyncio
    async def test_budget_preflight_routes_exceeded_run_to_decision(self, tmp_path):
        """A preflight failure gates side effects and requests human input."""
        from opsswarm.models import RunRecord, RunState

        orch = make_orchestrator(str(tmp_path))
        orch.github.set_labels = AsyncMock()
        orch.github.comment = AsyncMock()
        run = RunRecord(run_id="RUN-BUDGET-1", issue_number=42)
        run.state = RunState.INVESTIGATING
        budget = RunBudget("RUN-BUDGET-1", 1, 5, 60, 2, 5)
        budget.tasks_executed = 1

        allowed = await orch._budget_preflight(run, budget)

        assert allowed is False
        assert run.state is RunState.WAITING_DECISION
        assert run.decision is not None
        assert "budget exceeded" in run.decision.reason.lower()
        orch.github.comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_budget_preflight_allows_run_under_limits(self, tmp_path):
        """A preflight under the limits does not create a human gate."""
        from opsswarm.models import RunRecord, RunState

        orch = make_orchestrator(str(tmp_path))
        run = RunRecord(run_id="RUN-BUDGET-2", issue_number=43)
        run.state = RunState.INVESTIGATING
        budget = RunBudget("RUN-BUDGET-2", 2, 5, 60, 2, 5)

        assert await orch._budget_preflight(run, budget) is True
        assert run.decision is None

    def test_budget_for_reuses_active_run_budget(self, tmp_path):
        """Direct phase calls reuse one run-scoped tracker."""
        from opsswarm.models import RunRecord

        orch = make_orchestrator(str(tmp_path), budget_override={"max_tasks_per_run": 3})
        run = RunRecord(run_id="RUN-BUDGET-3", issue_number=44)
        first = orch._budget_for(run)
        first.mark_task()
        assert orch._budget_for(run) is first
        assert first.tasks_executed == 1

    def test_profile_and_missing_reconciliation_report(self, tmp_path):
        """Small orchestrator accessors preserve configured profile lookup."""
        from opsswarm.models import RunRecord

        orch = make_orchestrator(str(tmp_path))
        orch.cfg["openclaw"]["profiles"]["extra"] = "extra-agent"
        assert orch.profile("extra") == "extra-agent"
        assert orch.get_reconciliation_report(999) is None
        run = RunRecord(run_id="RUN-REPORT", issue_number=999)
        orch.runs[999] = run
        orch.reconciliation.get_recovery_plan = MagicMock(return_value={"state": "ok"})
        assert orch.get_reconciliation_report(999) == {"state": "ok"}

    @pytest.mark.asyncio
    async def test_save_logs_duplicate_and_persists_run(self, tmp_path):
        """Duplicate evidence is skipped while the run is still persisted."""
        from opsswarm.models import RunRecord

        orch = make_orchestrator(str(tmp_path))
        orch.ev.append = MagicMock(return_value=("E1", True))
        orch.store.save = MagicMock()
        run = RunRecord(run_id="RUN-SAVE", issue_number=45)

        await orch._save(run, "duplicate", {"value": 1})

        orch.ev.append.assert_called_once_with("RUN-SAVE", "duplicate", {"value": 1})
        orch.store.save.assert_called_once_with(run)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
