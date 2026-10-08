import json, re

with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json") as f:
    raw = f.read()

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

print(f"Normalised size: {len(norm_text)}")

# Search for the specific token
TOKEN = "4/plugins/b603"
pos = norm_text.find(TOKEN)
if pos >= 0:
    print(f"FOUND '{TOKEN}' at pos {pos}")
    start = max(0, pos - 100)
    end = min(len(norm_text), pos + len(TOKEN) + 50)
    print(norm_text[start:end])
else:
    print(f"NOT found in normalised. Checking full normalised JSON for substrings...")
    # Search for parts of the token
    for i in range(len(TOKEN) - 10):
        part = TOKEN[i:i+15]
        if part in norm_text:
            pos2 = norm_text.find(part)
            start = max(0, pos2 - 50)
            end = min(len(norm_text), pos2 + len(part) + 50)
            print(f"Part '{part}' found at {pos2}: {norm_text[start:end]!r}")

# Check if 'b603' appears
if "b603" in norm_text:
    print("\n'b603' found in normalised!")
    pos = norm_text.find("b603")
    start = max(0, pos - 80)
    end = min(len(norm_text), pos + 50)
    print(norm_text[start:end])
else:
    print("\n'b603' NOT in normalised!")

# Check all result keys in normalised
print("\nSample normalised result keys:")
for r in normalised.get("results", [])[:3]:
    print(f"  {list(r.keys())}")
