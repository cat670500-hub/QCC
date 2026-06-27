import requests
import time
import subprocess
import os
import sys

print("啟動伺服器...")
proc = subprocess.Popen([sys.executable, "app.py"])

try:
    time.sleep(3) # 等待伺服器啟動
    
    print("測試 1: 檢查伺服器首頁是否存活")
    res = requests.get("https://127.0.0.1:5000", verify=False)
    if res.status_code == 200:
        print("[OK] 首頁讀取成功")
    else:
        print(f"[FAIL] 首頁讀取失敗 (狀態碼: {res.status_code})")
        
    print("測試 2: 測試語音辨識 API")
    data = {
        "text": "恩逼吸洞么",
        "phone_number": "0912345678"
    }
    res = requests.post("https://127.0.0.1:5000/api/voice_dispatch", json=data, verify=False)
    
    if res.status_code == 200:
        print("[OK] 語音 API 測試成功，回應: ", res.json())
    else:
        print(f"[FAIL] 語音 API 測試失敗 (狀態碼: {res.status_code})")
        
finally:
    print("關閉伺服器...")
    proc.terminate()
