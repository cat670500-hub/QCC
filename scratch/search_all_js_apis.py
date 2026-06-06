import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
for entry in entries:
    url = entry["request"]["url"]
    if not url.endswith(".js"):
        continue
    resp = entry["response"]
    if "content" in resp and "text" in resp["content"]:
        text = resp["content"]["text"]
        matches = list(re.finditer(r'CheckIn', text, re.IGNORECASE))
        if matches:
            print(f"\nFound in: {url}")
            for m in matches:
                idx = m.start()
                start = max(0, idx - 100)
                end = min(len(text), idx + 100)
                print(f"  Match: {text[start:end]}")
