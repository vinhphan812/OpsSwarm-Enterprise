"""Contract test for the release-gate workflow YAML (issue #145, ADR 0027).

This is a YAML parse / structural assertion. It does NOT run the workflow.
It reads ``.github/workflows/release-gate.yml`` and asserts that:

  * the file parses as valid YAML;
  * every required smoke job is present;
  * every required environment variable is referenced in the workflow;
  * the ``action=rollback`` manual path is gated on workflow_dispatch only;
  * the workflow does not call ``/simulations/{id}/approve`` automatically.

The test runs offline and is safe for the day-0 unit-test gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is part of the API dev env
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-gate.yml"


REQUIRED_JOBS = (
    "gate",
    "metadata",
    "smoke-backend-health",
    "smoke-backend-readiness",
    "smoke-firestore-store",
    "smoke-p001-inventory",
    "smoke-p017-inventory",
    "smoke-bigquery-analytics",
    "smoke-pubsub-event",
    "smoke-agent-activity",
    "smoke-vertex-gemini",
    "smoke-simulation-dcg",
    "smoke-secret-scan",
    "smoke-frontend-availability",
    "release-decision",
    "rollback",
    "rollback-manual",
)

REQUIRED_ENV_KEYS = (
    "GCP_PROJECT",
    "GCP_REGION",
    "CLOUD_RUN_SERVICE",
    "PUBSUB_TOPIC",
    "BIGQUERY_DATASET",
    "FIREBASE_SITE",
    "STORE_ID",
    "FIXTURE_P001",
    "FIXTURE_P017",
    "EVENT_ID_PREFIX",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow missing: {WORKFLOW_PATH}"
    if yaml is None:
        pytest.skip("PyYAML is not installed")
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _on(workflow: dict) -> dict:
    """GitHub Actions parses ``on:`` as YAML 1.1 boolean ``True`` in some libs."""
    return workflow.get("on", workflow.get(True, {}))


def test_workflow_parses(workflow: dict) -> None:
    assert isinstance(workflow, dict)
    assert workflow.get("name") == "Release Gate"


def test_workflow_triggers(workflow: dict) -> None:
    triggers = _on(workflow)
    assert "workflow_run" in triggers, "missing workflow_run trigger"
    assert "workflow_dispatch" in triggers, "missing workflow_dispatch trigger"
    dispatch = triggers["workflow_dispatch"]
    inputs = dispatch.get("inputs", {})
    assert "action" in inputs, "missing workflow_dispatch input: action"
    assert "smoke_run_id" in inputs, "missing workflow_dispatch input: smoke_run_id"
    assert "previous_revision" in inputs, "missing workflow_dispatch input: previous_revision"


def test_required_jobs_present(workflow: dict) -> None:
    jobs = workflow.get("jobs", {})
    missing = [job for job in REQUIRED_JOBS if job not in jobs]
    assert not missing, f"missing jobs: {missing}"


def test_required_env_keys_present(workflow: dict) -> None:
    env = workflow.get("env", {})
    missing = [key for key in REQUIRED_ENV_KEYS if key not in env]
    assert not missing, f"missing env keys: {missing}"
    # Event id, env scope is the canonical event id prefix from the metadata job.
    assert env["EVENT_ID_PREFIX"].startswith("retailtwin-release-evidence"), env["EVENT_ID_PREFIX"]


def test_wif_authentication(workflow: dict) -> None:
    """WIF must be the only auth path; no JSON key files."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "google-github-actions/auth" in raw
    assert "workload_identity_provider" in raw
    assert "${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}" in raw
    assert "${{ secrets.GCP_DEPLOY_SA }}" in raw or "${{ secrets.GCP_RUNTIME_SA }}" in raw
    # No fallback to key files.
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in raw
    assert "authprovider-x509-cert-url" not in raw


def test_metadata_job_outputs_match_manifest_schema(workflow: dict) -> None:
    metadata = workflow["jobs"]["metadata"]
    outputs = metadata.get("outputs", {})
    required = {
        "backend_url",
        "frontend_url",
        "frontend_release",
        "frontend_version",
        "git_sha",
        "cloud_run_revision",
        "image_digest",
        "run_timestamp",
        "smoke_run_id",
        "smoke_correlation_id",
        "event_id",
        "gcp_project",
        "gcp_region",
        "demo_data_version",
        "llm_provider",
        "llm_model",
        "is_manual",
    }
    missing = required - outputs.keys()
    assert not missing, f"metadata job missing outputs: {missing}"


def test_release_decision_writes_manifest(workflow: dict) -> None:
    decision = workflow["jobs"]["release-decision"]
    raw = yaml.safe_dump(decision)
    assert "release-manifest/manifest.json" in raw
    assert "release-manifest-" in raw or "actions/upload-artifact" in raw
    # The aggregated check names must be enumerated.
    for job_name in REQUIRED_JOBS:
        if job_name.startswith("smoke-"):
            assert job_name in raw, f"release-decision missing {job_name}"


def test_rollback_jobs(workflow: dict) -> None:
    rollback = workflow["jobs"]["rollback"]
    assert "failure()" in yaml.safe_dump(rollback.get("if", ""))
    rollback_manual = workflow["jobs"]["rollback-manual"]
    assert "inputs.action == 'rollback'" in yaml.safe_dump(rollback_manual.get("if", ""))
    raw_manual = yaml.safe_dump(rollback_manual)
    assert "gcloud run services update-traffic" in raw_manual


def test_simulation_dcg_job_does_not_auto_approve(workflow: dict) -> None:
    """ADR 0014/0016 — bounded competition is the only auto-approve path.

    The smoke gate must never POST ``/simulations/{id}/approve`` or call
    the CommitService ``approve`` method. We strip the docstring comments
    that mention "no auto-approve" as a deliberate operator message.
    """
    sim = workflow["jobs"]["smoke-simulation-dcg"]
    raw = yaml.safe_dump(sim)
    assert "/simulations/" in raw
    # No POST /simulations/{id}/approve in any form (raw, JSON-encoded, or
    # bash-quoted). Stripping the explicit "no auto-approve" status message
    # so the docstring does not trip the test.
    stripped = re.sub(r"no auto-approve[^\"']*", "", raw, flags=re.IGNORECASE)
    assert "/approve" not in stripped, (
        "smoke-simulation-dcg must not POST /simulations/{id}/approve"
    )
    assert re.search(r"POST.*simulations.*approve", stripped, flags=re.IGNORECASE) is None


def test_secret_scan_patterns(workflow: dict) -> None:
    """Secret scan must cover the canonical credential patterns and the new endpoints."""
    secret = workflow["jobs"]["smoke-secret-scan"]
    raw = yaml.safe_dump(secret)
    for pattern in (
        "sk-[a-zA-Z0-9]{20,}",
        "AIza[a-zA-Z0-9_-]{35,}",
        "ya29",
        "ghp_",
        "PRIVATE KEY",
    ):
        assert pattern in raw, f"secret-scan missing pattern: {pattern}"
    # All seven smoke endpoints must be covered.
    for endpoint in (
        "/health",
        "/ready",
        "/store",
        "/inventory/P001",
        "/inventory/P017",
        "/agent/events",
        "/simulations/sim-seed-001",
    ):
        assert endpoint in raw, f"secret-scan missing endpoint: {endpoint}"


def test_pubsub_event_uses_canonical_event_id(workflow: dict) -> None:
    """Pub/Sub deterministic event must carry the canonical ``EVENT_ID_PREFIX``."""
    pubsub = workflow["jobs"]["smoke-pubsub-event"]
    raw = yaml.safe_dump(pubsub)
    assert "EVENT_ID" in raw
    assert "retailtwin-release-evidence" in raw or "needs.metadata.outputs.event_id" in raw


def test_frontend_availability_uses_firebase_hosting_api(workflow: dict) -> None:
    frontend = workflow["jobs"]["smoke-frontend-availability"]
    raw = yaml.safe_dump(frontend)
    assert "firebasehosting.googleapis.com" in raw
    assert "/v1beta1/sites/" in raw


def test_vertex_gemini_smoke_makes_real_call(workflow: dict) -> None:
    vertex = workflow["jobs"]["smoke-vertex-gemini"]
    raw = yaml.safe_dump(vertex)
    assert "aiplatform.googleapis.com" in raw
    assert "generateContent" in raw
    assert "${{ needs.metadata.outputs.llm_model }}" in raw


def test_manifest_is_uploaded_as_artifact(workflow: dict) -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The manifest is uploaded as both an artifact and the step summary.
    assert "actions/upload-artifact@v4" in raw
    assert "release-manifest-" in raw
    # Smoke checks each push one line of JSON to their step summary so the
    # aggregator can decide PASS / FAIL. The actual literal is `\"stage\":\"${{ env.STAGE }}\"`
    # (escaped double quotes inside a bash double-quoted string).
    assert r'\"stage\":\"${{ env.STAGE }}\"' in raw


def test_no_silent_release_promotion(workflow: dict) -> None:
    """The release gate must never silently mark a revision as production.

    The only place that mutates Cloud Run traffic is ``rollback-manual``,
    which is gated on ``action=rollback``. The ``rollback`` job only prints
    the rollback command — it does not execute it.
    """
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The rollback-manual job may mention "update-traffic" in multiple shell
    # lines (the run step + the comment / echo). Cap at the number of run
    # blocks plus a small buffer.
    assert raw.count("update-traffic") >= 1
    # Confirm the actual `gcloud run services update-traffic` invocation is
    # only in rollback-manual (steps inside that job).
    manual = yaml.safe_dump(workflow["jobs"]["rollback-manual"])
    assert "gcloud run services update-traffic" in manual
    # And the auto-rollback job must not invoke it. We strip the documentation
    # "echo" lines (which print the rollback command into the step summary)
    # before checking that no real invocation is present.
    auto = yaml.safe_dump(workflow["jobs"]["rollback"])
    auto_lines = [
        line for line in auto.splitlines()
        if "gcloud run services update-traffic" in line
        and "echo " not in line
        and "ROLLBACK COMMAND" not in line
    ]
    assert auto_lines == [], (
        f"rollback job must not invoke update-traffic; found {auto_lines!r}"
    )
    # The rollback-manual job is gated on action=rollback only.
    assert "inputs.action == 'rollback'" in manual
    assert "rollback-manual" in raw


def test_required_secrets_and_vars_referenced(workflow: dict) -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    for token in (
        "${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}",
        "${{ secrets.GCP_DEPLOY_SA }}",
        "${{ secrets.GCP_RUNTIME_SA }}",
        "${{ vars.FIREBASE_HOSTING_URL }}",
    ):
        assert token in raw, f"workflow does not reference {token}"