import json
with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    d = json.load(f)

# Check if more_info is still in results
has_more_info = any("more_info" in r for r in d.get("results", []))
print(f"Results with more_info: {has_more_info}")

# Find B104 findings
b104_findings = [r for r in d.get("results", []) if r.get("test_id") == "B104"]
print(f"B104 findings count: {len(b104_findings)}")
for r in b104_findings:
    print(f"  File: {r.get('filename')}:{r.get('line_number')} | has more_info: {'more_info' in r} | has code: {bool(r.get('code'))}")
    if "code" in r:
        print(f"  Code snippet: {r['code'][:200]!r}")

# Check metrics for more_info
metrics = d.get("metrics", {})
print(f"\nMetrics keys: {list(metrics.keys())[:10]}")
for fname, fdata in list(metrics.items())[:3]:
    print(f"  {fname}: has more_info: {'more_info' in fdata}")
