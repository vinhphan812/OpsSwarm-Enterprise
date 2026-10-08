import json, re

with open("C:/Users/Admin/AppData/Local/Temp/bandit-final.json") as f:
    raw = f.read()

# Check for multiple JSON objects
count = 0
pos = 0
while True:
    try:
        json.loads(raw[pos:])
        count += 1
        print(f"JSON object #{count} starts at pos {pos}, length {len(raw) - pos}")
        break
    except:
        pass
    
    # Find the next opening brace
    next_braces = [raw.find('{', pos+1), raw.find('[', pos+1)]
    next_braces = [p for p in next_braces if p >= 0]
    if not next_braces:
        print("No more JSON objects found")
        break
    pos = min(next_braces)
    count += 1
    if count > 5:
        print("Too many objects, stopping")
        break

# Check for trailing data
print(f"\nTotal raw size: {len(raw)}")
stripped = raw.rstrip()
if stripped != raw:
    print(f"Trailing whitespace: {len(raw) - len(stripped)} bytes")
    print(f"Trailing: {stripped[-50:]!r}")

# Check if there are embedded JSON strings in the JSON
print("\nSearching for 'b603' in raw (excluding more_info):")
pos = 0
while True:
    pos = raw.find("b603", pos)
    if pos < 0:
        print("No more occurrences")
        break
    start = max(0, pos - 50)
    end = min(len(raw), pos + 30)
    in_more_info = "more_info" in raw[max(0,pos-200):pos+200]
    print(f"  pos {pos}: more_info={in_more_info}: {raw[start:end]!r}")
    pos += 1
