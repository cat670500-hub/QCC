import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    print("Sending request to https://127.0.0.1:5000/login ...")
    r = requests.get("https://127.0.0.1:5000/login", verify=False, timeout=5)
    print("Response status:", r.status_code)
    print("Response text length:", len(r.text))
except Exception as e:
    import traceback
    print("Error occurred:")
    traceback.print_exc()
