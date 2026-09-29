from collections import Counter

from .models import RunState


class Metrics:
    # Cardinality-safe label sets — values come from enums/config, never from user input.
    VALID_RUN_STATES: set[str] = {s.value for s in RunState}
    VALID_POLICY_ACTIONS: set[str] = {"AUTO", "APPROVAL", "DECISION", "INPUT", "DENY"}
    VALID_EVIDENCE_FAILURES: set[str] = {"duplicate", "corrupt", "write_error"}
    VALID_BUDGET_TYPES: set[str] = {"tasks", "execution_seconds", "openclaw_calls"}

    def __init__(self):
        # ── Core counters (already shipped in PR #33) ──────────────────────────
        self.runs = Counter()  # state: count
        self.commands = Counter()  # outcome: count
        self.verifications = Counter()  # verified: count
        # Minimal histogram (count + sum only)
        self.histograms_count = Counter()
        self.histograms_sum = Counter()

        # ── NEW: required by issue #30 ────────────────────────────────────────
        # Active runs by state — gauge (populated on read from orchestrator state)
        self._active_runs_gauge: dict[str, int] = {}

        # State-transition latency — histogram (count + sum per transition)
        self.transition_count = Counter()   # (from_state, to_state): count
        self.transition_sum = Counter()       # (from_state, to_state): seconds

        # OpenClaw calls by profile
        self.openclaw_calls = Counter()  # profile: count

        # Policy classification outcomes
        self.policy_actions = Counter()  # action: count (AUTO / APPROVAL / DECISION / INPUT / DENY)

        # Evidence failures
        self.evidence_failures = Counter()  # failure_type: count

        # Budget utilisation — gauge (populated on read)
        self._budget_gauge: dict[str, float] = {}

        # Cardinality guard — tracks observed label values per family
        self._observed_labels: dict[str, set] = {
            "runs": set(),
            "commands": set(),
            "openclaw_calls": set(),
            "policy_actions": set(),
            "evidence_failures": set(),
            "transition": set(),
        }

    # ── Core recording methods (already shipped) ───────────────────────────────

    def record_run(self, state: str):
        self.runs[state] += 1

    def record_command(self, outcome: str):
        self.commands[outcome] += 1

    def record_verification(self, verified: bool):
        self.verifications[str(verified)] += 1

    def record_duration(self, name: str, duration: float):
        self.histograms_count[name] += 1
        self.histograms_sum[name] += duration

    # ── NEW: state-transition latency ─────────────────────────────────────────

    def record_transition(self, from_state: RunState, to_state: RunState, duration: float):
        key = (from_state.value, to_state.value)
        self.transition_count[key] += 1
        self.transition_sum[key] += duration
        self._observed_labels["transition"].add(f"{from_state.value}->{to_state.value}")

    # ── NEW: OpenClaw calls by profile ───────────────────────────────────────

    def record_openclaw_call(self, profile: str):
        # Guard: profile must be non-empty and contain only safe chars
        if not profile or not profile.replace("_", "").replace("-", "").isalnum():
            profile = "unknown"
        self.openclaw_calls[profile] += 1
        self._observed_labels["openclaw_calls"].add(profile)

    # ── NEW: policy actions ───────────────────────────────────────────────────

    def record_policy_action(self, action: str):
        # Guard: only known actions are accepted; log and skip unknown
        if action not in self.VALID_POLICY_ACTIONS:
            return
        self.policy_actions[action] += 1
        self._observed_labels["policy_actions"].add(action)

    # ── NEW: evidence failures ─────────────────────────────────────────────────

    def record_evidence_failure(self, failure_type: str):
        if failure_type not in self.VALID_EVIDENCE_FAILURES:
            failure_type = "unknown"
        self.evidence_failures[failure_type] += 1
        self._observed_labels["evidence_failures"].add(failure_type)

    # ── NEW: budget utilisation ────────────────────────────────────────────────

    def set_budget_utilization(self, budget_type: str, utilization: float):
        if budget_type not in self.VALID_BUDGET_TYPES:
            return
        self._budget_gauge[budget_type] = utilization

    # ── NEW: active runs gauge ────────────────────────────────────────────────

    def set_active_runs(self, state_counts: dict[str, int]):
        """Set the active run counts by state (replaces previous snapshot)."""
        self._active_runs_gauge = dict(state_counts)

    # ── Cardinality enforcement ───────────────────────────────────────────────

    @property
    def cardinality_guard(self) -> dict[str, int]:
        """Return observed cardinality per metric family for testing."""
        return {family: len(vals) for family, vals in self._observed_labels.items()}

    def _check_label(self, family: str, label: str) -> str:
        """Return the label; unknown family is allowed (pass-through)."""
        return label

    # ── Prometheus exporter ────────────────────────────────────────────────────

    def to_prometheus(self) -> str:
        lines = []

        # ── Core metrics (already shipped) ────────────────────────────────────
        for state, count in sorted(self.runs.items()):
            lines.append(f'opsswarm_runs_total{{state="{state}"}} {count}')
        for outcome, count in sorted(self.commands.items()):
            lines.append(f'opsswarm_commands_executed{{outcome="{outcome}"}} {count}')
        for verified, count in sorted(self.verifications.items()):
            lines.append(f'opsswarm_verifications_total{{verified="{verified}"}} {count}')
        for name in sorted(self.histograms_count):
            lines.append(f"{name}_count {self.histograms_count[name]}")
            lines.append(f"{name}_sum {self.histograms_sum[name]}")

        # ── NEW: active runs gauge ─────────────────────────────────────────────
        for state, count in sorted(self._active_runs_gauge.items()):
            lines.append(f'opsswarm_active_runs{{state="{state}"}} {count}')

        # ── NEW: state-transition latency ─────────────────────────────────────
        for (from_state, to_state), count in sorted(self.transition_count.items()):
            key = (from_state, to_state)
            lines.append(
                f'opsswarm_state_transition_seconds{{from_state="{from_state}",'
                f'to_state="{to_state}"}}_count {count}'
            )
            lines.append(
                f'opsswarm_state_transition_seconds{{from_state="{from_state}",'
                f'to_state="{to_state}"}}_sum {self.transition_sum[key]}'
            )

        # ── NEW: OpenClaw calls by profile ────────────────────────────────────
        for profile, count in sorted(self.openclaw_calls.items()):
            lines.append(f'opsswarm_openclaw_calls_total{{profile="{profile}"}} {count}')

        # ── NEW: policy actions ────────────────────────────────────────────────
        for action, count in sorted(self.policy_actions.items()):
            lines.append(f'opsswarm_policy_actions_total{{action="{action}"}} {count}')

        # ── NEW: evidence failures ─────────────────────────────────────────────
        for failure_type, count in sorted(self.evidence_failures.items()):
            lines.append(
                f'opsswarm_evidence_failures_total{{failure_type="{failure_type}"}} {count}'
            )

        # ── NEW: budget utilisation ─────────────────────────────────────────────
        for budget_type, utilization in sorted(self._budget_gauge.items()):
            lines.append(
                f'opsswarm_budget_utilization{{type="{budget_type}"}} {utilization:.4f}'
            )

        return "\n".join(lines)


metrics = Metrics()
