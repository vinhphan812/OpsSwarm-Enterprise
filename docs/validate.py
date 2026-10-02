#!/usr/bin/env python3
"""Docs validation entry point.

Checks documentation for:
1. Broken relative links and anchor references (via validate_doc_links.py)
2. Code examples embedded in markdown files execute without error

This is the canonical entry point for CI and local developer use.
Run: python docs/validate.py [--skip-external] [--verbose]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DOCS_DIR = PROJECT_ROOT / "docs"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Extra files included in linkcheck beyond the docs/ tree.
EXTRA_FILES = [
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "CLAUDE.md",
]


def run_linkcheck(verbose: bool = False) -> int:
    """Run validate_doc_links.py and return its exit code."""
    linkcheck_script = SCRIPTS_DIR / "validate_doc_links.py"
    if not linkcheck_script.exists():
        print(f"[FAIL] validate_doc_links.py not found at {linkcheck_script}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(linkcheck_script)]
    if verbose:
        cmd.append("--verbose")
    # Always pass extra files so root docs are covered
    cmd.extend(["--extra-files"] + [str(f) for f in EXTRA_FILES])

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def run_code_example_tests(verbose: bool = False) -> int:
    """Run tests/unit/test_doc_examples.py if it exists.

    This test file executes code snippets extracted from markdown docs,
    verifying they produce expected output.
    """
    test_file = PROJECT_ROOT / "tests" / "unit" / "test_doc_examples.py"
    if not test_file.exists():
        if verbose:
            print(f"[SKIP] No code-example tests found at {test_file}")
        return 0

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    if verbose:
        cmd.append("-v")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate OpsSwarm documentation: links, anchors, and code examples.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show per-file progress for link checking and verbose pytest output.",
    )
    parser.add_argument(
        "--skip-examples",
        action="store_true",
        help="Skip code-example execution tests (useful when network is unavailable).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" OpsSwarm Documentation Validator")
    print("=" * 60)

    errors = []

    # 1. Link and anchor check
    print("\n[1/2] Running linkcheck (relative links + anchors)…")
    rc = run_linkcheck(verbose=args.verbose)
    if rc != 0:
        errors.append("linkcheck")
        print("[FAIL] Linkcheck failed.")
    else:
        print("[PASS] Linkcheck passed.")

    # 2. Code-example tests
    if args.skip_examples:
        print("\n[2/2] Skipping code-example tests (--skip-examples passed).")
    else:
        print("\n[2/2] Running code-example tests…")
        rc = run_code_example_tests(verbose=args.verbose)
        if rc != 0:
            errors.append("code-examples")
            print("[FAIL] Code-example tests failed.")
        else:
            print("[PASS] Code-example tests passed.")

    # Summary
    print()
    if errors:
        print(f"[RESULT] FAIL — {len(errors)} validation layer(s) failed: {', '.join(errors)}")
        return 1
    print("[RESULT] PASS — All documentation validation layers passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
