#!/usr/bin/env python3
"""Fail-closed verification that every declared coverage gate agrees.

The repository declares its coverage threshold in several places:

* ``pyproject.toml``            -> ``[tool.coverage.report] fail_under``
* ``Makefile``                  -> ``--cov-fail-under=<n>`` on the ``coverage`` target
* ``.github/workflows/*.yml``    -> ``--cov-fail-under=<n>`` or a resolved value
* ``scripts/*``                  -> ``--cov-fail-under=<n>`` in helper scripts

``pyproject.toml`` is the single source of truth.  ``pytest-cov`` reads
``[tool.coverage.report] fail_under`` from that file directly, so the gate
binds even when a ``--cov-fail-under`` flag is absent from a given command
line.  The CI workflow goes one step further and *resolves* its enforced
value from ``pyproject.toml`` at run time, so the enforced gate cannot drift
from the policy even if this guard were deleted.

The original defect was ``.github/workflows/ci.yml`` enforcing
``--cov-fail-under=89`` while ``pyproject.toml`` and the ``Makefile`` declared
90, which let pull requests land below the documented policy.  This script
fails whenever a declared threshold drifts apart from the policy, and refuses
a policy below the committed floor.

Usage:
    python scripts/verify_coverage_gate.py [--root PATH] [--print-value]

``--print-value`` prints the policy threshold from ``pyproject.toml`` and is
what the CI workflow uses to resolve its enforced gate.

Exit codes:
    0   all declared gates agree and meet the policy floor
    1   the declarations disagree, are missing, or the policy floor was lowered
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
import yaml

# The committed coverage policy floor.  Raising the gate only requires editing
# the declarations; lowering it below this floor is refused on purpose, because
# the threshold is a commitment rather than incidental configuration.
MINIMUM_THRESHOLD = 90.0

# Matches "--cov-fail-under=89" and "--cov-fail-under 89".
CLI_FAIL_UNDER = re.compile(r"--cov-fail-under[= ](\d+(?:\.\d+)?)")

# Matches a gate whose value is resolved from the source of truth at run time,
# either through a GitHub Actions expression ("--cov-fail-under=${{ ... }}") or
# through a shell substitution ("--cov-fail-under=$(...)").
DERIVED_FAIL_UNDER = re.compile(r"--cov-fail-under=\s*(\$\{\{|\$\()")

CANONICAL_LOCATION = "pyproject.toml [tool.coverage.report] fail_under"
MAKEFILE_LOCATION = "Makefile --cov-fail-under"
CI_WORKFLOW_LOCATION = ".github/workflows/ci.yml --cov-fail-under"


def pyproject_threshold(text: str) -> float | None:
    """Extract ``[tool.coverage.report] fail_under`` from pyproject.toml."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    report = data.get("tool", {}).get("coverage", {}).get("report", {})
    value = report.get("fail_under")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_workflow_text(text: str) -> str:
    """Parse workflow YAML robustly using yaml.safe_load (handling folded/block scalars, anchors/aliases)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return text
    strings = []
    def _collect(obj):
        if isinstance(obj, str):
            strings.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _collect(k)
                _collect(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)
    _collect(data)
    return "\n".join(strings) + "\n" + text


def literal_thresholds(text: str) -> list[float]:
    """Return every ``--cov-fail-under=<n>`` value found in a text blob."""
    return [float(match) for match in CLI_FAIL_UNDER.findall(text)]


def derived_gate(text: str) -> bool:
    """Return True when the text resolves its gate from the source of truth."""
    return DERIVED_FAIL_UNDER.search(text) is not None


def read_text(path: Path) -> str:
    """Read a file as UTF-8, tolerating a missing file."""
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def declared_gates(root: Path) -> dict[str, list[float]]:
    """Return the thresholds declared by each gate location."""
    gates: dict[str, list[float]] = {}

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        canonical = pyproject_threshold(read_text(pyproject))
        gates[CANONICAL_LOCATION] = [] if canonical is None else [canonical]

    makefile = root / "Makefile"
    if makefile.is_file():
        gates[MAKEFILE_LOCATION] = literal_thresholds(read_text(makefile))

    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        for workflow in sorted(workflows.glob("*.yml")):
            location = f".github/workflows/{workflow.name} --cov-fail-under"
            wf_text = parse_workflow_text(read_text(workflow))
            gates[location] = literal_thresholds(wf_text)

    scripts = root / "scripts"
    if scripts.is_dir():
        this_file = Path(__file__).resolve()
        for script in sorted(scripts.iterdir()):
            if script.resolve() == this_file:
                continue
            if not script.is_file() or script.suffix not in {".py", ".sh"}:
                continue
            location = f"scripts/{script.name} --cov-fail-under"
            gates[location] = literal_thresholds(read_text(script))

    for cfg_name in ("tox.ini", "setup.cfg"):
        cfg_path = root / cfg_name
        if cfg_path.is_file():
            gates[f"{cfg_name} --cov-fail-under"] = literal_thresholds(read_text(cfg_path))

    return gates


def _disagreement(location: str, values: list[float], canonical: float) -> str | None:
    """Return an error message when a location disagrees with the policy."""
    distinct = sorted(set(values))
    if len(distinct) != 1:
        return (
            f"{location} declares more than one threshold ({distinct}); "
            "exactly one policy value is expected"
        )
    if distinct[0] != canonical:
        return (
            f"{location} declares coverage threshold {distinct[0]:g} but "
            f"pyproject.toml declares {canonical:g}; the declared coverage "
            "gates disagree"
        )
    return None


def verify(root: Path) -> list[str]:
    """Return the list of gate-consistency errors (empty when consistent)."""
    errors: list[str] = []
    gates = declared_gates(root)

    canonical_values = gates.get(CANONICAL_LOCATION, [])
    canonical: float | None = None
    if not canonical_values:
        errors.append(
            f"{CANONICAL_LOCATION} declares no coverage threshold; "
            "pyproject.toml is the source of truth and must declare fail_under"
        )
    else:
        distinct = sorted(set(canonical_values))
        if len(distinct) != 1:
            errors.append(
                f"{CANONICAL_LOCATION} declares more than one threshold ({distinct}); "
                "exactly one policy value is expected"
            )
        canonical = distinct[0]
        if canonical < MINIMUM_THRESHOLD:
            errors.append(
                f"{CANONICAL_LOCATION} declares fail_under = {canonical:g} but the "
                f"project policy floor is {MINIMUM_THRESHOLD:g}; lowering the gate "
                "is not permitted"
            )

    makefile_values = gates.get(MAKEFILE_LOCATION, [])
    if not makefile_values:
        errors.append(
            f"{MAKEFILE_LOCATION} declares no coverage threshold; the Makefile must "
            "state the policy threshold explicitly"
        )
    elif canonical is not None:
        disagreement = _disagreement(MAKEFILE_LOCATION, makefile_values, canonical)
        if disagreement:
            errors.append(disagreement)

    ci_source = parse_workflow_text(read_text(root / ".github" / "workflows" / "ci.yml"))
    ci_values = gates.get(CI_WORKFLOW_LOCATION, [])
    if ci_values and canonical is not None:
        disagreement = _disagreement(CI_WORKFLOW_LOCATION, ci_values, canonical)
        if disagreement:
            errors.append(disagreement)
    elif not ci_values and not derived_gate(ci_source):
        errors.append(
            f"{CI_WORKFLOW_LOCATION} declares no coverage threshold and does not "
            "resolve one from pyproject.toml; the CI gate must either state the "
            "policy value or resolve it"
        )

    for location, values in gates.items():
        if location in {CANONICAL_LOCATION, MAKEFILE_LOCATION, CI_WORKFLOW_LOCATION}:
            continue
        if not values:
            continue
        if canonical is None:
            errors.append(
                f"{location} declares coverage threshold {sorted(set(values))[0]:g} "
                "but pyproject.toml declares no policy value to compare against"
            )
            continue
        disagreement = _disagreement(location, values, canonical)
        if disagreement:
            errors.append(disagreement)

    return errors


def canonical_value(root: Path) -> float | None:
    """Return the policy threshold declared in pyproject.toml."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    return pyproject_threshold(read_text(pyproject))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify declared coverage gates agree.")
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root to inspect (defaults to the repository of this script).",
    )
    parser.add_argument(
        "--print-value",
        action="store_true",
        help="Print the policy threshold declared in pyproject.toml and exit.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]

    if args.print_value:
        canonical = canonical_value(root)
        if canonical is None:
            print(
                f"ERROR: {CANONICAL_LOCATION} is not declared",
                file=sys.stderr,
            )
            return 1
        print(f"{canonical:g}")
        return 0

    errors = verify(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    gates = declared_gates(root)
    detail = ", ".join(
        f"{location} = {values[0]:g}"
        for location, values in gates.items()
        if values and len(set(values)) == 1
    )
    ci_source = parse_workflow_text(read_text(root / ".github" / "workflows" / "ci.yml"))
    suffix = (
        " (ci.yml resolves its gate from pyproject.toml)"
        if derived_gate(ci_source)
        else ""
    )
    print(f"Coverage gate verified: all declarations agree ({detail}).{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
