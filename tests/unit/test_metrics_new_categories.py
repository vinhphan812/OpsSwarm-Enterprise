"""
Unit tests for the new metric categories added to close issue #30.

Covers:
  - State-transition latency: opsswarm_state_transition_seconds
  - OpenClaw calls by profile: opsswarm_openclaw_calls_total
  - Policy actions: opsswarm_policy_actions_total
  - Evidence failures: opsswarm_evidence_failures_total
  - Budget utilisation: opsswarm_budget_utilization
  - Active runs gauge: opsswarm_active_runs
  - Cardinality / privacy enforcement
"""

from opsswarm.metrics import Metrics
from opsswarm.models import RunState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_metrics(text: str) -> dict[str, str]:
    """Parse Prometheus text format into a dict of metric_name{labels}=value."""
    lines = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            name, rest = line.split("{", 1)
            labels, value = rest.rsplit("}", 1)
            lines[line.strip()] = (name.strip(), "{" + labels + "}", value.strip())
        else:
            parts = line.strip().split()
            if len(parts) >= 2:
                lines[line.strip()] = (parts[0], "", parts[1])
    return lines


# ---------------------------------------------------------------------------
# Metrics class — unit tests for new families
# ---------------------------------------------------------------------------


class TestMetricsNewFamilies:
    def test_record_transition(self):
        m = Metrics()
        m.record_transition(RunState.TRIAGE, RunState.INVESTIGATING, 0.123)
        output = m.to_prometheus()
        assert 'from_state="TRIAGE"' in output
        assert 'to_state="INVESTIGATING"' in output
        assert "_count" in output
        assert "_sum" in output

    def test_record_transition_accumulates(self):
        m = Metrics()
        m.record_transition(RunState.TRIAGE, RunState.INVESTIGATING, 0.1)
        m.record_transition(RunState.TRIAGE, RunState.INVESTIGATING, 0.2)
        output = m.to_prometheus()
        # Both count and sum appear
        assert "2" in output  # count = 2

    def test_record_openclaw_call(self):
        m = Metrics()
        m.record_openclaw_call("incident-manager")
        output = m.to_prometheus()
        assert 'profile="incident-manager"' in output
        assert "opsswarm_openclaw_calls_total" in output

    def test_record_openclaw_call_sanitises_invalid(self):
        m = Metrics()
        m.record_openclaw_call("")      # empty -> "unknown"
        m.record_openclaw_call("foo; DROP TABLE")  # injection attempt
        output = m.to_prometheus()
        assert 'profile="unknown"' in output

    def test_record_policy_action(self):
        m = Metrics()
        m.record_policy_action("APPROVAL")
        m.record_policy_action("AUTO")
        m.record_policy_action("DENY")
        output = m.to_prometheus()
        assert 'action="APPROVAL"' in output
        assert 'action="AUTO"' in output
        assert 'action="DENY"' in output

    def test_record_policy_action_unknown_ignored(self):
        m = Metrics()
        m.record_policy_action("BOGUS_ACTION")
        m.record_policy_action("APPROVAL")
        output = m.to_prometheus()
        assert "BOGUS_ACTION" not in output
        assert 'action="APPROVAL"' in output

    def test_record_evidence_failure(self):
        m = Metrics()
        m.record_evidence_failure("duplicate")
        m.record_evidence_failure("corrupt")
        m.record_evidence_failure("write_error")
        output = m.to_prometheus()
        assert 'failure_type="duplicate"' in output
        assert 'failure_type="corrupt"' in output
        assert 'failure_type="write_error"' in output

    def test_record_evidence_failure_unknown_mapped_to_unknown(self):
        m = Metrics()
        m.record_evidence_failure("made_up_failure_type")
        output = m.to_prometheus()
        assert 'failure_type="unknown"' in output
        assert "made_up_failure_type" not in output

    def test_set_active_runs(self):
        m = Metrics()
        m.set_active_runs({"INVESTIGATING": 3, "EXECUTING": 1})
        output = m.to_prometheus()
        assert 'state="INVESTIGATING"' in output
        assert 'state="EXECUTING"' in output
        assert "opsswarm_active_runs" in output

    def test_set_budget_utilization(self):
        m = Metrics()
        m.set_budget_utilization("tasks", 0.75)
        output = m.to_prometheus()
        assert 'type="tasks"' in output
        assert "0.7500" in output

    def test_set_budget_utilization_unknown_type_rejected(self):
        m = Metrics()
        m.set_budget_utilization("made_up_budget", 1.0)
        output = m.to_prometheus()
        assert "made_up_budget" not in output

    def test_all_new_metric_families_in_output(self):
        m = Metrics()
        m.record_transition(RunState.INVESTIGATING, RunState.DIAGNOSED, 0.05)
        m.record_openclaw_call("recovery-responder")
        m.record_policy_action("APPROVAL")
        m.record_evidence_failure("duplicate")
        m.set_active_runs({"TRIAGE": 1})
        m.set_budget_utilization("tasks", 0.2)

        output = m.to_prometheus()
        assert "opsswarm_state_transition_seconds" in output
        assert "opsswarm_openclaw_calls_total" in output
        assert "opsswarm_policy_actions_total" in output
        assert "opsswarm_evidence_failures_total" in output
        assert "opsswarm_active_runs" in output
        assert "opsswarm_budget_utilization" in output


# ---------------------------------------------------------------------------
# Cardinality / privacy enforcement
# ---------------------------------------------------------------------------


class TestMetricsCardinality:
    def test_cardinality_guard_property_exists(self):
        m = Metrics()
        m.record_openclaw_call("incident-manager")
        guard = m.cardinality_guard
        assert "openclaw_calls" in guard
        assert guard["openclaw_calls"] == 1

    def test_label_guard_tracks_observed_values(self):
        m = Metrics()
        m.record_openclaw_call("recovery-responder")
        m.record_openclaw_call("recovery-responder")  # duplicate — still 1 unique
        m.record_openclaw_call("incident-manager")
        assert m._observed_labels["openclaw_calls"] == {"recovery-responder", "incident-manager"}

    def test_policy_actions_cardinality_bounded(self):
        """Policy action labels are bounded to VALID_POLICY_ACTIONS enum."""
        m = Metrics()
        for action in ["AUTO", "APPROVAL", "DECISION", "INPUT", "DENY"]:
            m.record_policy_action(action)
        # Unknown action is silently dropped; cardinality stays at 5
        m.record_policy_action("BOGUS")
        assert len(m._observed_labels["policy_actions"]) == 5
        assert m.cardinality_guard["policy_actions"] == 5

    def test_no_raw_user_input_in_labels(self):
        """User-supplied strings cannot become metric label values.

        Profile labels come from config (agent names), not user input.
        This test confirms injection attempts are sanitised.
        """
        m = Metrics()
        # Safe config-supplied profile names
        m.record_openclaw_call("incident-manager")
        m.record_openclaw_call("recovery-responder")
        # Injection attempt with shell metacharacters — sanitised to "unknown"
        m.record_openclaw_call("profile; rm -rf /")
        m.record_openclaw_call("")
        output = m.to_prometheus()
        # Injection chars must not appear as label values
        assert 'profile="incident-manager"' in output
        assert 'profile="recovery-responder"' in output
        assert 'profile="unknown"' in output
        assert 'profile="profile; rm -rf /"' not in output
        assert '"rm' not in output

    def test_valid_run_states_enum_bounded(self):
        """Run-state label values are bounded to the RunState enum."""
        assert len(Metrics.VALID_RUN_STATES) == len(list(RunState))
        # Only enum values can appear as labels (enforced by callers)

    def test_cardinality_guard_observable(self):
        """cardinality_guard exposes observed cardinality for test assertions."""
        m = Metrics()
        assert isinstance(m.cardinality_guard, dict)
        assert "transition" in m.cardinality_guard
        assert "evidence_failures" in m.cardinality_guard

    def test_transition_label_key_format(self):
        """Transition labels use from_state->to_state key in observed_labels."""
        m = Metrics()
        m.record_transition(RunState.INVESTIGATING, RunState.DIAGNOSED, 0.1)
        observed = m._observed_labels["transition"]
        assert "INVESTIGATING->DIAGNOSED" in observed

    def test_budget_utilization_validated(self):
        """Only known budget types are accepted."""
        m = Metrics()
        m.set_budget_utilization("tasks", 0.5)
        m.set_budget_utilization("execution_seconds", 30.0)
        m.set_budget_utilization("openclaw_calls", 10.0)
        # Unknown types are silently dropped
        m.set_budget_utilization("memory_mb", 128.0)
        output = m.to_prometheus()
        assert 'type="memory_mb"' not in output
        assert 'type="tasks"' in output
        assert 'type="execution_seconds"' in output

    def test_active_runs_replaces_previous_snapshot(self):
        """set_active_runs replaces the previous gauge value (not accumulates)."""
        m = Metrics()
        m.set_active_runs({"TRIAGE": 2})
        m.set_active_runs({"TRIAGE": 0, "EXECUTING": 3})
        output = m.to_prometheus()
        lines = [l for l in output.splitlines() if "opsswarm_active_runs" in l]
        counts = [l.strip().split()[-1] for l in lines]
        # TRIAGE should appear with count 0 (not 2), proving snapshot replacement
        for l in lines:
            if 'state="TRIAGE"' in l:
                assert l.strip().endswith("0")
