"""Find which bandit finding causes validate-artifacts.py to reject."""
import json, re

with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    raw = f.read()

LONG_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9+/=_-]{40,})(?![A-Za-z0-9])")
SAFE = {"change-me","changeme","example","placeholder","redacted","secret","token","xxx",
        "secret_key","secretkey","api_key","apikey","private_key","privatekey"}
HASHES = re.compile(r"^[0-9A-Fa-f]{40}$|^[0-9A-Fa-f]{64}$|^[0-9A-Fa-f]{128}$")
PLACEHOLDER_RE = re.compile(r"^(?:example|dummy|test)", re.IGNORECASE)

# Check all text in JSON for the pattern
print("Searching full JSON text for long tokens...")
matches = list(LONG_TOKEN_PATTERN.finditer(raw))
print(f"Total long token matches: {len(matches)}")
for m in matches:
    cand = m.group(1)
    if cand.isdigit(): continue
    if HASHES.match(cand): continue
    norm = cand.strip("'\"<>[]{}()_-.").lower()
    if norm in SAFE: continue
    if PLACEHOLDER_RE.match(norm): continue
    start = max(0, m.start() - 30)
    end = min(len(raw), m.end() + 30)
    print(f"SUSPECT at pos {m.start()}: {raw[start:end]!r}")
