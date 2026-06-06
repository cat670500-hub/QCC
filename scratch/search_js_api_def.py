import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
for i, entry in enumerate(entries):
    req = entry["request"]
    url = req["url"]
    resp = entry["response"]
    if "content" in resp and "text" in resp["content"]:
        text = resp["content"]["text"]
        # search for patterns like /exam/something
        for m in re.finditer(r'/exam/[A-Za-z0-9_]+', text):
            print(f"URL: {url}")
            print(f"  Match: {m.group(0)}")
