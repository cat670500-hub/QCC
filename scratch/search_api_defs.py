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

# Let's search for assignments like " U=" or "const U=" or "function U(" or "U = "
# Let's search for any place where U is defined or assigned
# We can also print the list of imports and destructuring in the setup function
setup_match = re.search(r'setup\(S,\{emit:q\}\)\{const', js_content)
if setup_match:
    start = setup_match.start()
    print("Setup function start:")
    print(js_content[start:start+400])

print("\nOccurrences of 'U(' in the file:")
for m in re.finditer(r'[^A-Za-z0-9_]U\(', js_content):
    idx = m.start()
    print(js_content[idx-30:idx+80])

print("\nOccurrences of '_(' in the file:")
for m in re.finditer(r'[^A-Za-z0-9_]_\(', js_content):
    idx = m.start()
    print(js_content[idx-30:idx+80])
