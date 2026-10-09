import sys
sys.path.insert(0, "D:/competitions/Minto 2026/OpsSwarm-Enterprise-wt-pr79/scripts")
from pathlib import Path
import validate_artifacts as va
path = Path("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json")
try:
    va.validate(path)
    print("PASSED")
except va.ValidationError as e:
    print(f"FAILED: {e}")
    import json
    raw = path.read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    try:
        va._validate_bandit_policy(parsed)
        print("Bandit policy: OK")
    except va.ValidationError as e2:
        print(f"Bandit policy FAILED: {e2}")
    normalised = va._normalise_bandit_for_scan(parsed)
    scan_bytes = json.dumps(normalised).encode("utf-8")
    print(f"Normalized bytes: {len(scan_bytes)}")
    try:
        va._scan_credentials(raw.decode("utf-8"), None)
        print("Raw scan: OK")
    except va.ValidationError as e2:
        print(f"Raw scan FAILED: {e2}")
    try:
        result = va._scan_credentials(scan_bytes.decode("utf-8"), None)
        print(f"Normalized scan: OK, returned {result!r}")
    except va.ValidationError as e2:
        print(f"Normalized scan FAILED: {e2}")
