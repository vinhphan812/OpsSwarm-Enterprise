"""Unit tests for scripts/verify_coverage_gate.py.

These tests prove that the guard which prevents coverage-gate drift actually
fails when the declared thresholds disagree.  The original defect was
``.github/workflows/ci.yml`` enforcing ``--cov-fail-under=89`` while
``pyproject.toml`` and the ``Makefile`` declared 90.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from verify_coverage_gate import (  # noqa: E402
    CANONICAL_LOCATION,
    CI_WORKFLOW_LOCATION,
    MAKEFILE_LOCATION,
    MINIMUM_THRESHOLD,
    declared_gates,
    derived_gate,
    literal_thresholds,
    main,
    pyproject_threshold,
    verify,
)


PYPROJECT_TEMPLATE = """
[tool.coverage.run]
source = ["opsswarm"]

[tool.coverage.report]
fail_under = {value}
"""

MAKEFILE_TEMPLATE = """
coverage:
\tpython -m pytest -q --cov=opsswarm --cov-fail-under={value}
"""

# A ci.yml that states the threshold literally.
CI_LITERAL_TEMPLATE = """
name: CI
jobs:
  coverage:
    steps:
      - name: Run test suite with coverage
        run: >-
          python -m pytest
          --cov=opsswarm
          --cov-fail-under={value}
"""

# A ci.yml that resolves the threshold from pyproject.toml at run time.
CI_RESOLVED_TEMPLATE = """
name: CI
jobs:
  coverage:
    steps:
      - name: Resolve coverage gate from pyproject.toml
        id: coverage-gate
        run: echo "value=$(python scripts/verify_coverage_gate.py --print-value)" >> "$GITHUB_OUTPUT"

      - name: Run test suite with coverage
        run: >-
          python -m pytest
          --cov=opsswarm
          --cov-fail-under=${{{{ steps.coverage-gate.outputs.value }}}}
"""


def _write(
    root: Path,
    *,
    pyproject: str,
    makefile: str,
    ci: str,
) -> Path:
    """Materialise a minimal repository carrying the three gate declarations."""
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (root / "Makefile").write_text(makefile, encoding="utf-8")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(ci, encoding="utf-8")
    return root


@pytest.fixture
def consistent_repo(tmp_path: Path) -> Path:
    """A repository whose declarations all agree on 90."""
    return _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )


# ---------------------------------------------------------------------------
# The shipped repository
# ---------------------------------------------------------------------------


def test_repository_declarations_are_mutually_consistent() -> None:
    """The shipped repository declares one and the same threshold everywhere."""
    errors = verify(PROJECT_ROOT)

    assert errors == [], f"coverage gate declarations must agree: {errors}"


def test_pyproject_is_the_declared_source_of_truth() -> None:
    """pyproject.toml declares the policy threshold of 90."""
    canonical = pyproject_threshold(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert canonical == 90.0
    assert MINIMUM_THRESHOLD == 90.0
    assert CANONICAL_LOCATION.startswith("pyproject.toml")


def test_ci_workflow_enforces_the_policy_threshold() -> None:
    """ci.yml no longer carries the drifted 89 literal from the original defect."""
    ci_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "--cov-fail-under=89" not in ci_text
    assert literal_thresholds(ci_text) == []


def test_ci_workflow_resolves_the_gate_from_pyproject() -> None:
    """ci.yml resolves its enforced gate from pyproject.toml, not a literal."""
    ci_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert derived_gate(ci_text), "ci.yml must resolve the gate from the source of truth"


def test_makefile_enforces_the_policy_threshold() -> None:
    """The Makefile coverage target enforces 90."""
    makefile_text = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert literal_thresholds(makefile_text) == [90.0]


def test_every_workflow_and_script_is_audited_by_the_guard() -> None:
    """The guard covers every workflow and helper script, not only ci.yml."""
    gates = declared_gates(PROJECT_ROOT)

    assert CI_WORKFLOW_LOCATION in gates
    assert MAKEFILE_LOCATION in gates
    for workflow in (
        "release.yml",
        "required-checks-bridge.yml",
        "security.yml",
        "skill-gates.yml",
    ):
        assert f".github/workflows/{workflow} --cov-fail-under" in gates


# ---------------------------------------------------------------------------
# The guard fails on drift
# ---------------------------------------------------------------------------


def test_guard_fails_when_ci_threshold_drifts_below_policy(tmp_path: Path) -> None:
    """The guard fails when ci.yml enforces a lower threshold than the policy.

    This is the exact drift that the original defect introduced: ci.yml said
    89 while pyproject.toml and the Makefile said 90.
    """
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=89),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the declarations drift apart"
    assert any("disagree" in error for error in errors), errors


def test_guard_fails_when_makefile_threshold_drifts(tmp_path: Path) -> None:
    """The guard fails when the Makefile enforces a different threshold."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=95),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the Makefile drifts apart"
    assert any("disagree" in error for error in errors), errors


def test_guard_fails_when_policy_threshold_is_lowered(tmp_path: Path) -> None:
    """The guard fails when pyproject.toml lowers the policy below 90."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=60),
        makefile=MAKEFILE_TEMPLATE.format(value=60),
        ci=CI_LITERAL_TEMPLATE.format(value=60),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the policy threshold is lowered"
    assert any("policy floor" in error for error in errors), errors


def test_guard_fails_when_policy_is_lowered_while_others_agree(tmp_path: Path) -> None:
    """Lowering only pyproject.toml is caught, even though the rest still says 60."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=60),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the policy threshold is lowered"
    assert any("policy floor" in error for error in errors), errors


def test_guard_fails_when_a_declaration_is_missing(tmp_path: Path) -> None:
    """The guard fails when the canonical policy declaration disappears."""
    root = _write(
        tmp_path,
        pyproject="[tool.coverage.run]\nsource = [\"opsswarm\"]\n",
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the policy declaration disappears"
    assert any("source of truth" in error for error in errors), errors


def test_guard_fails_when_the_makefile_gate_is_removed(tmp_path: Path) -> None:
    """The Makefile must state the threshold so local runs are held to the bar."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile="coverage:\n\tpython -m pytest -q --cov=opsswarm\n",
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )

    errors = verify(root)

    assert errors, "the guard must fail when the Makefile gate is removed"
    assert any("Makefile" in error for error in errors), errors


def test_guard_fails_when_ci_declares_no_gate_at_all(tmp_path: Path) -> None:
    """ci.yml must either state the threshold or resolve it, never neither."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci="name: CI\njobs:\n  coverage:\n    steps:\n      - run: python -m pytest -q\n",
    )

    errors = verify(root)

    assert errors, "the guard must fail when ci.yml declares no gate"
    assert any(CI_WORKFLOW_LOCATION in error for error in errors), errors


def test_guard_fails_when_one_file_declares_two_thresholds(tmp_path: Path) -> None:
    """Two different thresholds inside one file are reported as an error."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90) + MAKEFILE_TEMPLATE.format(value=89),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )

    errors = verify(root)

    assert errors, "the guard must fail when one file declares two thresholds"
    assert any("more than one threshold" in error for error in errors), errors


def test_guard_fails_when_another_workflow_drifts(tmp_path: Path) -> None:
    """A drifting gate in any workflow is caught, not only in ci.yml."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )
    (root / ".github" / "workflows" / "release.yml").write_text(
        CI_LITERAL_TEMPLATE.format(value=80), encoding="utf-8"
    )

    errors = verify(root)

    assert errors, "the guard must fail when any workflow drifts apart"
    assert any("release.yml" in error for error in errors), errors


def test_guard_fails_when_a_helper_script_drifts(tmp_path: Path) -> None:
    """A drifting gate in a helper script is caught too."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=90),
    )
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run_coverage.py").write_text(
        "subprocess.run(['pytest', '--cov-fail-under=70'])\n", encoding="utf-8"
    )

    errors = verify(root)

    assert errors, "the guard must fail when a helper script drifts apart"
    assert any("run_coverage.py" in error for error in errors), errors


# ---------------------------------------------------------------------------
# The resolved-gate form is accepted
# ---------------------------------------------------------------------------


def test_guard_accepts_a_resolved_ci_gate(tmp_path: Path) -> None:
    """A ci.yml that resolves the gate from pyproject.toml is consistent."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_RESOLVED_TEMPLATE,
    )

    assert verify(root) == []


def test_guard_still_catches_drift_behind_a_resolved_ci_gate(tmp_path: Path) -> None:
    """Resolving the CI gate does not excuse a drifting Makefile."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=80),
        ci=CI_RESOLVED_TEMPLATE,
    )

    errors = verify(root)

    assert errors, "the guard must fail when the Makefile drifts apart"
    assert any("Makefile" in error for error in errors), errors


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_literal_parser_accepts_the_supported_spellings() -> None:
    """The parser accepts both the '=' and ' ' spellings of the flag."""
    assert literal_thresholds("pytest --cov-fail-under=90\n") == [90.0]
    assert literal_thresholds("pytest --cov-fail-under 90\n") == [90.0]
    assert literal_thresholds("no gate here\n") == []


def test_literal_parser_ignores_a_resolved_gate() -> None:
    """A resolved gate carries no literal value to compare."""
    assert literal_thresholds(CI_RESOLVED_TEMPLATE) == []


def test_pyproject_threshold_ignores_fail_under_outside_the_report_section() -> None:
    """Only [tool.coverage.report] fail_under counts as the declaration."""
    text = """
[tool.coverage.run]
fail_under = 10

[tool.coverage.report]
fail_under = 90
"""

    assert pyproject_threshold(text) == 90.0


def test_pyproject_threshold_returns_none_for_unparseable_input() -> None:
    """Unparseable TOML yields no threshold rather than a wrong one."""
    assert pyproject_threshold("this is not toml = = =") is None


def test_pyproject_threshold_returns_none_when_fail_under_is_absent() -> None:
    """A pyproject.toml without fail_under yields no threshold."""
    assert pyproject_threshold("[tool.coverage.run]\nsource = [\"opsswarm\"]\n") is None


# ---------------------------------------------------------------------------
# Command-line entry point
# ---------------------------------------------------------------------------


def test_main_returns_zero_for_a_consistent_repository(consistent_repo: Path) -> None:
    """The CLI succeeds when every declaration agrees."""
    assert main(["--root", str(consistent_repo)]) == 0


def test_main_returns_one_for_a_drifted_repository(tmp_path: Path) -> None:
    """The CLI fails when a declaration drifts apart."""
    root = _write(
        tmp_path,
        pyproject=PYPROJECT_TEMPLATE.format(value=90),
        makefile=MAKEFILE_TEMPLATE.format(value=90),
        ci=CI_LITERAL_TEMPLATE.format(value=89),
    )

    assert main(["--root", str(root)]) == 1


def test_main_prints_the_canonical_value(
    consistent_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI can print the policy value for use by the CI workflow."""
    assert main(["--root", str(consistent_repo), "--print-value"]) == 0

    assert capsys.readouterr().out.strip() == "90"
