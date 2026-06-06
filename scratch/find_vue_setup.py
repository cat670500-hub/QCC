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

# Find the definition of qe(n,p) or doCheckIn
target_idx = js_content.find('doCheckIn');
if target_idx != -1:
    print("Found 'doCheckIn' at index:", target_idx)
    # Print 1500 chars before target_idx to find the start of the component/setup
    print("\n--- Context before doCheckIn ---")
    start = max(0, target_idx - 1500)
    print(js_content[start:target_idx + 500])
