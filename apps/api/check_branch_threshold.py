#!/usr/bin/env python3
"""Check coverage thresholds and fail if below minimum.

This script is part of the Day-0 Cloud Run deployment PR (#111).
It validates branch coverage meets minimum thresholds before CI passes.
"""
import xml.etree.ElementTree as ET
import sys

tree = ET.parse("coverage.xml")
root = tree.getroot()

# The library (backbone.py, backbone_gcp.py) contains exception-handling,
# validation, and error-path branches that are exercised by the unit tests.
# This script enforces a minimum branch coverage of 70% so uncovered branches
# are tracked but do not block CI while the test suite matures.
_MIN_BRANCH_PCT = 70.0

# Try root element attributes first (Cobertura XML format used by coverage.py)
branch_valid = root.get("branches-valid")
branch_covered = root.get("branches-covered")

if branch_valid and branch_covered:
    bv = int(branch_valid)
    bc = int(branch_covered)
    if bv > 0:
        pct = (bc / bv) * 100
        print(f"branch: {bc}/{bv} = {pct:.1f}%")
        if pct < _MIN_BRANCH_PCT:
            print(f"ERROR: branch coverage {pct:.1f}% < {_MIN_BRANCH_PCT:.0f}% threshold")
            sys.exit(1)
        print(f"PASS: branch coverage >= {_MIN_BRANCH_PCT:.0f}%")
        sys.exit(0)

# Fallback: counter elements (some coverage.py XML variants)
found = hit = 0
for counter in root.findall(".//counter"):
    if counter.get("type") == "branch":
        found = int(counter.get("found", 0))
        hit = int(counter.get("hit", 0))
if found > 0:
    pct = (hit / found) * 100
    print(f"branch: {hit}/{found} = {pct:.1f}%")
    if pct < _MIN_BRANCH_PCT:
        print(f"ERROR: branch coverage {pct:.1f}% < {_MIN_BRANCH_PCT:.0f}% threshold")
        sys.exit(1)
    print(f"PASS: branch coverage >= {_MIN_BRANCH_PCT:.0f}%")
else:
    print("WARNING: no branch data found")
