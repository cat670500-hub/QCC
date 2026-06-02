import os
import sys
import json
import time
import datetime
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

def login_and_get_token(account, password):
    """登入醫院 TPRIS 系統取得 JWT Token"""
    url = "https://tprisweb.shh.org.tw/Auth/Login"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        "Name": account,
        "Password": password
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            token = res_data.get('token')
            if token:
                return token
            else:
                raise ValueError("登入回傳中無效的 Token 欄位")
        else:
            raise requests.exceptions.HTTPError(f"登入失敗，伺服器回傳狀態碼: {response.status_code}")
    except Exception as e:
        raise ConnectionError(f"無法連線登入醫院 TPRIS 系統: {e}")

def is_critical_care_bed(bed):
    """判斷床號是否屬於重症病房 (MICU, SICU, CCU, NCU, RCC, CIU, SIU 等)"""
    if not bed:
        return False
    bed_upper = str(bed).upper().strip()
    critical_keywords = ['ICU', 'MIU', 'NCU', 'RCC', 'CCU', 'SICU', 'SIU', 'CIU', 'PICU', 'NICU', 'BICU', 'EICU', 'RICU', 'RCW']
    return any(kw in bed_upper for kw in critical_keywords)

def fetch_live_patients(token):
    """使用 JWT Token 實時取得今日病患檢查清單 (不加 Status 參數，避免遺漏 56 等狀態的病患)"""
    url = "https://tprisweb.shh.org.tw/exam/List"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 動態產生今日的 ISO 8601 時間參數
    today_str = datetime.date.today().isoformat()
    params = {
        "$top": 3000, # 擴大抓取範圍至 3000 筆，確保撈取今日清晨開始的所有醫令 (解決忙碌醫院清晨醫令被擠出前 1000 筆的問題)
        "$skip": 0,
        "$orderby": "OrderDate desc",
        "orderDateStart": f"{today_str}T00:00:00+08:00",
        "orderDateEnd": f"{today_str}T23:59:59+08:00",
        "orByDefault": "true"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            return response.json().get('Items', [])
        elif response.status_code == 401:
            raise PermissionError("Token 已過期或未授權 (401)")
        else:
            raise requests.exceptions.HTTPError(f"獲取病患清單失敗，狀態碼: {response.status_code}")
    except Exception as e:
        if isinstance(e, PermissionError):
            raise e
        raise ConnectionError(f"實時 API 連線異常: {e}")

def parse_patients(raw_items):
    """解析病患清單，並依『醫令名稱符合 Chest(AP)Portable』或『床號為重症病房』做聯集篩選"""
    extracted_patients = []
    seen_keys = set()
    
    # 僅撈取以下活躍狀態的病患 (11:尚未排檢, 12:預約登記, 21:櫃台報到, 56:自動分派/已分派, Hold:暫卡)
    active_statuses = ['11', '12', '21', '56', 'Hold']
    
    for item in raw_items:
        # 去掉儀器類別為 CT 或 MR/MRI 的病患
        modality = str(item.get('Modality', '')).upper().strip()
        if modality in ['CT', 'MR', 'MRI']:
            continue
            
        status = str(item.get('Status', ''))
        if status not in active_statuses:
            continue
            
        proc_name = item.get('ProcedureName', '')
        bed = item.get('BedNo', '')
        
        # 條件 1：醫令名稱符合 'Chest(AP)Portable'
        is_chest_portable = (proc_name == 'Chest(AP)Portable')
        
        # 條件 2：病床號符合重症病房
        is_icu = is_critical_care_bed(bed)
        
        # 聯集篩選 (任一符合即呈現)
        if is_chest_portable or is_icu:
            pid = item.get('PatientId')
            pname = item.get('PatientName')
            source = item.get('PatientSourceTypeName') or "未知"
            accession_no = item.get('AccessionNo', '')
            order_no = item.get('OrderNo', '')
            
            if not pid:
                continue
                
            # 排重鍵
            key = (pid, proc_name)
            if key not in seen_keys:
                seen_keys.add(key)
                
                extracted_patients.append({
                    "name": pname or "未知",
                    "record_no": pid,
                    "bed": bed if bed else "(無病房資料)",
                    "exam": proc_name,
                    "source": source,
                    "accession_no": accession_no,
                    "order_no": order_no,
                    # 如果醫院端狀態為 21 (櫃台報到)，則直接標記為已報到 (checked_in)
                    "checked_in": (status == '21'),
                    # 如果醫院端狀態為 56 (自動分派/已分派)，則直接標記為已分派 (dispatched)
                    "dispatched": (status == '56')
                })
                
    return extracted_patients

def run_scraper():
    print("==================================================")
    print("      啟動實時醫院 API 爬蟲系統 (完全連線模式)      ")
    print("==================================================")
    
    current_account = None
    current_password = None
    token = None
    
    while True:
        try:
            # 每次輪詢動態讀取最新的環境變數，以支援不同操作人員的登入與切換
            env_account = os.environ.get('TPRIS_ACCOUNT', '未設定')
            env_password = os.environ.get('TPRIS_PASSWORD', '未設定')
            
            if env_account == '未設定' or env_password == '未設定':
                print("[錯誤] 未在環境或登入對應中設定 TPRIS_ACCOUNT 與 TPRIS_PASSWORD！等待操作人員登入...")
                time.sleep(5)
                continue
                
            # 偵測到操作人員變更，強制重置 Token 並使用新帳密登入醫院系統
            if env_account != current_account or env_password != current_password:
                print(f"\n[{time.strftime('%H:%M:%S')}] 偵測到當前操作人員變更為: {env_account}")
                print(f"[{time.strftime('%H:%M:%S')}] 正在以新操作人員帳號進行醫院系統登入安全驗證...")
                current_account = env_account
                current_password = env_password
                token = None  # 強制清除舊 Token
                
            # 1. 確保有 Token
            if not token:
                print(f"[{time.strftime('%H:%M:%S')}] 正在以操作人員 {current_account} 登入醫院系統並取得安全 Token...")
                token = login_and_get_token(current_account, current_password)
                print(f"[成功] 操作人員 {current_account} 成功取得安全驗證 Token！")
                
            # 2. 獲取實時資料
            print(f"[{time.strftime('%H:%M:%S')}] 正在從醫院網路 API 實時撈取今日檢查清單...")
            raw_items = fetch_live_patients(token)
            
            # 3. 解析與篩選
            patients = parse_patients(raw_items)
            print(f"[成功] 實時取得成功！共撈取到 {len(patients)} 筆符合條件 (醫令或重症病房) 的今日病患。")
            
            # 4. 同步至 Flask 主系統
            response = requests.post(FLASK_API_URL, json=patients, timeout=5)
            if response.status_code == 200:
                print("[同步] 成功同步實時名單至主系統平台！")
            else:
                print(f"[錯誤] 同步主系統失敗，伺服器狀態碼: {response.status_code}")
                
        except PermissionError:
            print("[警告] Token 已失效，將於下次輪詢時自動重登刷新 Token...")
            token = None
            
        except Exception as e:
            # 依據使用者需求：若無法連上醫院網路實時取得資料就回報錯誤！
            print(f"\n[錯誤] 無法連上醫院網路實時取得資料！請確認醫院 VPN 或內網連線是否正常。")
            print(f"   詳細錯誤資訊: {e}\n")
            
        print("等待 10 秒後再次進行實時輪詢...\n" + "-"*40)
        time.sleep(10)

if __name__ == "__main__":
    run_scraper()
