import json, re

LONG_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9+/=_-]{40,})(?![A-Za-z0-9])")
SAFE = {"change-me","changeme","example","placeholder","redacted","secret","token","xxx",
        "secret_key","secretkey","api_key","apikey","private_key","privatekey"}
HASHES = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$|^[0-9A-Fa-f]{128}$")
PLACEHOLDER_RE = re.compile(r"^(?:example|dummy|test)", re.IGNORECASE)

with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json") as f:
    raw = f.read()

# Simulate what the updated validate-artifacts does
def _normalise_bandit_for_scan(value):
    if not isinstance(value, dict):
        return value
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
            if not filtered_totals:
                filtered_totals = {}
            normalised["metrics"] = {"_totals": filtered_totals}
        else:
            normalised["metrics"] = {"_totals": totals} if isinstance(totals, dict) else {}
    return normalised

parsed = json.loads(raw)
normalised = _normalise_bandit_for_scan(parsed)
scan_text = json.dumps(normalised)

print(f"Original size: {len(raw)}")
print(f"Normalised size: {len(scan_text)}")

# Check long token matches
matches = list(LONG_TOKEN_PATTERN.finditer(scan_text))
print(f"Total long token matches: {len(matches)}")

for m in matches:
    cand = m.group(1)
    if cand.isdigit(): continue
    if HASHES.match(cand): continue
    norm = cand.strip("'\"<>[]{}()_-.").lower()
    if norm in SAFE: continue
    if PLACEHOLDER_RE.match(norm): continue
    
    start = max(0, m.start() - 60)
    end = min(len(scan_text), m.end() + 60)
    ctx = scan_text[start:end]
    print(f"\nFAIL: {cand[:60]!r}")
    print(f"  Context: {ctx!r}")
