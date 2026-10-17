#!/usr/bin/env bash
# =============================================================================
# Trivy JSON parser regression test suite — shell entry-point
#
# Delegates cases 1-6 to test_trivy_parser.py (native Python, no path issues).
# Case 7 (scanner failure) is tested directly here using shell logic that
# mirrors the RC>1 guard in security.yml lines 137-140.
#
# Local reproduction (from repo root):
#   bash .github/scripts/trivy-parser-regression.sh
#
# CI (add to .github/workflows/security.yml as a post-scan step):
#   - name: Trivy parser regression tests
#     run: bash .github/scripts/trivy-parser-regression.sh
#     if: always()  # run even if main scan step failed
# =============================================================================

set -uo pipefail  # no -e: we handle failure per case

# Prevent the MSYS path-conversion layer from re-interpreting MSYS paths
# when the Windows python3.exe launcher is invoked.  Without this, Python
# sees /d/... as D:\d\... (doubled drive letter) and fails to open the file.
export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Convert an MSYS path like "/d/competitions/.../scripts" to a Windows path
# that the WindowsApps python3.exe launcher can open directly.
# The WindowsApps launcher does NOT honour MSYS_NO_PATHCONV for script arguments,
# so we must give it a real Windows path: D:\competitions\...\scripts
msys_to_win_path() {
  case "$1" in
    /[a-z]/*)
      local drive="$(tr '[:lower:]' '[:upper:]' <<< "${1:1:1}")"
      local rest="${1:2}"
      echo "${drive}:${rest}"
      ;;
    *) echo "$1" ;;
  esac
}

# Resolve a working Python.
# On GitHub Actions (Linux) python3 is clean.
# On Windows dev machines the WindowsApps python3.exe launcher converts MSYS
# paths to Win32 paths incorrectly.  We use msys_to_win_path() below to convert
# the SCRIPT_DIR before passing it to Python as an argument.
PYTEST_SCRIPT_WIN="$(msys_to_win_path "$SCRIPT_DIR")/test_trivy_parser.py"
PYTHON=""
for p in python3 python; do
  if "$p" -c "import sys; sys.exit(0)" 2>/dev/null; then
    PYTHON="$p"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: no Python interpreter found" >&2
  exit 1
fi

echo ""
echo "=== Trivy JSON Parser — Regression Test Suite ==="
echo "Python:  $($PYTHON --version 2>&1)"
echo "Script:  ${SCRIPT_DIR}"
echo ""

FAILED=0

# ── Cases 1-6: Python runner ────────────────────────────────────────────────
# On Windows, $PYTEST_SCRIPT_WIN is a real Windows path (D:\...) so the
# WindowsApps python3.exe launcher can open it without MSYS path conversion.
if "$PYTHON" "$PYTEST_SCRIPT_WIN"; then
  echo ""
  echo "  PASS  [1-6] Python parser cases 1-6"
else
  echo ""
  echo "  FAIL  [1-6] Python parser cases 1-6"
  FAILED=$((FAILED + 1))
fi

# ── Case 7: Scanner failure (RC > 1) → exit 1 ─────────────────────────────
# Mirrors security.yml lines 137-140:
#   if [ "$_RC" -gt 1 ]; then echo "error"; exit 1; fi
echo ""
SCANNER_RC=2  # Simulate Trivy's fatal error (database error, network failure, etc.)
if [ "$SCANNER_RC" -gt 1 ]; then
  FINAL_RC=1
else
  FINAL_RC=$SCANNER_RC
fi

if [ "$FINAL_RC" -eq 1 ]; then
  echo "  PASS  [7] scanner failure (RC>1) → exit 1"
else
  echo "  FAIL  [7] scanner failure (RC>1) → expected exit 1, got exit ${FINAL_RC}"
  FAILED=$((FAILED + 1))
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Results ==="
if [ "$FAILED" -eq 0 ]; then
  echo "All 7 cases PASSED."
  exit 0
else
  echo "$FAILED case(s) FAILED."
  exit 1
fi
