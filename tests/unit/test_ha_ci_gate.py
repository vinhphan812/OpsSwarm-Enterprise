"""Contract tests for the PostgreSQL CI gate (Issue #70, Phase 2).

The HA PostgreSQL suite is the only evidence that the Phase 2 schema works
against a real PostgreSQL server.  If that job is skipped -- because the
service container failed to start, because the job was made conditional, or
because a filter excluded it -- the schema regression would pass CI
unnoticed.  These tests pin the two halves of the guarantee:

* the CI workflow really runs the PostgreSQL-backed suites against a
  PostgreSQL service container, and
* the required-checks bridge cannot accept that job as anything other than
  ``success``.

The bridge half is verified *behaviourally*: the check lists the workflow
actually passes to the poller are extracted from the workflow YAML and the
poller's verdict logic is executed against a stubbed check-runs payload.
Asserting on the YAML alone would only prove the text says the right thing,
not that the gate behaves that way.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BRIDGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "required-checks-bridge.yml"

HA_POSTGRES_JOB_ID = "ha-postgres"
HA_POSTGRES_JOB_NAME = "HA PostgreSQL schema and concurrency"
HA_POSTGRES_SUITES = (
    "tests/integration/test_ha_schema_postgres.py",
    "tests/faults/test_ha_lease_concurrency_postgres.py",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _bridge_run_script() -> str:
    """Return the shell script the required-checks bridge actually runs."""
    workflow = _load(BRIDGE_WORKFLOW)
    step = next(
        step
        for step in workflow["jobs"]["ci-required"]["steps"]
        if step.get("shell") == "bash"
    )
    return step["run"]


def _cli_checks(run: str, flag: str) -> list[str]:
    """Return the check names passed to the poller under ``flag``."""
    names: list[str] = []
    collecting = False
    for line in run.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            collecting = stripped.startswith(f"{flag} ")
            continue
        if not collecting:
            continue
        names.extend(re.findall(r'"([^"]+)"', stripped))
    assert names, f"the bridge must pass {flag!r} to the check poller"
    return names


def _poller():
    """Import the bridge check poller as a module."""
    spec = importlib.util.spec_from_file_location(
        "bridge_poll_check_runs", REPO_ROOT / "scripts" / "poll_check_runs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_runs(names: list[str], conclusion_for: dict[str, str]) -> list[dict]:
    """Build a GitHub check-runs payload with the requested conclusions."""
    return [
        {
            "name": name,
            "status": "completed",
            "conclusion": conclusion_for.get(name, "success"),
            "started_at": "2026-01-01T00:00:00Z",
        }
        for name in names
    ]


def test_ci_workflow_runs_the_ha_postgres_suites_against_a_postgres_service() -> None:
    """The PostgreSQL suites must run in CI against a real PostgreSQL server."""
    workflow = _load(CI_WORKFLOW)
    job = workflow["jobs"][HA_POSTGRES_JOB_ID]

    assert job["name"] == HA_POSTGRES_JOB_NAME

    postgres = job["services"]["postgres"]
    assert "postgres" in postgres["image"]

    steps = "\n".join(step.get("run", "") for step in job["steps"])
    for suite in HA_POSTGRES_SUITES:
        assert suite in steps, f"the CI job must run {suite}"

    # The suite needs a database to talk to.
    assert "HA_TEST_DATABASE_URL" in job["env"]


def test_the_postgres_job_is_not_conditional() -> None:
    """A conditional job that skipped would leave the gate without evidence.

    The artifact-upload steps are allowed to carry ``if: always()`` -- that
    is how a failing run still uploads its log.  What must not be conditional
    is the job itself or the step that actually runs the suites.
    """
    workflow = _load(CI_WORKFLOW)
    job = workflow["jobs"][HA_POSTGRES_JOB_ID]

    assert "if" not in job, "the PostgreSQL job must not be conditional"

    for step in job["steps"]:
        if step.get("uses", "").startswith("actions/upload-artifact"):
            assert step.get("if") == "always()", (
                "an artifact upload must always run so a failed run still uploads its evidence"
            )
            continue
        assert "if" not in step, f"the step {step.get('name')!r} must not be conditional"


def test_the_bridge_holds_the_postgres_job_to_a_strict_success() -> None:
    """The bridge must require ``success`` from the PostgreSQL job."""
    run = _bridge_run_script()

    strict = _cli_checks(run, "--strict-checks")
    assert HA_POSTGRES_JOB_NAME in strict

    expected = _cli_checks(run, "--checks")
    assert HA_POSTGRES_JOB_NAME not in expected, (
        "the PostgreSQL job must be held to the strict list, not the list that "
        "accepts a skipped conclusion"
    )


def test_the_bridge_accepts_a_fully_successful_run() -> None:
    """The gate must still pass when every check, including the job, succeeds."""
    run = _bridge_run_script()
    expected = _cli_checks(run, "--checks")
    strict = _cli_checks(run, "--strict-checks")
    names = expected + strict

    passed, pending = _poller().evaluate_checks(
        _check_runs(names, {}), expected, strict
    )

    assert passed
    assert not pending


@pytest.mark.parametrize("conclusion", ["skipped", "neutral", "cancelled", "timed_out"])
def test_the_bridge_refuses_a_postgres_job_that_did_not_succeed(conclusion: str) -> None:
    """A PostgreSQL job that did not report ``success`` must fail the gate.

    This is the gap the strict list exists to close: without it the bridge
    would accept a ``skipped`` PostgreSQL job, because the ordinary check
    list treats ``skipped`` as a pass.
    """
    run = _bridge_run_script()
    expected = _cli_checks(run, "--checks")
    strict = _cli_checks(run, "--strict-checks")
    names = expected + strict
    payload = _check_runs(names, {HA_POSTGRES_JOB_NAME: conclusion})

    passed, pending = _poller().evaluate_checks(payload, expected, strict)

    assert not passed, f"the bridge must fail when the PostgreSQL job reports {conclusion!r}"
    assert not pending


def test_the_bridge_refuses_a_missing_postgres_job() -> None:
    """A PostgreSQL job that never reported at all must not pass the gate."""
    run = _bridge_run_script()
    expected = _cli_checks(run, "--checks")
    strict = _cli_checks(run, "--strict-checks")
    without_postgres = [name for name in expected + strict if name != HA_POSTGRES_JOB_NAME]

    passed, pending = _poller().evaluate_checks(
        _check_runs(without_postgres, {}), expected, strict
    )

    assert not passed, "the bridge must fail when the PostgreSQL job never reported"
    assert not pending
