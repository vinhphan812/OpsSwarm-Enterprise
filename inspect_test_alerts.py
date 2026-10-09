import os

# Test file lines to inspect
test_files = {
    "tests/unit/test_github_origins.py": [97, 99, 101, 319, 321, 322, 335, 337, 339, 370, 372, 382, 384, 386, 515, 517, 524, 526, 535, 537],
    "tests/unit/test_github_client.py": [35, 37, 39],
}

for fpath, linenos in test_files.items():
    print(f"\n{'='*60}")
    print(f"FILE: {fpath}")
    print('='*60)
    with open(fpath, encoding='utf-8') as f:
        lines = f.readlines()
    for ln in linenos:
        start = max(1, ln - 1)
        end = min(len(lines), ln + 1)
        for i in range(start, end+1):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {i:4d} | {lines[i-1]}", end='')
        print()

# Also check ADR-028
print(f"\n{'='*60}")
print("FILE: docs/adr/ADR-028-*.md")
print('='*60)
import glob
for adr in sorted(glob.glob("docs/adr/ADR-028*")):
    print(f"\n--- {adr} ---")
    with open(adr, encoding='utf-8') as f:
        content = f.read()
    # show first 80 lines
    for i, line in enumerate(content.splitlines()[:80], 1):
        print(f"  {i:4d} | {line}")
