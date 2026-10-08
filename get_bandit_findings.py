import json

with open('/tmp/bandit-pr79-v194.json') as f:
    d = json.load(f)
results = d.get('results', [])
print(f"Total findings: {len(results)}")
for r in results:
    print(f"[{r.get('issue_severity')}] {r.get('filename')}:{r.get('line')} | {r.get('test_id')} | {r.get('issue_text','')[:200]}")
    print("  Keys:", list(r.keys()))
