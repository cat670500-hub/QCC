import json

with open("tprisweb.shh.org.tw.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

entries = har_data["log"]["entries"]
js_urls = []
for entry in entries:
    url = entry["request"]["url"]
    if ".js" in url:
        js_urls.append(url)

print("All JS URLs in HAR file:")
for url in sorted(set(js_urls)):
    print(f"  {url}")
