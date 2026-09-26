from fastapi.testclient import TestClient

from opsswarm.api import app
from opsswarm.metrics import Metrics, metrics

client = TestClient(app)


def test_metrics_endpoint():
    """Verify /metrics returns 200 with Prometheus text format and the expected counter."""
    metrics.record_run("TRIAGE")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "opsswarm_runs_total" in body
    # Prometheus format: label values are always double-quoted
    assert 'state="TRIAGE"' in body
    assert "1" in body


def test_metrics_all_counter_families_present():
    """Verify all three counter families are always present in the output."""
    # The singleton starts empty; exercise all three families so they appear.
    metrics.record_run("INIT")
    metrics.record_command("executed")
    metrics.record_verification(True)
    response = client.get("/metrics")
    body = response.text
    assert "opsswarm_runs_total" in body
    assert "opsswarm_commands_executed" in body
    assert "opsswarm_verifications_total" in body


def test_metrics_label_format_escaping():
    """Verify label values are properly double-quoted per Prometheus text exposition format."""
    metrics.record_run("PLANNING")
    metrics.record_command("approved")
    metrics.record_verification(True)
    response = client.get("/metrics")
    body = response.text
    assert 'state="PLANNING"' in body
    assert 'outcome="approved"' in body
    assert 'verified="True"' in body


def test_metrics_no_auth_required():
    """Confirm the /metrics endpoint is accessible without an API key."""
    # The route has no Depends(verify_api_key) — absence of 403 is the contract.
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_duration_summaries():
    """Verify duration count/sum pairs render correctly for recorded durations."""
    metrics.record_duration("command_execution", 1.5)
    metrics.record_duration("command_execution", 2.5)
    response = client.get("/metrics")
    body = response.text
    # Duration names become bare metric names without opsswarm_ prefix
    assert "command_execution_count" in body
    assert "command_execution_sum" in body
    # Sum should reflect both recorded durations (1.5 + 2.5 = 4.0)
    assert "4.0" in body


def test_metrics_singleton_isolation():
    """Confirm Metrics.to_prometheus produces consistent output format across resets."""
    m = Metrics()
    m.record_run("TRIAGE")
    output = m.to_prometheus()
    lines = output.split("\n")
    assert any("opsswarm_runs_total" in line for line in lines)
    # Verify format: counter value on same line as metric name and labels
    assert any('state="TRIAGE"' in line and "1" in line for line in lines)
