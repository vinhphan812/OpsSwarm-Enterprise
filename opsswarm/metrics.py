from collections import Counter


class Metrics:
    def __init__(self):
        self.runs = Counter()  # state: count
        self.commands = Counter()  # outcome: count
        self.verifications = Counter()  # verified: count
        # Minimal histogram implementation (count and sum only)
        self.histograms_count = Counter()
        self.histograms_sum = Counter()

    def record_run(self, state: str):
        self.runs[state] += 1

    def record_command(self, outcome: str):
        self.commands[outcome] += 1

    def record_verification(self, verified: bool):
        self.verifications[str(verified)] += 1

    def record_duration(self, name: str, duration: float):
        self.histograms_count[name] += 1
        self.histograms_sum[name] += duration

    def to_prometheus(self) -> str:
        lines = []
        # Runs
        for state, count in self.runs.items():
            lines.append(f"opsswarm_runs_total{{state=\"{state}\"}} {count}")
        # Commands
        for outcome, count in self.commands.items():
            lines.append(f"opsswarm_commands_executed{{outcome=\"{outcome}\"}} {count}")
        # Verifications
        for verified, count in self.verifications.items():
            lines.append(f"opsswarm_verifications_total{{verified=\"{verified}\"}} {count}")
        # Durations
        for name in self.histograms_count:
            lines.append(f"{name}_count {self.histograms_count[name]}")
            lines.append(f"{name}_sum {self.histograms_sum[name]}")
        return "\n".join(lines)


metrics = Metrics()
