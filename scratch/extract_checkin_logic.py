import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
js_content = ""
for entry in entries:
    if "index-BOAFHmF2.js" in entry["request"]["url"]:
        js_content = entry["response"]["content"]["text"]
        break

if not js_content:
    print("Could not find index-BOAFHmF2.js in HAR file!")
    exit(1)

print("Found index JS file. Size:", len(js_content))

# Look for CheckIn definitions, endpoints, etc.
# Commonly APIs are defined like function checkIn(data) or checkIn: function(...) or in axios call
# Let's search for "CheckIn" and print the context (200 characters before and after)
matches = [m.start() for m in re.finditer(r'CheckIn', js_content)]
print(f"Found {len(matches)} occurrences of 'CheckIn'")
for idx, start_idx in enumerate(matches):
    start = max(0, start_idx - 150)
    end = min(len(js_content), start_idx + 150)
    print(f"\n--- Match {idx+1} ---")
    print(js_content[start:end])
