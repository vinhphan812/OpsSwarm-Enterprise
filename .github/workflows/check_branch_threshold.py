#!/usr/bin/env python3
"""Check coverage thresholds and fail if below minimum."""
import xml.etree.ElementTree as ET
import sys

tree = ET.parse("coverage.xml")
root = tree.getroot()

# Try root element attributes first (Cobertura XML format used by coverage.py)
branch_valid = root.get("branches-valid")
branch_covered = root.get("branches-covered")

if branch_valid and branch_covered:
    bv = int(branch_valid)
    bc = int(branch_covered)
    if bv > 0:
        pct = (bc / bv) * 100
        print(f"branch: {bc}/{bv} = {pct:.1f}%")
        if pct < 75:
            print(f"ERROR: branch coverage {pct:.1f}% < 75% threshold")
            sys.exit(1)
        print("PASS: branch coverage >= 75%")
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
    if pct < 75:
        print(f"ERROR: branch coverage {pct:.1f}% < 75% threshold")
        sys.exit(1)
    print("PASS: branch coverage >= 75%")
else:
    print("WARNING: no branch data found")
