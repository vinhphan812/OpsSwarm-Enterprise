from collections import Counter

from .models import RunState


class Metrics:
    # Cardinality-safe label sets — values come from enums/config, never from user input.
    VALID_RUN_STATES: set[str] = {s.value for s in RunState}
    VALID_POLICY_ACTIONS: set[str] = {"AUTO", "APPROVAL", "DECISION", "INPUT", "DENY"}
    VALID_EVIDENCE_FAILURES: set[str] = {"duplicate", "corrupt", "write_error"}
    VALID_BUDGET_TYPES: set[str] = {"tasks", "execution_seconds", "openclaw_calls"}
    VALID_HUMAN_GATE_KINDS: set[str] = {"approval", "decision", "input"}
    VALID_RECONCILIATION_OUTCOMES: set[str] = {"clean_recovery", "ambiguous", "impossible", "no_evidence"}
    VALID_WEBHOOK_DELIVERY_KINDS: set[str] = {"processed", "dedup_skipped", "rejected"}

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

        # OpenClaw call duration histogram (per-profile seconds)
        self.openclaw_duration_count = Counter()  # profile: count
        self.openclaw_duration_sum = Counter()     # profile: seconds

        # OpenClaw timeout / error counters (per-profile)
        self.openclaw_timeouts = Counter()  # profile: count
        self.openclaw_errors = Counter()    # profile: count

        # Policy classification outcomes
        self.policy_actions = Counter()  # action: count (AUTO / APPROVAL / DECISION / INPUT / DENY)

        # Evidence failures
        self.evidence_failures = Counter()  # failure_type: count

        # Reconciliation outcomes
        self.reconciliation_outcomes = Counter()  # outcome: count

        # Ambiguous write counter
        self.ambiguous_writes = Counter()  # count

        # Webhook delivery counter
        self.webhook_deliveries = Counter()  # kind: count

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
            "reconciliation_outcomes": set(),
            "webhook_deliveries": set(),
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

    def record_openclaw_duration(self, profile: str, seconds: float):
        if not profile or not profile.replace("_", "").replace("-", "").isalnum():
            profile = "unknown"
        self.openclaw_duration_count[profile] += 1
        self.openclaw_duration_sum[profile] += seconds
        self._observed_labels.setdefault("openclaw_call_seconds", set()).add(profile)

    def record_openclaw_timeout(self, profile: str):
        if not profile or not profile.replace("_", "").replace("-", "").isalnum():
            profile = "unknown"
        self.openclaw_timeouts[profile] += 1
        self._observed_labels.setdefault("openclaw_timeouts", set()).add(profile)

    def record_openclaw_error(self, profile: str):
        if not profile or not profile.replace("_", "").replace("-", "").isalnum():
            profile = "unknown"
        self.openclaw_errors[profile] += 1
        self._observed_labels.setdefault("openclaw_errors", set()).add(profile)

    # ── NEW: policy actions ───────────────────────────────────────────────────

    def record_policy_action(self, action: str):
        # Guard: only known actions are accepted; log and skip unknown
        if action not in self.VALID_POLICY_ACTIONS:
            return
        self.policy_actions[action] += 1
        self._observed_labels["policy_actions"].add(action)

    # ── NEW: human gate wait duration ─────────────────────────────────────────

    def record_human_gate(self, gate_kind: str, duration: float):
        if gate_kind not in self.VALID_HUMAN_GATE_KINDS:
            gate_kind = "unknown"
        self.histograms_count["human_gate_seconds"] += 1
        self.histograms_sum["human_gate_seconds"] += duration
        self._observed_labels.setdefault("human_gate_seconds", set()).add(gate_kind)

    # ── NEW: ambiguous write counter ───────────────────────────────────────────

    def record_ambiguous_write(self):
        """Increment the ambiguous-write counter each time execution.ambiguous=True."""
        self.ambiguous_writes["total"] += 1

    # ── NEW: reconciliation outcomes ────────────────────────────────────────────

    def record_reconciliation_outcome(self, outcome: str):
        """Record a reconciliation outcome with cardinality guard."""
        if outcome not in self.VALID_RECONCILIATION_OUTCOMES:
            outcome = "unknown"
        self.reconciliation_outcomes[outcome] += 1
        self._observed_labels.setdefault("reconciliation_outcomes", set()).add(outcome)

    # ── NEW: webhook delivery counter ─────────────────────────────────────────────

    def record_webhook_delivery(self, kind: str):
        """Record a webhook delivery by outcome kind with cardinality guard."""
        if kind not in self.VALID_WEBHOOK_DELIVERY_KINDS:
            kind = "unknown"
        self.webhook_deliveries[kind] += 1
        self._observed_labels.setdefault("webhook_deliveries", set()).add(kind)

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

        # ── NEW: human gate wait duration (histogram) ───────────────────────────
        # human_gate_seconds is emitted via the generic histograms block above.
        # Cardinality is guarded by VALID_HUMAN_GATE_KINDS (3 values).

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

        # ── OpenClaw metrics (G2 / Issue #30) ────────────────────────────────
        for profile, count in sorted(self.openclaw_calls.items()):
            lines.append(f'opsswarm_openclaw_calls_total{{profile="{profile}"}} {count}')

        for profile in sorted(self.openclaw_duration_count.keys()):
            lines.append(
                f'opsswarm_openclaw_call_seconds{{profile="{profile}"}}_count '
                f'{self.openclaw_duration_count[profile]}'
            )
            lines.append(
                f'opsswarm_openclaw_call_seconds{{profile="{profile}"}}_sum '
                f'{self.openclaw_duration_sum[profile]:.6f}'
            )

        for profile, count in sorted(self.openclaw_timeouts.items()):
            lines.append(f'opsswarm_openclaw_timeouts_total{{profile="{profile}"}} {count}')

        for profile, count in sorted(self.openclaw_errors.items()):
            lines.append(f'opsswarm_openclaw_errors_total{{profile="{profile}"}} {count}')

        # ── NEW: policy actions ────────────────────────────────────────────────
        for action, count in sorted(self.policy_actions.items()):
            lines.append(f'opsswarm_policy_actions_total{{action="{action}"}} {count}')

        # ── NEW: ambiguous writes ─────────────────────────────────────────────────
        if self.ambiguous_writes:
            lines.append(f'opsswarm_execution_ambiguous_total {self.ambiguous_writes["total"]}')

        # ── NEW: reconciliation outcomes ─────────────────────────────────────────
        for outcome, count in sorted(self.reconciliation_outcomes.items()):
            lines.append(f'opsswarm_reconciliation_outcome{{outcome="{outcome}"}} {count}')

        # ── NEW: webhook deliveries ──────────────────────────────────────────────
        for kind, count in sorted(self.webhook_deliveries.items()):
            lines.append(f'opsswarm_webhook_deliveries_total{{kind="{kind}"}} {count}')

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
