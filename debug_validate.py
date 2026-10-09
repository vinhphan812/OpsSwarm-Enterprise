"""Debug validate-artifacts directly."""
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
    
    # Now let's debug which exact check failed
    import json
    raw = path.read_bytes()
    print(f"\nRaw bytes length: {len(raw)}")
    
    # Check 1: parse
    try:
        parsed = json.loads(raw.decode("utf-8"))
        print("JSON parse: OK")
    except Exception as e:
        print(f"JSON parse: FAILED - {e}")
        return
    
    # Check 2: bandit policy
    try:
        va._validate_bandit_policy(parsed)
        print("Bandit policy: OK")
    except Exception as e:
        print(f"Bandit policy: FAILED - {e}")
    
    # Check 3: normalize
    normalised = va._normalise_bandit_for_scan(parsed)
    scan_bytes = json.dumps(normalised).encode("utf-8")
    print(f"Normalized scan bytes length: {len(scan_bytes)}")
    
    # Check 4: credentials on raw
    try:
        va._scan_credentials(raw.decode("utf-8"), None)
        print("Raw credentials scan: OK")
    except Exception as e:
        print(f"Raw credentials scan: FAILED - {e}")
    
    # Check 5: credentials on normalized
    try:
        va._scan_credentials(scan_bytes.decode("utf-8"), None)
        print("Normalized credentials scan: OK")
    except Exception as e:
        print(f"Normalized credentials scan: FAILED - {e}")
