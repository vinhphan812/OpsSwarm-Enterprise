import json, re, sys
sys.path.insert(0, "D:/competitions/Minto 2026/OpsSwarm-Enterprise-wt-pr79/scripts")

# Read the actual file
with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json", "rb") as f:
    raw = f.read()

# Read the actual validate-artifacts.py
from pathlib import Path
import validate_artifacts as va

# Simulate the validate() path for bandit.json
path = Path("C:/Users/Admin/AppData/Local/Temp/bandit-final.json")
print(f"path.name: {path.name!r}")
print(f"path.suffix.lower(): {path.suffix.lower()!r}")
print(f"Is .json: {path.suffix.lower() == '.json'}")

# Simulate _validate_json
parsed, sbom_known_tokens = va._validate_json(path, raw.decode("utf-8"))
print(f"sbom_known_tokens: {sbom_known_tokens}")

# Simulate _normalise_bandit_for_scan
norm_bytes = json.dumps(va._normalise_bandit_for_scan(parsed)).encode("utf-8")
print(f"norm_bytes length: {len(norm_bytes)}")

# Check if b603 is in norm_bytes
if b"b603" in norm_bytes:
    print("b603 IN norm_bytes!")
else:
    print("b603 NOT in norm_bytes!")

# What _validate_text does
norm_text = norm_bytes.decode("utf-8")
print(f"\nCalling _scan_credentials with norm_text (len={len(norm_text)})...")
try:
    va._scan_credentials(norm_text, sbom_known_tokens)
    print("PASSED!")
except va.ValidationError as e:
    print(f"FAILED: {e}")
