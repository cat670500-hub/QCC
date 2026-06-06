import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
js_content = ""
for entry in entries:
    if "index-CILWCOUb.js" in entry["request"]["url"]:
        js_content = entry["response"]["content"]["text"]
        break

if not js_content:
    print("Could not find index-CILWCOUb.js in HAR file!")
    # Let's list all JS files in HAR
    print("Available JS files in HAR:")
    for entry in entries:
        url = entry["request"]["url"]
        if url.endswith(".js"):
            print(f"  {url}")
    exit(1)

print("Found index-CILWCOUb.js, size:", len(js_content))

# Look for CheckIn
matches = [m.start() for m in re.finditer(r'CheckIn', js_content, re.IGNORECASE)]
print(f"Found {len(matches)} occurrences of 'CheckIn' (case-insensitive)")
for idx, start_idx in enumerate(matches):
    start = max(0, start_idx - 100)
    end = min(len(js_content), start_idx + 100)
    print(f"\n--- Match {idx+1} ---")
    print(js_content[start:end])
