import json, re

LONG_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9+/=_-]{40,})(?![A-Za-z0-9])")
SAFE = {"change-me","changeme","example","placeholder","redacted","secret","token","xxx",
        "secret_key","secretkey","api_key","apikey","private_key","privatekey"}
HASHES = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$|^[0-9A-Fa-f]{128}$")
PLACEHOLDER_RE = re.compile(r"^(?:example|dummy|test)", re.IGNORECASE)

with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    parsed = json.load(f)

# Simulate what _normalise_bandit_for_scan does
def _normalise_bandit_for_scan(value):
    if not isinstance(value, dict):
        return value
    normalised = dict(value)
    normalised["results"] = [
        {key: item for key, item in result.items() if key != "more_info"}
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

normalised = _normalise_bandit_for_scan(parsed)
scan_text = json.dumps(normalised)

# Check metrics keys
print("Metrics keys (first 5):")
for i, k in enumerate(list(normalised.get("metrics", {}).keys())[:5]):
    print(f"  {k!r}")

# Now scan for long tokens in the full normalised text
print("\nLong token scan of normalised JSON:")
found = 0
for m in LONG_TOKEN_PATTERN.finditer(scan_text):
    cand = m.group(1)
    if cand.isdigit(): continue
    if HASHES.match(cand): continue
    norm = cand.strip("'\"<>[]{}()_-.").lower()
    if norm in SAFE: continue
    if PLACEHOLDER_RE.match(norm): continue
    
    start = max(0, m.start() - 40)
    end = min(len(scan_text), m.end() + 40)
    ctx = scan_text[start:end]
    
    # Check context
    is_metric_key = "\\" in ctx or '":"' in ctx
    is_code = '"code"' in ctx
    is_itext = '"issue_text"' in ctx
    is_link = '"link"' in ctx
    
    found += 1
    print(f"\n  [{found}] Token: {cand[:60]!r}")
    print(f"    is_metric_key={is_metric_key}, is_code={is_code}, is_itext={is_itext}, is_link={is_link}")
    print(f"    Context: {ctx!r}")

print(f"\nTotal failing: {found}")
