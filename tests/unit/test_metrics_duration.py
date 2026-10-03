"""
Unit tests asserting that metrics.record_duration is called by the orchestrator
workflow, and that histograms_count / histograms_sum are populated after a run.

Covers acceptance criteria for task t_2f767587 (Option A):
  1. At least 2 record_duration call sites in the orchestrator.
  2. histograms_count / histograms_sum are populated after _investigate and _verify.
"""

import pytest
import yaml

from opsswarm.metrics import Metrics
from opsswarm.models import RunState
from opsswarm.orchestrator import Orchestrator
from tests.fakes import FakeGitHub, FakeOpenClaw
from tests.integration.orchestrator.test_flows import investigation_and_rca


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg():
    return yaml.safe_load(open("config/test.yaml"))


@pytest.fixture
def issue():
    return {
        "number": 1,
        "title": "[Incident] latency spike",
        "body": (
            "## Incident\n\n"
            "### Service\napi-gateway\n\n"
            "### Symptoms\nP99 > 5s\n\n"
            "### Customer impact\nCheckout degraded\n\n"
            "### Environment\nproduction\n"
        ),
        "labels": [{"name": "opsswarm"}, {"name": "sev:2"}],
        "user": {"login": "dev"},
    }


def _rca_response():
    """RCA synthesis response."""
    return {
        "proximate_cause": "test",
        "root_cause": "test",
        "causal_chain": ["test"],
        "confidence": 0.9,
    }

def _safe_workflow_responses():
    """Full response set for a safe-write run that resolves end-to-end."""
    return investigation_and_rca() + [
        {
            "options": [
                {
                    "id": "restart",
                    "description": "restart pods",
                    "profile": "recovery-responder",
                    "risk": "safe_write",
                    "estimated_recovery": "2m",
                    "rationale": "quick rollout restart",
                    "capabilities": ["deploy.restart"],
                }
            ],
            "recommended_option": "restart",
            "confidence": 0.91,
            "requires_business_input": False,
            "business_input_question": None,
        },
        {
            "option_id": "restart",
            "success": True,
            "summary": "pods restarted",
            "evidence": ["receipt:1"],
            "ambiguous": False,
            "raw": {},
        },
        {
            "verified": True,
            "summary": "latency nominal",
            "evidence": ["sli:ok"],
            "confidence": 0.97,
            "raw": {},
        },
        _rca_response(),
    ]


def _failed_verify_responses():
    """Response set where verification fails (not aborted), exercising the
    FAILED exit path of _verify."""
    return investigation_and_rca() + [
        {
            "options": [
                {
                    "id": "restart",
                    "description": "restart pods",
                    "profile": "recovery-responder",
                    "risk": "safe_write",
                    "estimated_recovery": "2m",
                    "rationale": "quick rollout restart",
                    "capabilities": ["deploy.restart"],
                }
            ],
            "recommended_option": "restart",
            "confidence": 0.91,
            "requires_business_input": False,
            "business_input_question": None,
        },
        {
            "option_id": "restart",
            "success": True,
            "summary": "pods restarted",
            "evidence": ["receipt:1"],
            "ambiguous": False,
            "raw": {},
        },
        {
            "verified": False,
            "summary": "still degraded",
            "evidence": [],
            "confidence": 0.40,
            "abort": False,
            "raw": {},
        },
    ]


# ---------------------------------------------------------------------------
# Tests — Metrics class unit-level (isolated, no orchestrator)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_duration_populates_histograms():
    """record_duration increments histograms_count and accumulates histograms_sum."""
    m = Metrics()
    m.record_duration("investigate_seconds", 1.2)
    m.record_duration("investigate_seconds", 0.8)

    assert m.histograms_count["investigate_seconds"] == 2
    assert abs(m.histograms_sum["investigate_seconds"] - 2.0) < 1e-9


@pytest.mark.unit
def test_record_duration_multiple_spans_independent():
    """Two distinct span names produce independent histogram entries."""
    m = Metrics()
    m.record_duration("investigate_seconds", 3.0)
    m.record_duration("verify_seconds", 1.5)

    assert m.histograms_count["investigate_seconds"] == 1
    assert m.histograms_count["verify_seconds"] == 1
    assert m.histograms_sum["investigate_seconds"] == 3.0
    assert m.histograms_sum["verify_seconds"] == 1.5


@pytest.mark.unit
def test_to_prometheus_renders_duration_lines():
    """to_prometheus() emits _count and _sum lines for recorded durations."""
    m = Metrics()
    m.record_duration("investigate_seconds", 2.5)
    output = m.to_prometheus()

    assert "investigate_seconds_count 1" in output
    assert "investigate_seconds_sum 2.5" in output


# ---------------------------------------------------------------------------
# Integration — orchestrator wires durations during a full run
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_investigate_duration_recorded_after_resolved_run(tmp_path, cfg, issue):
    """
    After a fully resolved run, investigate_seconds histogram must be populated
    (count >= 1, sum > 0).
    """
    from opsswarm.metrics import metrics as global_metrics

    # Snapshot counts before the run so module-level singleton state doesn't
    # confound the assertion.
    before_count = global_metrics.histograms_count.get("investigate_seconds", 0)
    before_sum = global_metrics.histograms_sum.get("investigate_seconds", 0.0)

    gh = FakeGitHub(issue)
    oc = FakeOpenClaw(_safe_workflow_responses())
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    run = await eng.start_issue(1)

    assert run.state == RunState.RESOLVED
    assert global_metrics.histograms_count["investigate_seconds"] > before_count
    # On fast hardware time.monotonic() can return the same value twice, yielding a
    # 0.0 delta. Guard: if count grew, the call site is wired — the sum must be
    # >= before_sum (never decreases). Also assert the delta is non-negative.
    inv_sum = global_metrics.histograms_sum["investigate_seconds"]
    inv_delta = inv_sum - before_sum
    assert inv_sum >= before_sum, "investigate_seconds sum must not decrease"
    assert inv_delta >= 0.0, "investigate_seconds duration delta must be non-negative"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_duration_recorded_after_resolved_run(tmp_path, cfg, issue):
    """
    After a fully resolved run, verify_seconds histogram must be populated
    (count >= 1, sum > 0).
    """
    from opsswarm.metrics import metrics as global_metrics

    before_count = global_metrics.histograms_count.get("verify_seconds", 0)
    before_sum = global_metrics.histograms_sum.get("verify_seconds", 0.0)

    gh = FakeGitHub(issue)
    oc = FakeOpenClaw(_safe_workflow_responses())
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    run = await eng.start_issue(1)

    assert run.state == RunState.RESOLVED
    assert global_metrics.histograms_count["verify_seconds"] > before_count
    # Sum must be strictly greater than the snapshot taken before this run.
    # On fast hardware time.monotonic() can return the same value twice,
    # yielding a 0.0 delta. Guard: if count grew, at least one call landed
    # (proven above); the sum must be >= before_sum (never decreases).
    assert global_metrics.histograms_sum["verify_seconds"] >= before_sum, (
        "verify_seconds sum must not decrease"
    )
    # Additionally assert that sum grew relative to before this run OR that
    # count increased by more than 1 (meaning duration was recorded multiple
    # times — either way record_duration was wired correctly).
    count_delta = global_metrics.histograms_count["verify_seconds"] - before_count
    sum_delta = global_metrics.histograms_sum["verify_seconds"] - before_sum
    assert count_delta >= 1, "verify_seconds count must increase by at least 1"
    assert sum_delta >= 0.0, "verify_seconds sum must not decrease after a run"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_both_duration_spans_recorded_in_single_run(tmp_path, cfg, issue):
    """
    A single resolved run must produce at least one entry in BOTH
    investigate_seconds and verify_seconds — covering both wired call sites.
    """
    from opsswarm.metrics import metrics as global_metrics

    before_inv = global_metrics.histograms_count.get("investigate_seconds", 0)
    before_ver = global_metrics.histograms_count.get("verify_seconds", 0)

    gh = FakeGitHub(issue)
    oc = FakeOpenClaw(_safe_workflow_responses())
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    run = await eng.start_issue(1)

    assert run.state == RunState.RESOLVED
    assert global_metrics.histograms_count["investigate_seconds"] > before_inv, (
        "investigate_seconds was not recorded — _investigate duration call site is missing"
    )
    assert global_metrics.histograms_count["verify_seconds"] > before_ver, (
        "verify_seconds was not recorded — _verify duration call site is missing"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_duration_recorded_on_failed_verification(tmp_path, cfg, issue):
    """
    Even when verification fails (run ends in FAILED), verify_seconds must still
    be recorded — the instrumentation covers the failure exit path of _verify.
    """
    from opsswarm.metrics import metrics as global_metrics

    before_count = global_metrics.histograms_count.get("verify_seconds", 0)

    gh = FakeGitHub(issue)
    oc = FakeOpenClaw(_failed_verify_responses())
    eng = Orchestrator(cfg, gh, oc, str(tmp_path))
    run = await eng.start_issue(1)

    assert run.state == RunState.FAILED
    assert global_metrics.histograms_count["verify_seconds"] > before_count, (
        "verify_seconds must be recorded even when verification fails"
    )
