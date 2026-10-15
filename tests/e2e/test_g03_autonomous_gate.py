"""G03 Autonomous Gate (#50): the harness passes on main and fails without the Observer wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gates import g03_autonomous_gate
from gates.g03_autonomous_gate import run_g03


def _checks(evidence: dict[str, Any]) -> dict[str, bool]:
    return {item["check"]: item["passed"] for item in evidence["checks"]}


def test_g03_passes_end_to_end(run_id: str) -> None:
    evidence = run_g03(f"{run_id}-g03")

    assert evidence["result"] == "PASS", [c for c in evidence["checks"] if not c["passed"]]
    sale = evidence["steps"]["sale"]
    assert sale["receipt"]["investigation_id"].startswith("inv-evt-")
    assert [e["stage"] for e in sale["activity"]] == ["OBSERVE", "INVESTIGATE", "PLAN", "SIMULATE"]
    assert sale["first_model_request"]["roles"] == ["system", "user"]
    json.dumps(evidence, default=str)


def test_g03_reports_fail_without_autonomy(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    """No false PASS: an app that never hands events to the Observer fails the gate."""
    real = g03_autonomous_gate._autonomous_app

    def without_autonomy(provider: Any, observed_at: str) -> Any:
        app = real(provider, observed_at)
        app.state.autonomy = None
        return app

    monkeypatch.setattr(g03_autonomous_gate, "_autonomous_app", without_autonomy)

    evidence = run_g03(f"{run_id}-g03-off")

    checks = _checks(evidence)
    assert evidence["result"] == "FAIL"
    assert checks["event_accepted_and_handed_to_the_observer"] is False
    assert checks["agent_activity_began_automatically"] is False


def test_cli_writes_evidence_and_exits_zero_on_pass(tmp_path: Path, run_id: str) -> None:
    out = tmp_path / "g03.json"
    assert g03_autonomous_gate.main(["--out", str(out), "--run-id", f"{run_id}-g03-cli"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["result"] == "PASS"
