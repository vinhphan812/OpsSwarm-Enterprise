import json

with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json") as f:
    raw = f.read()

# What _normalise_bandit_for_scan does
def _normalise_bandit_for_scan(value):
    normalised = dict(value)
    normalised["results"] = [
        {key: item for key, item in result.items() if key not in ("more_info", "code")}
        if isinstance(result, dict)
        else result
        for result in value.get("results", [])
    ]
    metrics = value.get("metrics")
    if isinstance(metrics, dict):
        totals = metrics.get("_totals")
        if isinstance(totals, dict):
            filtered_totals = {k: v for k, v in totals.items() if k != "more_info"}
            normalised["metrics"] = {"_totals": filtered_totals or {}}
        else:
            normalised["metrics"] = {"_totals": totals} if isinstance(totals, dict) else {}
    return normalised

parsed = json.loads(raw)
normalised = _normalise_bandit_for_scan(parsed)
norm_bytes = json.dumps(normalised).encode("utf-8")
norm_text = norm_bytes.decode("utf-8")

print(f"norm_bytes length: {len(norm_bytes)}")
print(f"norm_text first 200 chars: {norm_text[:200]!r}")

# Check if this can be JSON-parsed
try:
    reparsed = json.loads(norm_text)
    print(f"Re-parsed OK: {len(reparsed.get('results', []))} results")
except Exception as e:
    print(f"Re-parse FAILED: {e}")

# Search for b603 in norm_bytes
if b"b603" in norm_bytes:
    print("b603 FOUND in norm_bytes!")
    pos = norm_bytes.find(b"b603")
    print(norm_bytes[max(0,pos-50):pos+50])
else:
    print("b603 NOT in norm_bytes!")

# Check the actual path taken by validate()
# For bandit.json: scan_bytes = norm_bytes, text = norm_text
# Then _validate_json(path, text) - would this work?
print("\nChecking _validate_json call with norm_text:")
try:
    json.loads(norm_text)
    print("JSON loads OK")
except Exception as e:
    print(f"JSON loads FAILED: {e}")
