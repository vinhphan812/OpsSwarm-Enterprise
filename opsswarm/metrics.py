from collections import Counter


class Metrics:
    def __init__(self):
        self.runs = Counter()  # state: count
        self.commands = Counter()  # outcome: count
        self.verifications = Counter()  # verified: count
        # Minimal histogram implementation (count and sum only)
        self.histograms_count = Counter()
        self.histograms_sum = Counter()
        # Issue #26 — Budget metric families
        self.budget_tasks = Counter()       # total tasks executed per run bucket
        self.budget_openclaw_calls = Counter()  # openclaw call counts
        self.budget_wall_clock_seconds = Counter()  # wall-clock duration buckets
        self.budget_corrective_actions = Counter()  # corrective actions taken

    def record_run(self, state: str):
        self.runs[state] += 1

    def record_command(self, outcome: str):
        self.commands[outcome] += 1

    def record_verification(self, verified: bool):
        self.verifications[str(verified)] += 1

    def record_duration(self, name: str, duration: float):
        self.histograms_count[name] += 1
        self.histograms_sum[name] += duration

    # --- Issue #26: Budget metrics ---

    def record_task_executed(self, run_id: str):
        """Record one task execution for a run."""
        self.budget_tasks[run_id] += 1

    def record_openclaw_call(self, run_id: str):
        """Record one OpenClaw call for a run."""
        self.budget_openclaw_calls[run_id] += 1

    def record_wall_clock(self, run_id: str, seconds: float):
        """Record wall-clock duration for a run."""
        self.histograms_count[f"wall_clock_seconds:{run_id}"] += 1
        self.histograms_sum[f"wall_clock_seconds:{run_id}"] += seconds
        # Also maintain a summary counter for quick reporting
        bucket = _bucket_wall_clock(seconds)
        self.budget_wall_clock_seconds[f"{run_id}:{bucket}"] += 1

    def record_corrective_action(self, run_id: str):
        """Record one corrective action created for a run."""
        self.budget_corrective_actions[run_id] += 1

    def budget_report(self, run_id: str) -> dict:
        """Return current budget utilization for a run.

        Returns:
            dict with keys: tasks_used, openclaw_calls, wall_clock_seconds, corrective_actions
        """
        return {
            "run_id": run_id,
            "tasks_used": self.budget_tasks.get(run_id, 0),
            "openclaw_calls": self.budget_openclaw_calls.get(run_id, 0),
            "wall_clock_seconds": round(
                self.histograms_sum.get(f"wall_clock_seconds:{run_id}", 0.0), 2
            ),
            "corrective_actions": self.budget_corrective_actions.get(run_id, 0),
        }

    def to_prometheus(self) -> str:
        lines = []
        # Runs
        for state, count in self.runs.items():
            lines.append(f'opsswarm_runs_total{{state="{state}"}} {count}')
        # Commands
        for outcome, count in self.commands.items():
            lines.append(f'opsswarm_commands_executed{{outcome="{outcome}"}} {count}')
        # Verifications
        for verified, count in self.verifications.items():
            lines.append(f'opsswarm_verifications_total{{verified="{verified}"}} {count}')
        # Durations
        for name in self.histograms_count:
            lines.append(f"{name}_count {self.histograms_count[name]}")
            lines.append(f"{name}_sum {self.histograms_sum[name]}")
        # Issue #26 — Budget utilization (run-scoped)
        for run_id in _active_runs(self.budget_tasks, self.budget_openclaw_calls,
                                   self.budget_wall_clock_seconds, self.budget_corrective_actions):
            report = self.budget_report(run_id)
            for key, val in report.items():
                if key == "run_id":
                    continue
                safe_key = key.replace(":", "_")
                lines.append(f'opsswarm_budget_{{run_id="{run_id}",metric="{safe_key}"}} {val}')
        return "\n".join(lines)


def _bucket_wall_clock(seconds: float) -> str:
    """Bucket wall-clock time into a human-readable label."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{round(seconds / 3600, 1)}h"


def _active_runs(*counters) -> set[str]:
    """Collect all unique run IDs present across multiple counters."""
    runs: set[str] = set()
    for counter in counters:
        for key in counter:
            # Counter keys may be plain run_id or "run_id:subkey"
            run_id = key.split(":")[0]
            runs.add(run_id)
    return runs


metrics = Metrics()
