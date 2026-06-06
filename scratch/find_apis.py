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
        # Find matches of "/CheckIn" or similar in the content
        matches = re.findall(r'/[A-Za-z0-9_/]+CheckIn[A-Za-z0-9_]*', text)
        if matches:
            print(f"Found in response of: {url}")
            print(f"  Matches: {matches}")
