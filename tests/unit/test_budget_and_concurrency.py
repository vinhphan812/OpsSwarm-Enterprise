# -*- coding: utf-8 -*-
"""Unit tests for Issue #26 — RunBudget and ConcurrencyLimiter."""

import asyncio
import time

import pytest

from opsswarm.orchestrator import ConcurrencyLimiter, RunBudget


class TestRunBudget:
    """Tests for RunBudget counters and limit checks."""

    def test_snapshot_starts_at_zero(self):
        """New budget has all counters at zero."""
        b = RunBudget(
            run_id="r1",
            max_tasks=10,
            max_openclaw_calls=50,
            max_wall_clock_seconds=300.0,
            max_corrective_actions=5,
            max_depth=10,
        )
        snap = b.snapshot()
        assert snap["tasks_executed"] == 0
        assert snap["openclaw_calls"] == 0
        assert snap["wall_clock_seconds"] == 0.0
        assert snap["corrective_actions"] == 0

    def test_mark_task_increments_counter(self):
        b = RunBudget("r1", 10, 50, 300, 5, 10)
        b.mark_task()
        b.mark_task()
        assert b.tasks_executed == 2
        assert b.snapshot()["tasks_executed"] == 2

    def test_mark_openclaw_call_increments_counter(self):
        b = RunBudget("r1", 10, 50, 300, 5, 10)
        b.mark_openclaw_call()
        b.mark_openclaw_call()
        b.mark_openclaw_call()
        assert b.openclaw_calls == 3

    def test_mark_corrective_action_increments_counter(self):
        b = RunBudget("r1", 10, 50, 300, 5, 10)
        b.mark_corrective_action()
        assert b.corrective_actions == 1

    def test_check_returns_false_when_under_limit(self):
        b = RunBudget("r1", max_tasks=3, max_openclaw_calls=5, max_wall_clock_seconds=60,
                       max_corrective_actions=2, max_depth=5)
        exceeded, reason = b.check()
        assert exceeded is False
        assert reason is None

    def test_check_returns_true_at_max_tasks(self):
        b = RunBudget("r1", max_tasks=3, max_openclaw_calls=5, max_wall_clock_seconds=60,
                       max_corrective_actions=2, max_depth=5)
        b.tasks_executed = 3
        exceeded, reason = b.check()
        assert exceeded is True
        assert "max_tasks" in reason
        assert "3" in reason

    def test_check_returns_true_at_max_openclaw_calls(self):
        b = RunBudget("r1", max_tasks=10, max_openclaw_calls=5, max_wall_clock_seconds=60,
                       max_corrective_actions=2, max_depth=5)
        b.openclaw_calls = 5
        exceeded, reason = b.check()
        assert exceeded is True
        assert "max_openclaw_calls" in reason

    def test_check_returns_true_at_max_wall_clock(self):
        b = RunBudget("r1", max_tasks=10, max_openclaw_calls=5, max_wall_clock_seconds=60.0,
                       max_corrective_actions=2, max_depth=5)
        b.wall_clock_seconds = 60.0
        exceeded, reason = b.check()
        assert exceeded is True
        assert "max_wall_clock_seconds" in reason

    def test_check_returns_true_at_max_corrective_actions(self):
        b = RunBudget("r1", max_tasks=10, max_openclaw_calls=5, max_wall_clock_seconds=60,
                       max_corrective_actions=3, max_depth=5)
        b.corrective_actions = 3
        exceeded, reason = b.check()
        assert exceeded is True
        assert "max_corrective_actions" in reason

    def test_snapshot_includes_all_limits(self):
        b = RunBudget("r2", max_tasks=7, max_openclaw_calls=20, max_wall_clock_seconds=900,
                       max_corrective_actions=4, max_depth=8)
        snap = b.snapshot()
        assert snap["max_tasks"] == 7
        assert snap["max_openclaw_calls"] == 20
        assert snap["max_wall_clock_seconds"] == 900
        assert snap["max_corrective_actions"] == 4

    def test_snapshot_includes_run_id(self):
        b = RunBudget("RUN-GH-42-abc", max_tasks=10, max_openclaw_calls=50, max_wall_clock_seconds=300,
                       max_corrective_actions=5, max_depth=10)
        assert b.snapshot()["run_id"] == "RUN-GH-42-abc"

    def test_check_respects_priority_max_tasks(self):
        """When multiple limits are hit, the first exceeded is reported."""
        b = RunBudget("r1", max_tasks=1, max_openclaw_calls=1, max_wall_clock_seconds=1,
                       max_corrective_actions=1, max_depth=5)
        b.tasks_executed = 1
        b.openclaw_calls = 1
        b.wall_clock_seconds = 1.0
        b.corrective_actions = 1
        exceeded, reason = b.check()
        assert exceeded is True
        # First condition checked is tasks — that is the one returned
        assert "max_tasks" in reason


class TestConcurrencyLimiter:
    """Tests for ConcurrencyLimiter (asyncio.Semaphore-backed)."""

    @pytest.mark.asyncio
    async def test_acquire_then_release(self):
        """Simple acquire/release leaves limiter in original state."""
        limiter = ConcurrencyLimiter("r1", max_parallel=2)
        await limiter.acquire()
        assert limiter.available == 1
        limiter.release()
        assert limiter.available == 2

    @pytest.mark.asyncio
    async def test_acquire_blocks_at_limit(self):
        """When all slots are taken, acquire() blocks until a release."""
        limiter = ConcurrencyLimiter("r1", max_parallel=2)
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.available == 0

        # Third acquire should not complete without a release
        # Use a short timeout to detect blocking
        acquired_third = False

        async def try_acquire():
            nonlocal acquired_third
            await limiter.acquire()
            acquired_third = True

        task = asyncio.create_task(try_acquire())
        # Give it a tiny moment to confirm it's blocked
        await asyncio.sleep(0.05)
        assert not acquired_third, "Third acquire should be blocked"
        # Release one slot, unblocking the third acquire
        limiter.release()
        await asyncio.wait_for(task, timeout=1.0)
        assert acquired_third

    @pytest.mark.asyncio
    async def test_multiple_concurrent_acquires(self):
        """Multiple tasks acquire and release concurrently."""
        limiter = ConcurrencyLimiter("r1", max_parallel=3)
        results: list[int] = []

        async def worker(i: int):
            await limiter.acquire()
            try:
                results.append(i)
            finally:
                limiter.release()

        await asyncio.gather(*(worker(i) for i in range(5)))
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_zero_max_parallel_guarded(self):
        """max_parallel=0 is clamped to 1."""
        limiter = ConcurrencyLimiter("r1", max_parallel=0)
        await limiter.acquire()
        assert limiter.available == 0
        limiter.release()

    @pytest.mark.asyncio
    async def test_negative_max_parallel_guarded(self):
        """Negative max_parallel is clamped to 1."""
        limiter = ConcurrencyLimiter("r1", max_parallel=-5)
        await limiter.acquire()
        limiter.release()
        assert limiter.available >= 1


class TestBudgetIntegration:
    """Smoke tests wiring budget + limiter together."""

    @pytest.mark.asyncio
    async def test_budget_and_limiter_work_together(self):
        """A single-run scenario: budget tracks counters, limiter gates concurrency."""
        budget = RunBudget(
            run_id="r1",
            max_tasks=5,
            max_openclaw_calls=10,
            max_wall_clock_seconds=120.0,
            max_corrective_actions=3,
            max_depth=5,
        )
        limiter = ConcurrencyLimiter("r1", max_parallel=2)
        results: list[int] = []

        async def simulate_task(i: int):
            exceeded, _ = budget.check()
            assert not exceeded
            await limiter.acquire()
            try:
                budget.mark_task()
                budget.mark_openclaw_call()
                results.append(i)
            finally:
                limiter.release()

        await asyncio.gather(*(simulate_task(i) for i in range(4)))
        assert len(results) == 4
        assert budget.tasks_executed == 4
        assert budget.openclaw_calls == 4

    @pytest.mark.asyncio
    async def test_budget_stops_at_limit(self):
        """Budget check returns True once counter hits limit."""
        budget = RunBudget(
            run_id="r1",
            max_tasks=2,
            max_openclaw_calls=5,
            max_wall_clock_seconds=60,
            max_corrective_actions=3,
            max_depth=5,
        )
        limiter = ConcurrencyLimiter("r1", max_parallel=4)

        async def task_with_budget_check(i: int):
            exceeded, _ = budget.check()
            if exceeded:
                return False
            await limiter.acquire()
            try:
                budget.mark_task()
            finally:
                limiter.release()
            return True

        # First 2 tasks succeed
        ok = await asyncio.gather(*(task_with_budget_check(i) for i in range(2)))
        assert all(ok)

        # 3rd task is blocked by budget
        exceeded, reason = budget.check()
        assert exceeded
        assert "max_tasks" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
