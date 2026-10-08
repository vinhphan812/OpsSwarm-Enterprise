import os

files_lines = {
    "opsswarm/github_client.py": [340, 346, 350, 356, 360, 368, 375],
    "opsswarm/orchestrator.py": [374, 379, 750, 754, 757, 761, 763, 767],
}

for fpath, linenos in files_lines.items():
    print(f"\n{'='*60}")
    print(f"FILE: {fpath}")
    print('='*60)
    with open(fpath, encoding='utf-8') as f:
        lines = f.readlines()
    for ln in linenos:
        start = max(1, ln - 2)
        end = min(len(lines), ln + 5)
        for i in range(start, end+1):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {i:4d} | {lines[i-1]}", end='')
        print()
