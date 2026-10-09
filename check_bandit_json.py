import json
with open("C:/Users/Admin/AppData/Local/Temp/bandit-fixed.json") as f:
    d = json.load(f)

# Check all results for more_info and code content
print(f"Total results: {len(d.get('results', []))}")
print(f"Results with more_info: {sum(1 for r in d.get('results',[]) if 'more_info' in r)}")
print(f"Results with code: {sum(1 for r in d.get('results',[]) if 'code' in r)}")

# Check for nosec-related tokens in code snippets
nosec_in_code = [r for r in d.get('results', []) if 'code' in r and 'nosec' in r.get('code','').lower()]
print(f"Results with nosec in code: {len(nosec_in_code)}")

# Check if B104 results are present
b104 = [r for r in d.get('results', []) if r.get('test_id') == 'B104']
print(f"B104 results: {len(b104)}")

# Check the metrics section for file paths that might have long tokens
metrics = d.get('metrics', {})
print(f"\nMetrics files: {len(metrics)}")
for k, v in list(metrics.items())[:5]:
    print(f"  Key: {k!r}")
