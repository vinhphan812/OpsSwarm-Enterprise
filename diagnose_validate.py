"""Debug validate-artifacts.py failure on bandit-fixed.json."""
import json, re

LONG_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9+/=_-]{40,})(?![A-Za-z0-9])")
SAFE = {"change-me","changeme","example","placeholder","redacted","secret","token","xxx",
        "secret_key","secretkey","api_key","apikey","private_key","privatekey"}
HASHES = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$|^[0-9A-Fa-f]{128}$")
PLACEHOLDER_RE = re.compile(r"^(?:example|dummy|test)", re.IGNORECASE)

# What _validate_text receives after _normalise_bandit_for_scan
with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    parsed = json.load(f)

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
scan_bytes = json.dumps(normalised).encode("utf-8")
text = scan_bytes.decode("utf-8")

print(f"Text length: {len(text)}")
print(f"Long token matches in SCANNED text: {len(list(LONG_TOKEN_PATTERN.finditer(text)))}")

# Now find which ones fail
fail_count = 0
for m in LONG_TOKEN_PATTERN.finditer(text):
    cand = m.group(1)
    if cand.isdigit(): continue
    if HASHES.match(cand): continue
    norm = cand.strip("'\"<>[]{}()_-.").lower()
    if norm in SAFE: continue
    if PLACEHOLDER_RE.match(norm): continue
    
    # Check if candidate is in the normalised bandit JSON
    # The normalised JSON has "more_info" stripped from results
    # Find context around the match
    start = max(0, m.start() - 60)
    end = min(len(text), m.end() + 60)
    context = text[start:end]
    
    # Is this more_info from results?
    in_more_info = "more_info" in context
    in_code = '"code":' in context
    
    fail_count += 1
    print(f"\nSUSPECT {fail_count}: {cand[:60]!r}")
    print(f"  In more_info context: {in_more_info}")
    print(f"  In code context: {in_code}")
    print(f"  Context: {context!r}")

print(f"\nTotal failing tokens: {fail_count}")
