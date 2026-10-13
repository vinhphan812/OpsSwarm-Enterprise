#!/usr/bin/env python3
"""Enforce critical-path coverage thresholds.

This script verifies that real critical-path implementations have elevated coverage
(>=90% line, >=85% branch) in the current coverage.xml report.

For stub-only modules, elevated coverage is deferred.
For real implementations, actual coverage data from coverage.xml is checked.

Exits 0 if all real critical-path code meets elevated thresholds.
Exits 1 if any real critical-path implementation lacks sufficient coverage.
"""
import subprocess
import sys
import os
import re
import xml.etree.ElementTree as ET

# Directories subject to elevated thresholds (>=90% line, >=85% branch)
CRITICAL_DIRS = [
    "guard/decision-context-guard",
    "services/executor",
    "services/twin",
    "services/simulation",
    "services/verifier",
]

# Critical files - must have >=90% line, >=85% branch coverage
CRITICAL_FILES = [
    "apps/api/retailtwin_api/events.py",
]

# Stub-only indicators (no real implementation)
STUB_PATTERNS = [
    r"^#\s*(?:stub|todo|not implemented|deferred)",
    r"raise\s+NotImplementedError",
]

# Elevated thresholds for critical-path code
CRITICAL_LINE_THRESHOLD = 0.90
CRITICAL_BRANCH_THRESHOLD = 0.85


def get_repo_root() -> str:
    """Get the repository root directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def has_real_code(path: str) -> bool:
    """Return True if path contains non-stub implementation code."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for pattern in STUB_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
                return False
        lines = [
            l.strip()
            for l in content.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        return len(lines) >= 5
    except Exception:
        return False


def get_coverage(path: str) -> tuple[float, float] | None:
    """Get (line_rate, branch_rate) for a file from coverage.xml. Returns None if not found."""
    repo_root = get_repo_root()
    cov_xml = os.path.join(repo_root, "apps", "api", "coverage.xml")
    if not os.path.exists(cov_xml):
        return None
    try:
        tree = ET.parse(cov_xml)
        root = tree.getroot()
        req_abs = os.path.abspath(os.path.join(repo_root, path)).replace("\\", "/")
        path_parts = path.replace("\\", "/").split("/")
        base_name = path_parts[-1] if path_parts else ""
        found_files: list[tuple[str, str, str]] = []

        for cls in root.findall(".//class"):
            fn = cls.get("filename", "")
            fn_norm = fn.replace("\\", "/")
            fn_abs = os.path.abspath(fn_norm).replace("\\", "/")
            fn_base = fn_norm.split("/")[-1] if "/" in fn_norm else fn_norm
            found_files.append((fn_norm, fn_abs, fn_base))
            lr = cls.get("line-rate")
            br = cls.get("branch-rate")

            # Strategy 1: repo-relative endswith
            if fn_norm.endswith(path) or path.endswith(fn_norm):
                if lr is not None and br is not None:
                    return float(lr), float(br)

            # Strategy 2: absolute-path normalization
            if fn_abs == req_abs:
                if lr is not None and br is not None:
                    return float(lr), float(br)

            # Strategy 3: bare filename match
            if fn_base == base_name and base_name:
                if lr is not None and br is not None:
                    return float(lr), float(br)

        print(f"DEBUG no match: path={path!r} base_name={base_name!r} req_abs={req_abs!r}")
        print(f"DEBUG filenames: {sorted(set(f[0] for f in found_files))}")
        return None
    except Exception:
        return None


def check_file(rel_path: str) -> tuple[bool, str | None]:
    """Check a critical file. Returns (ok, detail)."""
    repo_root = get_repo_root()
    full_path = os.path.join(repo_root, rel_path)
    if not os.path.isfile(full_path):
        return True, None
    if not has_real_code(full_path):
        print(f"INFO: {rel_path} is stub-only - elevated threshold deferred.")
        return True, None
    cov = get_coverage(rel_path)
    if cov is None:
        return False, (
            f"ERROR: {rel_path} has real implementation but coverage.xml has no data for it.\n"
            f"  Add tests for {rel_path} or configure per-path coverage."
        )
    line_rate, branch_rate = cov
    if line_rate < CRITICAL_LINE_THRESHOLD or branch_rate < CRITICAL_BRANCH_THRESHOLD:
        return False, (
            f"ERROR: {rel_path} has real implementation with insufficient coverage:\n"
            f"  line rate: {line_rate*100:.1f}% (required: >={CRITICAL_LINE_THRESHOLD*100:.0f}%)\n"
            f"  branch rate: {branch_rate*100:.1f}% (required: >={CRITICAL_BRANCH_THRESHOLD*100:.0f}%)\n"
            f"  Add tests to raise coverage above thresholds."
        )
    print(f"INFO: {rel_path} has real code with sufficient coverage (line={line_rate*100:.1f}%, branch={branch_rate*100:.1f}%).")
    return True, None


def check_dir(rel_dir: str) -> list:
    """Scan a critical directory. Returns list of errors."""
    errors = []
    repo_root = get_repo_root()
    full_dir = os.path.join(repo_root, rel_dir)
    if not os.path.isdir(full_dir):
        return errors
    found_code = False
    for root, dirs, files in os.walk(full_dir):
        for f in files:
            if not (f.endswith(".py") or f.endswith(".ts") or f.endswith(".tsx")):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo_root).replace(os.sep, "/")
            if has_real_code(full_path):
                found_code = True
                cov = get_coverage(rel_path)
                if cov is None:
                    errors.append(
                        f"ERROR: {rel_path} has real implementation but no coverage data.\n"
                        f"  Elevated thresholds (>={CRITICAL_LINE_THRESHOLD*100:.0f}% line, >={CRITICAL_BRANCH_THRESHOLD*100:.0f}% branch) required."
                    )
                else:
                    line_rate, branch_rate = cov
                    if line_rate < CRITICAL_LINE_THRESHOLD or branch_rate < CRITICAL_BRANCH_THRESHOLD:
                        errors.append(
                            f"ERROR: {rel_path} has real implementation with insufficient coverage:\n"
                            f"  line: {line_rate*100:.1f}% < {CRITICAL_LINE_THRESHOLD*100:.0f}%, branch: {branch_rate*100:.1f}% < {CRITICAL_BRANCH_THRESHOLD*100:.0f}%"
                        )
                    else:
                        print(f"INFO: {rel_path} has sufficient coverage (line={line_rate*100:.1f}%, branch={branch_rate*100:.1f}%).")
    if not found_code:
        print(f"INFO: {rel_dir}/ contains stub files only - elevated threshold deferred.")
    return errors


def main() -> int:
    repo_root = get_repo_root()
    print(f"Repository root: {repo_root}")
    os.chdir(repo_root)

    all_errors = []
    for rel_path in CRITICAL_FILES:
        ok, detail = check_file(rel_path)
        if not ok and detail:
            all_errors.append(detail)

    for rel_dir in CRITICAL_DIRS:
        all_errors.extend(check_dir(rel_dir))

    if all_errors:
        print()
        for err in all_errors:
            print(err)
        print()
        print("FAIL: critical-path coverage enforcement is not satisfied.")
        return 1

    print("PASS: all critical-path implementations have sufficient coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
