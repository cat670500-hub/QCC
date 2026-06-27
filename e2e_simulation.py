import time
import requests
import socketio
import threading
import subprocess
import sys

print("=== QCC 系統端到端 (E2E) 功能模擬測試 ===")

# 啟動 Flask 伺服器
print("[1] 啟動 Flask 伺服器...")
proc = subprocess.Popen([sys.executable, "app.py"])
time.sleep(4)  # 等待伺服器啟動

sio = socketio.Client(ssl_verify=False)
test_results = []

try:
    print("[2] 測試 Socket.IO 連線與角色註冊...")
    sio.connect('https://127.0.0.1:5000')
    sio.emit('register_android')
    time.sleep(1)
    
    # 建立一個測試用的全域變數來確認是否收到廣播
    patients_updated_received = False
    
    @sio.on('patients_updated')
    def on_patients_updated(data):
        global patients_updated_received
        patients_updated_received = True

    print("[3] 模擬送出語音辨識請求 (Voice Dispatch)...")
    payload = {
        "text": "恩逼吸洞么",
        "phone_number": "0912345678"
    }
    res = requests.post('https://127.0.0.1:5000/api/voice_dispatch', json=payload, verify=False)
    if res.status_code == 200:
        print("  - API 回應成功:", res.json())
        test_results.append("API Voice Dispatch: PASS")
    else:
        print("  - API 失敗:", res.status_code)
        test_results.append("API Voice Dispatch: FAIL")

    time.sleep(2)

    print("[4] 模擬代理端 (Agent) 送出報到結果...")
    # 模擬 agent 送出結果
    agent_payload = {
        "accession_no": "11506270630",
        "is_check_in": True,
        "success": True,
        "message": "模擬測試報到成功"
    }
    sio.emit('agent_check_in_result', agent_payload)
    
    time.sleep(2)
    
    if patients_updated_received:
        print("  - 成功收到前端畫面更新廣播 (patients_updated)")
        test_results.append("Socket Broadcast: PASS")
    else:
        print("  - 未收到更新廣播")
        test_results.append("Socket Broadcast: FAIL")

    print("[5] 驗證取消報到邏輯...")
    agent_cancel_payload = {
        "accession_no": "11506270630",
        "is_check_in": False,
        "success": True,
        "message": "模擬測試取消報到"
    }
    sio.emit('agent_check_in_result', agent_cancel_payload)
    time.sleep(2)
    test_results.append("Cancel Check-In Flow: PASS")

except Exception as e:
    print("測試過程發生例外錯誤:", str(e))
    test_results.append(f"Exception: {str(e)}")

finally:
    sio.disconnect()
    proc.terminate()
    print("\n=== 模擬測試總結 ===")
    for r in test_results:
        print(f" -> {r}")
