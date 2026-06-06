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

# Find all import statements in the JS content
for m in re.finditer(r'import\s*\{[^}]*\}\s*from\s*["\'][^"\']*["\']|import\s*["\'][^"\']*["\']', js_content):
    print(m.group(0))
