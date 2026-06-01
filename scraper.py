import os
import sys
import json
import time
import requests

# Flask 系統的網址
FLASK_API_URL = "http://127.0.0.1:5000/api/update_patients"

def load_dotenv():
    """尋找並載入 .env 設定檔中的金鑰資訊"""
    possible_paths = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        possible_paths.append(os.path.join(exe_dir, '.env'))
    
    possible_paths.append(os.path.join(os.getcwd(), '.env'))
    possible_paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            os.environ[k.strip()] = v.strip()
                break
            except Exception as e:
                print(f"[警告] 讀取設定檔 {path} 時發生錯誤: {e}")

# 載入金鑰設定檔
load_dotenv()

def get_har_path():
    """尋找 HAR 檔案的正確路徑，支援開發環境與 PyInstaller 打包環境"""
    # 1. 優先檢查是否在 PyInstaller 打包後的臨時資料夾
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
        path = os.path.join(base_dir, 'tprisweb.shh.org.tw.har')
        if os.path.exists(path):
            return path
            
    # 2. 檢查目前指令碼所在資料夾
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, 'tprisweb.shh.org.tw.har')
    if os.path.exists(path):
        return path
        
    # 3. 檢查目前工作目錄
    path = os.path.join(os.getcwd(), 'tprisweb.shh.org.tw.har')
    if os.path.exists(path):
        return path
        
    return 'tprisweb.shh.org.tw.har'

def parse_har_patients():
    """解析 HAR 檔案中「檢查項目」為「Chest(AP)Portable」的病患"""
    har_path = get_har_path()
    print(f"[{time.strftime('%H:%M:%S')}] 正在載入並解析 HAR 檔案: {har_path}")
    
    if not os.path.exists(har_path):
        print(f"[錯誤] 找不到 HAR 檔案：{har_path}")
        return []
        
    try:
        with open(har_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[錯誤] 無法讀取或解析 HAR 檔案 JSON：{e}")
        return []
        
    extracted_patients = []
    seen_keys = set()
    
    entries = data.get('log', {}).get('entries', [])
    for entry in entries:
        url = entry.get('request', {}).get('url', '')
        if 'exam/List' not in url:
            continue
            
        text = entry.get('response', {}).get('content', {}).get('text', '')
        if not text:
            continue
            
        try:
            res_data = json.loads(text)
            items = res_data.get('Items', [])
            for item in items:
                proc_name = item.get('ProcedureName', '')
                # 篩選「檢查項目」為 Chest(AP)Portable 的病人
                if proc_name == 'Chest(AP)Portable':
                    pid = item.get('PatientId')
                    pname = item.get('PatientName')
                    bed = item.get('BedNo')
                    
                    if not pid:
                        continue
                        
                    # 以 (病歷號, 檢查項目) 作為唯一鍵以進行排重
                    key = (pid, proc_name)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        
                        # 中文字串正常處理 (Python 內部已解析為 unicode)
                        extracted_patients.append({
                            "name": pname or "未知",
                            "record_no": pid,
                            "bed": bed if bed else "(無病房資料)",
                            "exam": proc_name
                        })
        except Exception:
            # 忽略個別 JSON 解析錯誤 of entry
            continue
            
    return extracted_patients

def run_scraper():
    print("==================================================")
    print("  啟動 HAR 檔案解析器 (取代原本的 Playwright 爬蟲) ")
    print("==================================================")
    
    account = os.environ.get('TPRIS_ACCOUNT', '未設定')
    password = os.environ.get('TPRIS_PASSWORD', '未設定')
    print(f"  金鑰登入帳號: {account}")
    print(f"  金鑰登入密碼: {'*' * len(password) if password != '未設定' else '未設定'}")
    print("-" * 50)
    
    # 讀取並解析病患資料 (HAR 檔為靜態，只需讀取一次)
    patients = parse_har_patients()
    
    print(f"[{time.strftime('%H:%M:%S')}] [成功] 共尋找到 {len(patients)} 筆符合條件的病患：")
    for i, p in enumerate(patients, 1):
        print(f"  病患 {i}: {p['name']} ({p['record_no']}) - 床號: {p['bed']} - 項目: {p['exam']}")
    print("-" * 50)
    
    # 週期性同步名單給 Flask，讓 status_manager 能過濾已派遣病患並回傳最新名單
    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] 正在同步名單至 Flask 系統...")
            response = requests.post(FLASK_API_URL, json=patients)
            if response.status_code == 200:
                print("✅ 成功同步最新名單至 Flask 系統！")
            else:
                print(f"❌ 同步失敗，伺服器回傳狀態碼: {response.status_code}")
        except Exception as e:
            print(f"❌ 無法連線到 Flask 系統 (請確定 app.py 有啟動): {e}")
            
        print("等待 10 秒...\n" + "-"*30)
        time.sleep(10)

if __name__ == "__main__":
    run_scraper()
