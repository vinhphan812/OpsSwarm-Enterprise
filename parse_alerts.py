import json, sys

with open(r"C:\Users\Admin\AppData\Local\hermes\profiles\dev-qa\cache\terminal-output\out-1791192588-40308-7490.log") as f:
    raw = f.readline().strip()

data = json.loads(raw)
alerts = sorted(data, key=lambda x: x['number'])
open_alerts = [a for a in alerts if a['state'] == 'open']
fixed_alerts = [a for a in alerts if a['state'] == 'fixed']
print(f"Total: {len(alerts)}, Open: {len(open_alerts)}, Fixed: {len(fixed_alerts)}")
print()
print("=== OPEN ALERTS ===")
for a in open_alerts:
    loc = a['most_recent_instance']['location']
    msg = a['most_recent_instance']['message']['text']
    cls = a['most_recent_instance'].get('classifications', [])
    print(f"#{a['number']} | {a['rule']['id']} | {loc['path']}:{loc['start_line']} | cls={cls} | {msg}")

print()
print("=== FIXED ALERTS ===")
for a in fixed_alerts:
    loc = a['most_recent_instance']['location']
    print(f"#{a['number']} | {a['rule']['id']} | {loc['path']}:{loc['start_line']} | fixed={a['fixed_at']}")
