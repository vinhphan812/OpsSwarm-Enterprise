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

The bridge half is verified *behaviourally*: the bash script the workflow
actually runs is extracted from the workflow YAML and executed against a
stubbed check-runs payload.  Asserting on the YAML alone would only prove
the text says the right thing, not that the gate behaves that way.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def _find_bash() -> str | None:
    """Return the path of a usable bash, or None when there is none.

    On Windows the ``bash`` on ``PATH`` is often a WSL launcher that cannot
    start a real shell, so each candidate is probed before it is used.
    """
    candidates = [
        shutil.which("bash"),
        r"C:/Program Files/Git/bin/bash.exe",
        r"C:/Program Files/Git/usr/bin/bash.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "echo usable"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and "usable" in probe.stdout:
            return candidate
    return None


BASH = _find_bash()
JQ = shutil.which("jq")

requires_shell = pytest.mark.skipif(
    BASH is None or JQ is None,
    reason="bash and jq are required to exercise the bridge script",
)


def _bridge_script() -> str:
    """Return the bash script the required-checks bridge actually runs."""
    workflow = _load(BRIDGE_WORKFLOW)
    steps = workflow["jobs"]["ci-required"]["steps"]
    scripts = [step["run"] for step in steps if step.get("shell") == "bash"]
    assert scripts, "the bridge job must run at least one bash step"
    return "\n".join(scripts)


def _without_polling_delay(script: str) -> str:
    """Shorten the bridge's polling loop so the tests do not wait minutes.

    Only the *waiting* is changed -- the retry count and the sleep -- so the
    verdict logic under test, including the pending/missing path, stays
    exactly as the workflow runs it.
    """
    script = re.sub(r"seq 1 \d+", "seq 1 2", script)
    return re.sub(r"sleep \d+", "sleep 0", script)


def _script_array(script: str, name: str) -> list[str]:
    """Return the quoted entries of a bash array assignment in the script."""
    match = re.search(rf"{name}=\(\s*(.*?)\s*\)", script, re.DOTALL)
    assert match is not None, f"the bridge script must define the {name!r} array"
    return re.findall(r'"([^"]+)"', match.group(1))


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


def _run_bridge(script: str, payload: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    """Execute the bridge script against a stubbed check-runs payload.

    ``curl`` is replaced by a stub that prints the payload, so the script's
    own polling, ``jq`` extraction and verdict logic all run unmodified.
    """
    assert BASH is not None
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    payload_file = tmp_path / "check-runs.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    curl_stub = stub_dir / "curl"
    curl_stub.write_text(
        "#!/usr/bin/env bash\ncat " + str(payload_file).replace("\\", "/") + "\n",
        encoding="utf-8",
    )
    curl_stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(stub_dir) + os.pathsep + env["PATH"]
    env.update({"GH_TOKEN": "test", "REPO": "owner/repo", "HEAD_SHA": "0" * 40})

    return subprocess.run(
        [BASH, "-c", _without_polling_delay(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


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
    script = _bridge_script()

    strict = _script_array(script, "strict")
    assert HA_POSTGRES_JOB_NAME in strict

    expected = _script_array(script, "expected")
    assert HA_POSTGRES_JOB_NAME not in expected, (
        "the PostgreSQL job must be held to the strict list, not the list that "
        "accepts a skipped conclusion"
    )


@requires_shell
def test_the_bridge_accepts_a_fully_successful_run(tmp_path: Path) -> None:
    """The gate must still pass when every check, including the job, succeeds."""
    script = _bridge_script()
    names = _script_array(script, "expected") + _script_array(script, "strict")

    result = _run_bridge(script, {"check_runs": _check_runs(names, {})}, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "All canonical CI checks passed." in result.stdout


@pytest.mark.parametrize("conclusion", ["skipped", "neutral", "cancelled", "timed_out"])
@requires_shell
def test_the_bridge_refuses_a_postgres_job_that_did_not_succeed(
    conclusion: str, tmp_path: Path
) -> None:
    """A PostgreSQL job that did not report ``success`` must fail the gate.

    This is the gap the strict list exists to close: without it the bridge
    would accept a ``skipped`` PostgreSQL job, because the ordinary check
    list treats ``skipped`` as a pass.
    """
    script = _bridge_script()
    names = _script_array(script, "expected") + _script_array(script, "strict")
    payload = {
        "check_runs": _check_runs(names, {HA_POSTGRES_JOB_NAME: conclusion}),
    }

    result = _run_bridge(script, payload, tmp_path)

    assert result.returncode != 0, (
        f"the bridge must fail when the PostgreSQL job reports {conclusion!r}"
    )


@requires_shell
def test_the_bridge_refuses_a_missing_postgres_job(tmp_path: Path) -> None:
    """A PostgreSQL job that never reported at all must not pass the gate."""
    script = _bridge_script()
    names = _script_array(script, "expected") + _script_array(script, "strict")
    without_postgres = [name for name in names if name != HA_POSTGRES_JOB_NAME]

    result = _run_bridge(script, {"check_runs": _check_runs(without_postgres, {})}, tmp_path)

    assert result.returncode != 0, "the bridge must fail when the PostgreSQL job never reported"
