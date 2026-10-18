"""Pytest wrappers for the G06 Submission Gate flagship harness (#53).

The flagship harness is script-driven (see ``scripts/run-submission-gate.sh``
and ``tests/e2e/gates/run_flagship_scenario.py``), consistent with how the
other release gates ship. These tests pin the contract the reviewers need
on every PR touching the harness without requiring the full 20-run matrix
to be re-executed.

Covered scenarios:
  - ``--mode happy`` is the default and emits the 9 in-memory checks.
  - ``--mode negative`` exercises the no-stale-commit REFRESH_REQUIRED path
    on the same Decision Context Guard used by G04 (#51). The negative
    case is preserved as a matrix row per reviewer blocker #3.
  - Production-mode fields (``environment``, ``provider_mode``,
    ``live_twin_backend``, ``cloud_run_revision``, ``verifier_verdict``,
    the per-action ``kind`` tag, the per-gate ``dcg_audit`` slice, and
    the correlation_id round-trip) are present in the evidence JSON in
    both modes.
"""

from __future__ import annotations

import json

from gates import run_flagship_scenario


def _checks(evidence: dict) -> dict[str, bool]:
    return {item["check"]: item["passed"] for item in evidence["checks"]}


def test_g06_happy_mode_passes_end_to_end(run_id: str) -> None:
    evidence = run_flagship_scenario.run_flagship(f"{run_id}-g06-happy", mode="happy")

    assert evidence["result"] == "PASS"
    assert evidence["mode"] == "happy"
    checks = _checks(evidence)
    # Canonical 9-check shape (DoD-3 of #53).
    for name in (
        "all_13_events_published",
        "weekend_demand_surge_detected",
        "observer_accepted_every_sale",
        "every_investigation_completed_simulation",
        "guard_allowed_on_fresh_reads",
        "simulation_id_present",
        "decision_id_present",
        "p017_shelf_increased",
        "audit_trail_complete",
    ):
        assert checks.get(name) is True, f"{name} did not pass"
    runtime = evidence["runtime"]
    assert runtime["environment"] == "in-memory preflight"
    assert runtime["provider_mode"] == "fake"
    assert runtime["live_twin_backend"] == "memory"
    assert runtime["cloud_run_revision"] is None
    assert runtime["mode"] == "happy"
    assert "verifier_verdict" in runtime
    assert runtime["verifier_verdict"] in ("VERIFIED", "INCONCLUSIVE", "NOT_RUN")
    assert "actions" in runtime
    assert all(item["kind"] == "guarded_live_mutation" for item in runtime["actions"])
    assert "dcg_audit" in runtime
    assert "correlation_id_round_trip" in runtime
    # The evidence JSON round-trips through json.dumps to ensure it serialises.
    json.dumps(evidence, default=str)


def test_g06_negative_mode_returns_refresh_required(run_id: str) -> None:
    """The no-stale-commit negative case at the G06 harness level.

    Mirrors ``tests/e2e/test_stale_context.py::TestStaleContextContract::test_stale_context_is_rejected_by_dcg``
    at the G06 layer, with the same Decision built against Live Twin version
    N and the SKU bumped to N+1 by the runner itself.
    """
    evidence = run_flagship_scenario.run_flagship(f"{run_id}-g06-neg", mode="negative")

    assert evidence["result"] == "PASS"
    assert evidence["mode"] == "negative"
    checks = _checks(evidence)
    assert checks["p017_starts_at_version_n"] is True
    assert checks["p017_moved_to_n_plus_1"] is True
    assert checks["guard_returns_refresh_required"] is True
    assert checks["guard_reason_is_version_stale"] is True
    assert checks["no_commit_binding_issued"] is True
    assert checks["live_twin_unmutated"] is True
    assert checks["guard_audit_records_correlation_id"] is True

    runtime = evidence["runtime"]
    # Same production-mode field shape as happy mode so the matrix stays uniform.
    assert runtime["environment"] == "in-memory preflight"
    assert runtime["provider_mode"] == "fake"
    assert runtime["live_twin_backend"] == "memory"
    assert runtime["cloud_run_revision"] is None
    assert runtime["mode"] == "negative"
    assert runtime["verifier_verdict"] == "NOT_RUN"
    assert "dcg_audit" in runtime
    guard_breakdown = runtime["dcg_audit"]["gate_breakdown"]
    assert "context" in guard_breakdown
    assert guard_breakdown["context"]["verdict"] == "REFRESH_REQUIRED"
    assert guard_breakdown["context"]["reason_code"] == "VERSION_STALE"
    json.dumps(evidence, default=str)


def test_g06_cli_accepts_negative_mode(run_id: str, tmp_path) -> None:
    out = tmp_path / "g06-negative.json"
    assert run_flagship_scenario.main(
        ["--mode", "negative", "--out", str(out), "--run-id", f"{run_id}-g06-cli-neg"]
    ) == 0
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["mode"] == "negative"
    assert evidence["result"] == "PASS"


def test_g06_cli_default_is_happy(run_id: str, tmp_path) -> None:
    out = tmp_path / "g06-happy.json"
    assert run_flagship_scenario.main(
        ["--out", str(out), "--run-id", f"{run_id}-g06-cli-happy"]
    ) == 0
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["mode"] == "happy"
    assert evidence["result"] == "PASS"


def test_g06_production_mode_runtime_fields_are_environment_overridable(run_id: str, monkeypatch) -> None:
    """The fields reviewers required are env-overridable; the production shell
    sets them. Verify the script reads them at import-time and persists them
    into the runtime block.
    """
    monkeypatch.setenv("G06_ENVIRONMENT", "production-cloudrun")
    monkeypatch.setenv("G06_PROVIDER_MODE", "vertex_gemini")
    monkeypatch.setenv("LIVE_TWIN_BACKEND", "firestore")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("G06_CLOUD_RUN_REVISION", "retailtwin-api-00099-abc")
    # Re-import so module-level constants pick up the env vars.
    import importlib

    importlib.reload(run_flagship_scenario)
    try:
        evidence = run_flagship_scenario.run_flagship(
            f"{run_id}-g06-prod-env", mode="negative"
        )
        rt = evidence["runtime"]
        assert rt["environment"] == "production-cloudrun"
        assert rt["provider_mode"] == "vertex_gemini"
        assert rt["live_twin_backend"] == "firestore"
        assert rt["app_env"] == "production"
        assert rt["cloud_run_revision"] == "retailtwin-api-00099-abc"
    finally:
        # Reload back to the in-memory preflight defaults so later tests are
        # not affected by the env override.
        monkeypatch.delenv("G06_ENVIRONMENT", raising=False)
        monkeypatch.delenv("G06_PROVIDER_MODE", raising=False)
        monkeypatch.delenv("LIVE_TWIN_BACKEND", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("G06_CLOUD_RUN_REVISION", raising=False)
        importlib.reload(run_flagship_scenario)
