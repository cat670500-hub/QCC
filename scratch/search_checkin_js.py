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
        if "CheckIn" in text:
            print(f"\nFound in: {url}")
            for m in re.finditer(r'.{0,100}CheckIn.{0,100}', text):
                print(f"  Match: {m.group(0)}")
