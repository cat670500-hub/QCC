import json

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
print(f"Total entries: {len(entries)}")

endpoints = {}
for entry in entries:
    req = entry["request"]
    url = req["url"]
    method = req["method"]
    endpoints[(method, url)] = endpoints.get((method, url), 0) + 1

for (method, url), count in sorted(endpoints.items(), key=lambda x: x[0][1]):
    if "api" in url.lower() or "exam" in url.lower() or "check" in url.lower() or "login" in url.lower():
        print(f"{method} {url} (Count: {count})")
