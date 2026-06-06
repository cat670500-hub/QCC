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
        
        # Let's search for "CheckIn" or "CheckInBack" or "/exam/"
        for term in ["CheckIn", "CheckInBack", "/exam/"]:
            if term in text:
                print(f"\nTerm '{term}' found in: {url}")
                for m in re.finditer(re.escape(term), text):
                    idx = m.start()
                    print(f"  Match: {text[max(0, idx-80):min(len(text), idx+100)]}")
