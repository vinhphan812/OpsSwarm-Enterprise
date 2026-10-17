#!/usr/bin/env python3
"""
Trivy JSON parser regression test suite.

Validates the parser logic embedded in .github/workflows/security.yml
(container-image job, "Scan image for fixable HIGH/CRITICAL" step).
Case 7 (scanner failure RC>1) is exercised by the shell wrapper
(.github/scripts/trivy-parser-regression.sh) and is NOT repeated here.

Test cases (cases 1-6 — case 7 is in the shell wrapper)
──────────
1. Valid clean report          → exit 0
2. Fixable HIGH with FixedVer  → exit 1
3. Unfixed HIGH/CRITICAL       → exit 0  (exception in output)
4. Malformed JSON              → exit 1
5. Missing Results key         → exit 1
6. Missing report file         → exit 1
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FIXTURES_DIR = SCRIPT_DIR / "fixtures"
OUT_DIR = SCRIPT_DIR / "fixtures-out"
OUT_DIR.mkdir(exist_ok=True)

FAILED = 0
_LOG_LINES: list[str] = []


def _log(msg: str) -> None:
    """Print a message and also append it to the captured output stream."""
    _LOG_LINES.append(msg)
    print(msg, file=sys.stdout)


def run_parser(report_path: Path) -> tuple[int, str]:
    """
    Mirror the parser logic from security.yml (container-image job).
    Returns (exit_code, combined_output) where output includes all FIXABLE/EXCEPTION
    lines accumulated during parsing.
    """
    _LOG_LINES.clear()
    try:
        with open(report_path) as fh:
            data = json.load(fh)
    except Exception as exc:
        _log(f"Could not parse report: {exc}")
        return 1, "\n".join(_LOG_LINES)

    # Fail-closed structural validation: data must be a dict with a Results list.
    if not isinstance(data, dict):
        _log(f"Expected a JSON object at the root, got {type(data).__name__}")
        return 1, "\n".join(_LOG_LINES)

    if "Results" not in data:
        _log("Missing Results key")
        return 1, "\n".join(_LOG_LINES)

    if not isinstance(data["Results"], list):
        _log("Results is not a list")
        return 1, "\n".join(_LOG_LINES)

    has_fixable = False
    for result in data.get("Results", []):
        if not isinstance(result, dict):
            _log("Results entry is not a JSON object")
            return 1, "\n".join(_LOG_LINES)

        target = result.get("Target", "?")
        vulns = result.get("Vulnerabilities")
        if vulns is None:
            continue  # no vulns in this target
        if not isinstance(vulns, list):
            _log(f"Vulnerabilities in target {target} is not a list")
            return 1, "\n".join(_LOG_LINES)

        for vuln in vulns:
            if not isinstance(vuln, dict):
                _log("Vulnerability entry is not a JSON object")
                return 1, "\n".join(_LOG_LINES)

            vid = vuln.get("VulnerabilityID", "?")
            pkg = vuln.get("PkgName", "?")
            ver = vuln.get("InstalledVersion", "?")
            sev = vuln.get("Severity", "")
            if sev not in ("HIGH", "CRITICAL"):
                continue
            status = vuln.get("Status", "")
            fixable = vuln.get("FixedVersion", "")
            if status == "unfixed":
                _log(
                    f"EXCEPTION: {sev} {vid} in {pkg} {ver} (no fix available)"
                )
                continue  # ADR 0026 exception
            if status == "wont-fix":
                continue  # explicitly accepted
            if fixable:
                has_fixable = True
                _log(
                    f"FIXABLE: {vid} in {pkg} {ver} (fix: {fixable})"
                )

    if has_fixable:
        return 1, "\n".join(_LOG_LINES)
    # Success path: include any EXCEPTION/no-fix lines for the test to assert on.
    return 0, "\n".join(_LOG_LINES) or "No fixable HIGH/CRITICAL vulnerabilities found."


def pass_(case: int, msg: str) -> None:
    print(f"  PASS  [{case}] {msg}")


def fail_(case: int, msg: str, expected: str, actual: str) -> None:
    global FAILED
    FAILED += 1
    print(f"  FAIL  [{case}] {msg} (expected {expected}, got {actual})")


def write_json(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def main() -> None:
    print("")
    print("=== Trivy JSON Parser — Regression Test Suite ===")
    print(f"Python: {sys.version.split()[0]}")
    print("")

    FIXTURES_DIR.mkdir(exist_ok=True)

    # ── Case 1: Valid clean report → exit 0 ─────────────────────────────────
    case = 1
    write_json(
        FIXTURES_DIR / f"case{case}.json",
        '{"Results": []}',
    )
    rc, _ = run_parser(FIXTURES_DIR / f"case{case}.json")
    if rc == 0:
        pass_(case, "valid clean report → exit 0")
    else:
        fail_(case, "valid clean report", "exit 0", f"exit {rc}")

    # ── Case 2: Fixable HIGH with FixedVersion → exit 1 ─────────────────────
    case = 2
    write_json(
        FIXTURES_DIR / f"case{case}.json",
        json.dumps({
            "Results": [{
                "Target": "app/lib.so",
                "Vulnerabilities": [{
                    "VulnerabilityID": "CVE-2021-99999",
                    "PkgName": "libfoo",
                    "InstalledVersion": "1.0.0",
                    "Severity": "HIGH",
                    "Status": "fixed",
                    "FixedVersion": "1.0.3",
                }],
            }]
        }),
    )
    rc, _ = run_parser(FIXTURES_DIR / f"case{case}.json")
    if rc == 1:
        pass_(case, "fixable HIGH → exit 1")
    else:
        fail_(case, "fixable HIGH", "exit 1", f"exit {rc}")

    # ── Case 3: Unfixed HIGH/CRITICAL → exit 0, exception logged ─────────────
    case = 3
    write_json(
        FIXTURES_DIR / f"case{case}.json",
        json.dumps({
            "Results": [{
                "Target": "app/lib.so",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2020-00001",
                        "PkgName": "libbar",
                        "InstalledVersion": "2.1.0",
                        "Severity": "HIGH",
                        "Status": "unfixed",
                    },
                    {
                        "VulnerabilityID": "CVE-2020-00002",
                        "PkgName": "libbaz",
                        "InstalledVersion": "3.0.0",
                        "Severity": "CRITICAL",
                        "Status": "unfixed",
                    },
                ],
            }]
        }),
    )
    rc, out = run_parser(FIXTURES_DIR / f"case{case}.json")
    if rc == 0 and "EXCEPTION" in out:
        pass_(case, "unfixed HIGH/CRIT → exit 0 + exception logged")
    elif rc == 0:
        fail_(case, "unfixed HIGH/CRIT — missing exception",
              "exit 0 + EXCEPTION", "exit 0 (no exception)")
    else:
        fail_(case, "unfixed HIGH/CRIT", "exit 0", f"exit {rc}")

    # ── Case 4: Malformed JSON → exit 1 ──────────────────────────────────────
    case = 4
    write_json(FIXTURES_DIR / f"case{case}.json", '{"Results": [}')
    rc, _ = run_parser(FIXTURES_DIR / f"case{case}.json")
    if rc == 1:
        pass_(case, "malformed JSON → exit 1")
    else:
        fail_(case, "malformed JSON", "exit 1", f"exit {rc}")

    # ── Case 5: Missing Results key → exit 1 ─────────────────────────────────
    case = 5
    write_json(
        FIXTURES_DIR / f"case{case}.json",
        '{"ArtifactName": "app", "ArtifactType": "filesystem"}',
    )
    rc, _ = run_parser(FIXTURES_DIR / f"case{case}.json")
    if rc == 1:
        pass_(case, "missing Results key → exit 1")
    else:
        fail_(case, "missing Results key", "exit 1", f"exit {rc}")

    # ── Case 6: Missing report file → exit 1 ──────────────────────────────────
    case = 6
    missing = FIXTURES_DIR / "case6-nonexistent.json"
    if missing.exists():
        missing.unlink()
    rc, _ = run_parser(missing)
    if rc == 1:
        pass_(case, "missing report file → exit 1")
    else:
        fail_(case, "missing report file", "exit 1", f"exit {rc}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("")
    print("=== Results ===")
    if FAILED == 0:
        print("All 6 cases PASSED.")
        sys.exit(0)
    else:
        print(f"{FAILED} case(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
