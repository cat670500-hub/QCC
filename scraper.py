import os
import sys
import json
import time
import datetime
import requests
import socketio

# Flask 系統的網址
FLASK_API_URL = os.environ.get("FLASK_API_URL", "http://127.0.0.1:5000/api/update_patients")

# 初始化 Socket.IO 客戶端 (關閉 SSL 驗證防內部網路憑證問題)
sio = socketio.Client(ssl_verify=False)

@sio.event
def connect():
    print("[代理端] 成功與主伺服器建立 WebSocket 連線！")
    sio.emit('register_agent')

@sio.event
def disconnect():
    print("[代理端] 與主伺服器的 WebSocket 連線已中斷。")

@sio.on('agent_check_in')
def handle_agent_check_in(data):
    acc_no = data.get("accession_no")
    is_check = data.get("is_check_in", True)
    action_name = "報到" if is_check else "取消報到"
    
    print(f"[代理端] 收到主伺服器即時轉發的{action_name}請求: 單號={acc_no}")
    
    if not acc_no:
        sio.emit('agent_check_in_result', {
            "accession_no": acc_no,
            "is_check_in": is_check,
            "success": False,
            "message": "AccessionNo 為空"
        })
        return
        
    token = os.environ.get('TPRIS_TOKEN')
    if not token:
        try:
            account = os.environ.get('TPRIS_ACCOUNT')
            password = os.environ.get('TPRIS_PASSWORD')
            if account and password and account != '未設定' and password != '未設定':
                token = login_and_get_token(account, password)
                os.environ['TPRIS_TOKEN'] = token
        except Exception as e:
            sio.emit('agent_check_in_result', {
                "accession_no": acc_no,
                "is_check_in": is_check,
                "success": False,
                "message": f"無法登入取得 Token: {e}"
            })
            log_local_error(acc_no, action_name, f"無法登入取得 Token: {e}")
            return
            
    success = False
    err_msg = ""
    try:
        success = hospital_check_in(token, acc_no, is_check)
        if not success:
            err_msg = "醫院 API 回傳失敗 (詳見爬蟲主控台)"
    except PermissionError:
        print("[代理端] Token 失效，嘗試重新登入並重試...")
        try:
            account = os.environ.get('TPRIS_ACCOUNT')
            password = os.environ.get('TPRIS_PASSWORD')
            token = login_and_get_token(account, password)
            os.environ['TPRIS_TOKEN'] = token
            success = hospital_check_in(token, acc_no, is_check)
            if not success:
                err_msg = "醫院 API 回傳失敗"
        except Exception as ex:
            err_msg = f"Token 刷新重試失敗: {ex}"
            log_local_error(acc_no, action_name, err_msg)
    except Exception as e:
        err_msg = f"連線異常: {e}"
        log_local_error(acc_no, action_name, err_msg)
        
    sio.emit('agent_check_in_result', {
        "accession_no": acc_no,
        "is_check_in": is_check,
        "success": success,
        "message": "同步成功" if success else err_msg
    })
    
    if success:
        try:
            print("[代理端] 同步成功，正在立即刷新醫院實時病患清單...")
            raw_items = fetch_live_patients(token)
            patients = parse_patients(raw_items)
            requests.post(FLASK_API_URL, json=patients, timeout=5)
            print("[代理端] 已成功更新最新病患狀態清單！")
        except Exception as ex:
            print(f"[代理端警告] 同步成功後自動刷新名單發生錯誤: {ex}")

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

def log_local_error(accession_no, action, message):
    try:
        time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{time_str}] 單號: {accession_no} | 動作: {action} | 原因: {message}\n"
        with open("check_in_errors.log", "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[警告] 寫入本地錯誤記錄檔失敗: {e}")

def hospital_check_in(token, accession_no, is_check_in=True):
    """向醫院 TPRIS 系統寫回/同步報到或取消報到狀態"""
    if not accession_no:
        print("[同步警告] 醫令 AccessionNo 為空，無法寫回醫院系統報到狀態")
        return False
        
    url = "https://tprisweb.shh.org.tw/exam/CheckIn" if is_check_in else "https://tprisweb.shh.org.tw/exam/CheckInBack"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    if is_check_in:
        payload = {
            "AccessionNos": [accession_no],
            "ChangeState": True,
            "Marge": False,
            "RoomNo": "82Portable"
        }
    else:
        payload = {
            "AccessionNos": [accession_no],
            "CheckInBackNote": "",
            "Marge": False
        }
        
    action_name = "報到" if is_check_in else "取消報到"
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # 關閉 SSL 驗證以防醫院內部網路凭证錯誤
        response = requests.put(url, headers=headers, json=payload, verify=False, timeout=10)
        if response.status_code == 200:
            res_json = None
            try:
                res_json = response.json()
            except Exception:
                pass
                
            is_ok = True
            err_msg = ""
            if isinstance(res_json, dict):
                # 檢查常見的成功/失敗標記
                for key in ["Success", "success", "IsSuccess", "isSuccess"]:
                    if key in res_json:
                        val = res_json[key]
                        if val is False or str(val).lower() == "false":
                            is_ok = False
                # 提取錯誤訊息
                for key in ["Message", "message", "ErrorMsg", "errorMsg", "Msg", "msg"]:
                    if key in res_json and res_json[key]:
                        err_msg = str(res_json[key])
            
            if is_ok:
                print(f"[同步成功] 成功將 {accession_no} 的{action_name}狀態寫回醫院 TPRIS 系統！ 回傳內容: {response.text}")
                return True
            else:
                msg = err_msg if err_msg else response.text
                print(f"[同步失敗] 醫院系統回傳成功狀態碼 200，但業務邏輯處理失敗: {msg}")
                log_local_error(accession_no, action_name, msg)
                return False
        elif response.status_code == 401:
            raise PermissionError("Token 已失效 (401)")
        elif response.status_code == 500 and ("already being tracked" in response.text or "is already being tracked" in response.text):
            print(f"[同步警告] 醫院系統回傳 500 (實體追蹤衝突)，單號 {accession_no} 應已於醫院端完成{action_name}！")
            return True
        else:
            msg = f"HTTP {response.status_code}: {response.text}"
            print(f"[同步失敗] 醫院系統回傳狀態碼: {response.status_code}, 內容: {response.text}")
            log_local_error(accession_no, action_name, msg)
            return False
    except Exception as e:
        if isinstance(e, PermissionError):
            raise e
        msg = str(e)
        print(f"[同步錯誤] 連線醫院系統寫回報到狀態時發生異常: {msg}")
        log_local_error(accession_no, action_name, msg)
        return False

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
    """解析病患清單，並依『醫令名稱符合 Chest(AP)Portable』、『床號為重症病房』以及『同住院病患之其它 CR 檢查』做篩選"""
    extracted_patients = []
    seen_keys = set()
    
    # 僅撈取以下活躍狀態的病患 (11:尚未排檢, 12:預約登記, 21:櫃台報到, 56:自動分派/已分派, Hold:暫卡)
    active_statuses = ['11', '12', '21', '56', 'Hold']
    
    # 1. 先收集「今天有 Portable 檢查」的住院病患病歷號
    portable_patient_ids = set()
    for item in raw_items:
        modality = str(item.get('Modality', '')).upper().strip()
        if modality in ['CT', 'MR', 'MRI']:
            continue
        status = str(item.get('Status', ''))
        if status not in active_statuses:
            continue
            
        source = str(item.get('PatientSourceTypeName') or '').strip()
        source_code = str(item.get('PatientSourceTypeCode') or '').strip()
        is_ward = (source == "住院" or source_code == "I")
        
        proc_name = str(item.get('ProcedureName', '')).strip()
        is_portable_exam = "portable" in proc_name.lower() or (item.get('ScheduleLocation') == '82Portable')
        
        if is_ward and is_portable_exam:
            raw_pid = item.get('PatientId')
            if raw_pid:
                portable_patient_ids.add(str(raw_pid).strip())
                
    # 2. 第二次掃描，進行篩選與建構名單
    for item in raw_items:
        # 去掉儀器類別為 CT 或 MR/MRI 的病患
        modality = str(item.get('Modality', '')).upper().strip()
        if modality in ['CT', 'MR', 'MRI']:
            continue
            
        status = str(item.get('Status', ''))
        if status not in active_statuses:
            continue
            
        proc_name = str(item.get('ProcedureName', '')).strip()
        bed = item.get('BedNo', '')
        source = str(item.get('PatientSourceTypeName') or '').strip()
        source_code = str(item.get('PatientSourceTypeCode') or '').strip()
        
        # 條件 1：醫令名稱符合 'Chest(AP)Portable'
        is_chest_portable = (proc_name == 'Chest(AP)Portable')
        
        # 條件 2：病床號符合重症病房
        is_icu = is_critical_care_bed(bed)
        
        # 條件 3：同一個住院病患有 Portable，且此項目為 CR 檢查
        raw_pid = item.get('PatientId')
        pid = str(raw_pid).strip() if raw_pid is not None else ""
        is_ward = (source == "住院" or source_code == "I")
        is_other_cr_for_portable_patient = False
        if is_ward and pid in portable_patient_ids and modality in ['CR', 'DX']:
            is_other_cr_for_portable_patient = True
        
        # 聯集篩選 (任一符合即呈現)
        if is_chest_portable or is_icu or is_other_cr_for_portable_patient:
            if not pid:
                continue
                
            pname = str(item.get('PatientName') or '').strip() or "未知"
            accession_no = str(item.get('AccessionNo') or '').strip()
            order_no = str(item.get('OrderNo') or '').strip()
            
            raw_bed = item.get('BedNo')
            bed_str = str(raw_bed).strip() if raw_bed is not None else ""
            
            # 排重鍵 (同一病患、相同檢查項目、不同申請單號皆視為獨立項目呈現)
            req_no = accession_no if accession_no else order_no
            key = (pid, proc_name, req_no)
            if key not in seen_keys:
                seen_keys.add(key)
                
                # 若醫院端狀態為 21 (櫃台報到) 或 CheckInTime 有時間值，則標記為已報到 (checked_in)
                raw_check_in_time = item.get('CheckInTime')
                is_checked_in = (status == '21' or (raw_check_in_time is not None and str(raw_check_in_time).strip() != ""))
                
                extracted_patients.append({
                    "name": pname,
                    "record_no": pid,
                    "bed": bed_str if bed_str else "(無病房資料)",
                    "exam": proc_name,
                    "source": source if source else "住院",
                    "accession_no": accession_no,
                    "order_no": order_no,
                    "checked_in": is_checked_in,
                    # 如果醫院端狀態為 56 (自動分派/已分派)，則直接標記為已分派 (dispatched)
                    "dispatched": (status == '56')
                })
                
    return extracted_patients

def run_scraper():
    print("==================================================")
    print("      啟動實時醫院 API 爬蟲系統 (完全連線模式)      ")
    print("==================================================")
    
    # 建立與主伺服器的 WebSocket 即時連線
    flask_base = FLASK_API_URL.rsplit('/api/', 1)[0] if '/api/' in FLASK_API_URL else FLASK_API_URL.rstrip('/')
    try:
        if not sio.connected:
            sio.connect(flask_base)
            print(f"[代理端] 已成功嘗試連線至主伺服器 WebSocket: {flask_base}")
    except Exception as e:
        print(f"[代理端警告] 無法即時連線主伺服器 WebSocket: {e}，將僅依賴原本的 10 秒輪詢機制同步。")
        
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
            
            # 共享 Token 供 app.py 執行緒進行寫回操作
            os.environ['TPRIS_TOKEN'] = token
                
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
                
            # 5. 抓取待處理的報到/取消報到任務，並傳送至醫院系統
            flask_base = FLASK_API_URL.rsplit('/api/', 1)[0] if '/api/' in FLASK_API_URL else FLASK_API_URL.rstrip('/')
            pending_url = f"{flask_base}/api/pending_check_ins"
            try:
                pending_resp = requests.get(pending_url, timeout=5)
                if pending_resp.status_code == 200:
                    pending_tasks = pending_resp.json()
                    if pending_tasks:
                        print(f"[{time.strftime('%H:%M:%S')}] 偵測到 {len(pending_tasks)} 筆待同步報到/取消報到任務...")
                        for task in pending_tasks:
                            acc_no = task.get("accession_no")
                            is_check = task.get("is_check_in", True)
                            if acc_no:
                                try:
                                    hospital_check_in(token, acc_no, is_check)
                                except PermissionError:
                                    print("[警告] 執行報到同步任務時 Token 已失效，嘗試重新登入...")
                                    token = login_and_get_token(current_account, current_password)
                                    os.environ['TPRIS_TOKEN'] = token
                                    # 用新 Token 重試一次
                                    hospital_check_in(token, acc_no, is_check)
            except Exception as e:
                print(f"[錯誤] 處理待同步任務時發生異常: {e}")
                
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
