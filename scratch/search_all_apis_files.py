import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
for entry in entries:
    url = entry["request"]["url"]
    if "assets/apis-" not in url:
        continue
    resp = entry["response"]
    if "content" in resp and "text" in resp["content"]:
        text = resp["content"]["text"]
        print(f"\nChecking apis file: {url}, size: {len(text)}")
        
        # Search for any string like "/exam/" or CheckIn or similar
        for term in ["CheckIn", "CheckInBack", "exam/"]:
            if term in text:
                print(f"  Found '{term}':")
                for m in re.finditer(re.escape(term), text):
                    idx = m.start()
                    print(f"    Match: {text[max(0, idx-80):min(len(text), idx+100)]}")
