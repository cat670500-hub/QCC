import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
js_content = ""
for entry in entries:
    if "api-DobS6bk4.js" in entry["request"]["url"]:
        js_content = entry["response"]["content"]["text"]
        break

if not js_content:
    print("Could not find api-DobS6bk4.js in HAR file!")
    exit(1)

print("Found api-DobS6bk4.js, size:", len(js_content))

# Print all HTTP request-like patterns or words
# e.g., urls, methods, or api prefixes
# Let's print the first 2000 characters and search for strings in quotes
print("First 1500 chars of api JS:")
print(js_content[:1500])

print("\nOccurrences of 'exam' in api JS:")
for m in re.finditer(r'exam', js_content, re.IGNORECASE):
    idx = m.start()
    print(js_content[idx-30:idx+80])
