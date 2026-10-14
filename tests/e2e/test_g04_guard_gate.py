"""G04 Guard Gate (#51): the harness passes on main and fails when the guard is bypassed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gates import g04_guard_gate
from gates.g04_guard_gate import run_g04
from retailtwin_api.guard.decision_context_guard.guard import DecisionContextGuard


def _checks(evidence: dict) -> dict[str, bool]:
    return {item["check"]: item["passed"] for item in evidence["checks"]}


def test_g04_passes_end_to_end(run_id: str) -> None:
    evidence = run_g04(f"{run_id}-g04")

    assert evidence["result"] == "PASS", [c for c in evidence["checks"] if not c["passed"]]
    assert all(_checks(evidence).values())
    stale = evidence["steps"]["stale_submit"]
    assert stale["response"]["verdict"] == "REFRESH_REQUIRED"
    assert stale["live_after"] == evidence["steps"]["stale_mutation"]["after"]
    d1 = evidence["steps"]["d1"]["decision_id"]
    d2 = evidence["steps"]["replan"]["result"]["committed_decision_id"]
    assert d2 != d1
    chain = [(e["stage"], e["decision_id"], e["verdict"]) for e in evidence["steps"]["guard_audit_chain"]]
    assert ("commit", d1, "ALLOW") not in chain
    assert ("commit", d2, "ALLOW") in chain
    assert any(record["logger"].endswith("replan") for record in evidence["logs"])
    json.dumps(evidence, default=str)


def test_g04_reports_fail_when_the_version_gate_is_bypassed(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    """No false PASS: with the context-version gate disabled the stale decision commits."""
    monkeypatch.setattr(DecisionContextGuard, "_context", _skip_versions)

    evidence = run_g04(f"{run_id}-g04-bypass")

    checks = _checks(evidence)
    assert evidence["result"] == "FAIL"
    assert checks["stale_decision_refused"] is False
    assert checks["executor_wrote_nothing"] is False
    assert checks["no_usable_authorization"] is False


def _skip_versions(self: DecisionContextGuard, decision, ctx):  # type: ignore[no-untyped-def]
    for action in decision.proposed_actions:
        doc = self._twin.get_inventory(ctx.store_id, action.sku)
        if doc is not None:
            ctx.live[action.sku] = doc
    return None


def test_cli_writes_evidence_and_exits_zero_on_pass(tmp_path: Path, run_id: str, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "g04.json"

    assert g04_guard_gate.main(["--out", str(out), "--run-id", f"{run_id}-g04-cli"]) == 0

    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["result"] == "PASS"
    assert evidence["run_id"] == f"{run_id}-g04-cli"
    assert "PASS" in capsys.readouterr().out


def test_cli_exits_nonzero_on_fail(monkeypatch: pytest.MonkeyPatch, run_id: str) -> None:
    monkeypatch.setattr(DecisionContextGuard, "_context", _skip_versions)
    assert g04_guard_gate.main(["--run-id", f"{run_id}-g04-cli-fail"]) == 1
