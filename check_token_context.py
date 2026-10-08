import json, re

with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    d = json.load(f)

LONG_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9+/=_-]{40,})(?![A-Za-z0-9])")

# Find all results and check their code/issue_text for the more_info URL
for r in d.get("results", []):
    code = r.get("code","")
    itext = r.get("issue_text","")
    fname = r.get("filename","")
    ln = r.get("line_number","")
    tid = r.get("test_id","")
    
    combined = code + "\n" + itext
    matches = list(LONG_TOKEN_PATTERN.finditer(combined))
    if matches:
        print(f"\n{fname}:{ln} [{tid}]")
        for m in matches:
            cand = m.group(1)
            start = max(0, m.start()-5)
            end = min(len(combined), m.end()+5)
            print(f"  Token: {cand[:60]!r}")
            print(f"  Context: {combined[start:end]!r}")
