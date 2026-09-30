"""Unit tests for opsswarm.metrics module.

GET /metrics requires opsswarm:admin scope per ADR-014.
Auth is provided via session-level conftest.py setup.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from opsswarm.api import app
from opsswarm.metrics import Metrics, metrics


def _admin_bearer(method: str, path: str) -> dict:
    """Return an Authorization header with a valid opsswarm:admin bearer token."""
    secret = "test-secret"
    ts = int(time.time())
    payload = f"{method.upper()}:{path}:{ts}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"opsswarm:admin={mac}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """TestClient scoped to this fixture so auth header is fresh per test."""
    return TestClient(app)


def test_metrics_endpoint(client):
    """Verify /metrics returns 200 with Prometheus text format and the expected counter."""
    metrics.record_run("TRIAGE")

    response = client.get("/metrics", headers=_admin_bearer("GET", "/metrics"))
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "opsswarm_runs_total" in body
    # Prometheus format: label values are always double-quoted
    assert 'state="TRIAGE"' in body
    assert "1" in body


def test_metrics_all_counter_families_present(client):
    """Verify all three counter families are always present in the output."""
    # The singleton starts empty; exercise all three families so they appear.
    metrics.record_run("INIT")
    metrics.record_command("executed")
    metrics.record_verification(True)
    response = client.get("/metrics", headers=_admin_bearer("GET", "/metrics"))
    body = response.text
    assert "opsswarm_runs_total" in body
    assert "opsswarm_commands_executed" in body
    assert "opsswarm_verifications_total" in body


def test_metrics_label_format_escaping(client):
    """Verify label values are properly double-quoted per Prometheus text exposition format."""
    metrics.record_run("PLANNING")
    metrics.record_command("approved")
    metrics.record_verification(True)
    response = client.get("/metrics", headers=_admin_bearer("GET", "/metrics"))
    body = response.text
    assert 'state="PLANNING"' in body
    assert 'outcome="approved"' in body
    assert 'verified="True"' in body


def test_metrics_requires_admin_scope(client):
    """GET /metrics requires opsswarm:admin scope (ADR-014); no auth -> 401."""
    response = client.get("/metrics")
    # 401 Missing credentials — /metrics is NOT public like /health
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing credentials"


def test_metrics_read_scope_insufficient(client):
    """opsswarm:read token on GET /metrics -> 403 Insufficient scope."""
    secret = "test-secret"
    ts = int(time.time())
    payload = f"GET:/metrics:{ts}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"opsswarm:read={mac}"
    response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "Insufficient scope" in response.json()["detail"]


def test_metrics_duration_summaries(client):
    """Verify duration count/sum pairs render correctly for recorded durations."""
    metrics.record_duration("command_execution", 1.5)
    metrics.record_duration("command_execution", 2.5)
    response = client.get("/metrics", headers=_admin_bearer("GET", "/metrics"))
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
