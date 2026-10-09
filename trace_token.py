import json, re

TOKEN_TO_FIND = "4/plugins/b603_subprocess_without_shell_equals_true"

with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json") as f:
    raw = f.read()

# Find the position in raw
pos = raw.find(TOKEN_TO_FIND)
if pos >= 0:
    start = max(0, pos - 100)
    end = min(len(raw), pos + len(TOKEN_TO_FIND) + 10)
    print(f"Found in ORIGINAL at pos {pos}:")
    print(raw[start:end])
else:
    print("Not found in original!")

# Check normalised output
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
norm_text = json.dumps(normalised)
pos2 = norm_text.find(TOKEN_TO_FIND)
if pos2 >= 0:
    start = max(0, pos2 - 100)
    end = min(len(norm_text), pos2 + len(TOKEN_TO_FIND) + 10)
    print(f"\nFound in NORMALISED at pos {pos2}:")
    print(norm_text[start:end])
else:
    print("\nNot found in normalised!")
    # Find where the token IS in normalised
    if TOKEN_TO_FIND[:20] in norm_text:
        pos3 = norm_text.find(TOKEN_TO_FIND[:20])
        start = max(0, pos3 - 20)
        end = min(len(norm_text), pos3 + len(TOKEN_TO_FIND[:20]) + 10)
        print(f"But substring found: {norm_text[start:end]}")
