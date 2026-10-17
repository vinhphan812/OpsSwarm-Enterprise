"""Contract tests for the Day-0 Foundation Gate script (issue #10).

These tests do not call Google Cloud. They pin the structure of
``scripts/day0_evidence.py`` and the orchestration shell
``scripts/verify-day0-gate.sh`` so that future refactors cannot silently
remove a required check or change the evidence JSON schema.

Run from ``apps/api``:

    python -m pytest tests/test_day0_smoke.py -q

Or from anywhere in the repo:

    PYTHONPATH=apps/api python -m pytest apps/api/tests/test_day0_smoke.py -q
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EVIDENCE_SCRIPT = SCRIPTS_DIR / "day0_evidence.py"
ORCHESTRATOR_SCRIPT = SCRIPTS_DIR / "verify-day0-gate.sh"
ADR_FILE = REPO_ROOT / "docs" / "adr" / "0028-day-0-foundation-smoke-and-freeze.md"
RUNBOOK_FILE = REPO_ROOT / "docs" / "DAY0_GATE_RUNBOOK.md"


REQUIRED_CHECK_IDS = {
    "preconditions",
    "cloud-run",
    "firestore-p001",
    "local-api-firestore",
    "pubsub-event-path",
    "vertex-live-inventory",
    "repo-hygiene",
}


# ── Script file presence ─────────────────────────────────────────────────────
def test_evidence_script_exists_and_is_executable() -> None:
    assert EVIDENCE_SCRIPT.is_file(), f"Missing {EVIDENCE_SCRIPT}"
    mode = EVIDENCE_SCRIPT.stat().st_mode
    assert mode & 0o111, f"{EVIDENCE_SCRIPT} is not executable"


def test_orchestrator_script_exists_and_is_executable() -> None:
    assert ORCHESTRATOR_SCRIPT.is_file(), f"Missing {ORCHESTRATOR_SCRIPT}"
    mode = ORCHESTRATOR_SCRIPT.stat().st_mode
    assert mode & 0o111, f"{ORCHESTRATOR_SCRIPT} is not executable"


def test_adr_0028_exists() -> None:
    assert ADR_FILE.is_file(), f"Missing ADR {ADR_FILE}"
    text = ADR_FILE.read_text(encoding="utf-8")
    assert "Status" in text
    assert "Accepted" in text or "Proposed" in text
    # Issue link must be present
    assert "issues/10" in text


def test_runbook_exists() -> None:
    assert RUNBOOK_FILE.is_file(), f"Missing runbook {RUNBOOK_FILE}"


# ── Evidence script structure ────────────────────────────────────────────────
def test_evidence_script_references_all_required_checks() -> None:
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    for check_id in REQUIRED_CHECK_IDS:
        # Look for either the literal string in a record() call or
        # an explicit "id": "..." mapping in the JSON output.
        pattern = (
            rf'record\(\s*[^)]*"{re.escape(check_id)}"'
            rf'|check\(\s*[^,]+,\s*"{re.escape(check_id)}"'
            rf'|"id":\s*"{re.escape(check_id)}"'
        )
        assert re.search(pattern, text), (
            f"Evidence script does not reference check id {check_id!r}"
        )


def test_evidence_script_targets_canonical_project() -> None:
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    assert "retailtwin-ai-511002" in text
    assert "us-central1" in text
    assert "gemini-2.5-flash" in text


def test_evidence_script_emits_canonical_evidence_shape() -> None:
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    for field in (
        '"schema_version"',
        '"run_id"',
        '"started_at"',
        '"finished_at"',
        '"project"',
        '"region"',
        '"vertex_model"',
        '"checks"',
        '"summary"',
    ):
        assert field in text, f"Evidence script does not emit {field}"


def test_evidence_script_does_not_hardcode_secrets() -> None:
    """Refuse any obvious secret value in the script."""
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    # Reject high-entropy key-looking substrings outside of the audit log.
    for pattern in ("AIza", "ghp_", "BEGIN PRIVATE KEY"):
        assert pattern not in text, f"Evidence script must not embed {pattern!r}"


# ── Orchestrator structure ───────────────────────────────────────────────────
def test_orchestrator_calls_evidence_script() -> None:
    text = ORCHESTRATOR_SCRIPT.read_text(encoding="utf-8")
    assert "day0_evidence.py" in text


def test_orchestrator_rejects_wrong_account() -> None:
    """The shell must not allow running the gate without the right account
    when DAY0_REQUIRED_ACCOUNTS is set. By default the gate is
    capability-based and does not require a named human identity."""
    text = ORCHESTRATOR_SCRIPT.read_text(encoding="utf-8")
    # The default behaviour (no env var) does not pin to a specific
    # personal email; identity is verified by capability probes in the
    # Python helper.
    assert "DAY0_REQUIRED_ACCOUNTS" in text
    assert "Refusing" in text or "requires" in text or "missing" in text


def test_evidence_script_uses_capability_based_identity_check() -> None:
    """The Python helper must not hard-code a personal account.

    An optional ``DAY0_REQUIRED_ACCOUNTS`` env var may pin execution to
    a specific identity, but the default must accept any gcloud identity
    that can read the canonical project and dataset.
    """
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    assert "DAY0_REQUIRED_ACCOUNTS" in text
    # The preconditions check should probe Firestore + BigQuery capabilities
    # rather than comparing to a literal email address.
    assert "_assert_can_read_firestore" in text
    assert "_assert_can_query_bigquery" in text


def test_orchestrator_runs_npm_build() -> None:
    text = ORCHESTRATOR_SCRIPT.read_text(encoding="utf-8")
    assert "npm run build" in text or "npm ci" in text


def test_orchestrator_propagates_require_bq_row_flag() -> None:
    """The shell must pass --require-bq-row through to the Python helper."""
    text = ORCHESTRATOR_SCRIPT.read_text(encoding="utf-8")
    assert "--require-bq-row" in text
    assert "REQUIRE_BQ_ROW" in text


def test_evidence_script_supports_require_bq_row_env() -> None:
    """The Python helper must accept DAY0_REQUIRE_BQ_ROW=1 to flip BQ to required."""
    text = EVIDENCE_SCRIPT.read_text(encoding="utf-8")
    assert "DAY0_REQUIRE_BQ_ROW" in text
    assert "--require-bq-row" in text


# ── Live evidence schema (using the dry-run JSON we write during a run) ─────
def test_evidence_schema_matches_when_evidence_file_exists(tmp_path: Path) -> None:
    """If an evidence file was written by a previous gate run, validate it.

    Skips when no evidence has been collected yet (CI without network).
    """
    evidence = REPO_ROOT / "artifacts" / "day0-foundation" / "latest.json"
    if not evidence.is_file():
        pytest.skip("No previous evidence file at artifacts/day0-foundation/latest.json")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    for key in (
        "schema_version",
        "run_id",
        "started_at",
        "finished_at",
        "project",
        "region",
        "vertex_model",
        "checks",
        "summary",
    ):
        assert key in payload, f"Missing top-level key {key!r} in evidence file"
    check_ids = {c["id"] for c in payload["checks"]}
    missing = REQUIRED_CHECK_IDS - check_ids
    assert not missing, f"Previous evidence missing required check ids: {missing}"


# ── CLI smoke test (offline) ─────────────────────────────────────────────────
def test_evidence_script_help_runs_offline() -> None:
    """``--help`` must not require network or gcloud."""
    proc = subprocess.run(
        [os.environ.get("PYTHON_BIN", "python3"), str(EVIDENCE_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Day-0 Foundation Gate" in proc.stdout


def test_orchestrator_help_runs_offline() -> None:
    proc = subprocess.run(
        [str(ORCHESTRATOR_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Day-0 Foundation Gate" in proc.stdout