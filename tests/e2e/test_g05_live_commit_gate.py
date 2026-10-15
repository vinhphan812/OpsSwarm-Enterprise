"""G05 Live Commit Gate (#52): the harness passes on main and fails when the Executor applies other actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gates import g05_live_commit_gate
from gates.g05_live_commit_gate import run_g05
from retailtwin_api.agents.executor import executor as executor_module


def _checks(evidence: dict[str, Any]) -> dict[str, bool]:
    return {item["check"]: item["passed"] for item in evidence["checks"]}


def test_g05_passes_end_to_end(run_id: str) -> None:
    evidence = run_g05(f"{run_id}-g05")

    assert evidence["result"] == "PASS", [c for c in evidence["checks"] if not c["passed"]]
    commit = evidence["steps"]["commit"]
    assert commit["response"]["verdict"] == "ALLOW"
    assert commit["live_after"]["version"] == commit["live_before"]["version"] + 1
    assert commit["store_version_before"] != commit["store_version_after"]
    assert evidence["steps"]["simulation"]["chosen"] == commit["decision_id"]
    assert [e["stage"] for e in commit["guard_audit"]] == ["authorize", "commit"]
    assert evidence["steps"]["failure_cases"]["infeasible"]["detail_code"] == "INFEASIBLE_ACTION"
    json.dumps(evidence, default=str)


def test_g05_reports_fail_when_the_executor_applies_other_actions(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    """No false PASS: an Executor that drops an authorized action is caught, and the Verifier sees it."""
    real_apply = executor_module._apply

    def drop_last_action(decision: Any, originals: Any, now: Any) -> Any:
        trimmed = decision.model_copy(update={"proposed_actions": decision.proposed_actions[:-1]})
        return real_apply(trimmed, originals, now)

    monkeypatch.setattr(executor_module, "_apply", drop_last_action)

    evidence = run_g05(f"{run_id}-g05-bad-executor")

    checks = _checks(evidence)
    assert evidence["result"] == "FAIL"
    assert checks["live_twin_shows_exactly_the_authorized_transition"] is False
    assert checks["verifier_confirmed_the_live_state"] is False
    assert evidence["steps"]["verification"]["status"] == "REGRESSION"


def test_cli_writes_evidence_and_exits_zero_on_pass(tmp_path: Path, run_id: str) -> None:
    out = tmp_path / "g05.json"
    assert g05_live_commit_gate.main(["--out", str(out), "--run-id", f"{run_id}-g05-cli"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["result"] == "PASS"
