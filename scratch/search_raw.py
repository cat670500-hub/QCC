import json
import re

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
for i, entry in enumerate(entries):
    req = entry["request"]
    resp = entry["response"]
    req_str = json.dumps(req)
    resp_str = json.dumps(resp)
    
    for term in ["CheckIn", "checkIn", "check_in", "Check_In"]:
        if term in req_str or term in resp_str:
            print(f"Entry {i}: {req['method']} {req['url']}")
            # Find matching context
            for m in re.finditer(rf'.{{0,50}}{term}.{{0,50}}', req_str + resp_str):
                print(f"  Match: {m.group(0)}")
            break
