import sys
import os
import threading
import time
import re
import webbrowser
import socket
import json
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_socketio import SocketIO, emit

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
                print(f"[系統] 已成功載入金鑰設定檔: {path}")
                break
            except Exception as e:
                print(f"[警告] 讀取設定檔 {path} 時發生錯誤: {e}")

# 載入金鑰設定
load_dotenv()

# 判斷是否為 PyInstaller 打包後的執行檔
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    # 讓 Playwright 讀取打包進來的瀏覽器 (備用)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(sys._MEIPASS, 'ms-playwright')
else:
    app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('TPRIS_PASSWORD', 'hospital-secret!')

# 明確指定 async_mode='threading' 避免 PyInstaller 打包後找不到非同步驅動
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

@app.context_processor
def inject_host_info():
    return {
        'host_ip': get_local_ip(),
        'port': 5000
    }

@app.before_request
def check_auth():
    # 靜態資源、登入頁面與 API 接口不攔截
    if request.path.startswith('/static/') or request.path.startswith('/api/') or request.path == '/login' or request.path == '/manifest.json' or request.path == '/sw.js':
        return
    if not session.get('authenticated'):
        return redirect(url_for('login'))

def get_all_operators():
    """從環境變數中解析所有操作人員的帳號與密碼對應"""
    operators = {}
    
    # 支援單一帳密 (Legacy/預設)
    legacy_acc = os.environ.get('TPRIS_ACCOUNT')
    legacy_pwd = os.environ.get('TPRIS_PASSWORD')
    if legacy_acc and legacy_pwd:
        operators[legacy_acc] = legacy_pwd
        
    # 支援多組帳密 (例如 TPRIS_ACCOUNT_1, TPRIS_PASSWORD_1 等)
    for key, val in os.environ.items():
        if key.startswith('TPRIS_ACCOUNT_'):
            suffix = key[len('TPRIS_ACCOUNT_'):]
            pwd_key = f'TPRIS_PASSWORD_{suffix}'
            pwd_val = os.environ.get(pwd_key)
            if pwd_val:
                operators[val] = pwd_val
                
    return operators

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        account_input = request.form.get('account', '').strip()
        password_input = request.form.get('password', '').strip()
        
        operators = get_all_operators()
        matched_account = None
        matched_password = None
        
        if account_input:
            # 如果輸入了帳號，進行精確匹配
            if account_input in operators and operators[account_input] == password_input:
                matched_account = account_input
                matched_password = password_input
        else:
            # 如果沒有輸入帳號，僅憑密碼自動尋找對應帳號
            for acc, pwd in operators.items():
                if pwd == password_input:
                    matched_account = acc
                    matched_password = pwd
                    break
                    
        if matched_account:
            session['authenticated'] = True
            session['operator_account'] = matched_account
            
            # 動態更新目前環境變數中作用的帳密，供背景爬蟲執行緒讀取，從而登記不同的操作人員
            os.environ['TPRIS_ACCOUNT'] = matched_account
            os.environ['TPRIS_PASSWORD'] = matched_password
            print(f"[系統] 成功變更當前登入的操作人員為: {matched_account}")
            
            return redirect(url_for('index'))
        else:
            error = "帳號或密碼不正確，請重新輸入！"
            
    return render_template('login.html', error=error)


# 存放待傳送至醫院系統的報到/取消報到指令
pending_hospital_check_ins = []

# 存放本機代理端的連線 Session ID
agent_sid = None


# 存放目前的請求狀態 (簡易版，不持久化)
current_requests = {}
# 存放已經發送過的病患，避免重複出現 (使用 record_no + exam 作為唯一鍵)
sent_patients = set()
# 存放已經手動報到過的病患
checked_in_patients = set()
# 存放已經回覆/確認過的病患
confirmed_patients = set()
# 存放本地發送時間，使用 record_no + exam + req_no 作為唯一鍵
dispatch_times = {}

# 系統設定持久化與自訂通知文字
SETTINGS_FILE = "settings.json"
system_settings = {"custom_message": ""}

def load_settings():
    global system_settings
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                system_settings = json.load(f)
            print(f"[系統] 已成功載入設定檔: {system_settings}")
        else:
            save_settings(system_settings)
    except Exception as e:
        print(f"[警告] 載入設定檔 {SETTINGS_FILE} 失敗: {e}")

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        print(f"[系統] 已儲存設定檔: {settings}")
    except Exception as e:
        print(f"[警告] 儲存設定檔 {SETTINGS_FILE} 失敗: {e}")

load_settings()

SMS_SETTINGS_FILE = "sms_settings.json"
sms_settings = {"rules": []}

def load_sms_settings():
    global sms_settings
    try:
        if os.path.exists(SMS_SETTINGS_FILE):
            with open(SMS_SETTINGS_FILE, "r", encoding="utf-8") as f:
                sms_settings = json.load(f)
            print(f"[系統] 已成功載入簡訊設定檔: {sms_settings}")
        else:
            save_sms_settings(sms_settings)
    except Exception as e:
        print(f"[警告] 載入簡訊設定檔 {SMS_SETTINGS_FILE} 失敗: {e}")

def save_sms_settings(settings):
    try:
        with open(SMS_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        print(f"[系統] 已儲存簡訊設定檔: {settings}")
    except Exception as e:
        print(f"[警告] 儲存簡訊設定檔 {SMS_SETTINGS_FILE} 失敗: {e}")

load_sms_settings()

# 存放 Android 簡訊/來電端之連線 Session ID
android_sid = None

def get_sms_number_for_bed(bed):
    if not bed:
        return None
    match = re.match(r'^([a-zA-Z0-9]+?)(0*[0-9]+)$', bed.strip())
    if match:
        ward = match.group(1).upper()
        try:
            bed_num = int(match.group(2))
        except ValueError:
            return None
    else:
        ward = bed.strip().upper()
        bed_num = 0

    for rule in sms_settings.get("rules", []):
        rule_ward = str(rule.get("ward", "")).strip().upper()
        if ward == rule_ward:
            try:
                start = int(rule.get("bed_start", 0))
                end = int(rule.get("bed_end", 0))
                if start <= bed_num <= end:
                    return rule.get("phone")
            except Exception:
                continue
    return None

# 存放每個病患發送時的自訂通知文字
dispatch_messages = {}

# 存放確認紀錄的清單 (最新 50 筆)
confirmed_history = []

def add_to_history(request_id, patient_info):
    global patients_data
    if patient_info:
        # 記錄至已確認集合
        record_no = str(patient_info.get('record_no') or '').strip()
        exam = str(patient_info.get('exam') or '').strip()
        acc = str(patient_info.get('accession_no') or '').strip()
        ord_no = str(patient_info.get('order_no') or '').strip()
        req_no = acc if acc else ord_no
        patient_key = f"{record_no}|{exam}|{req_no}"
        confirmed_patients.add(patient_key)
        
        # 同步更新當前 patients_data 的確認狀態
        for p in patients_data:
            p_rec = str(p.get('record_no') or '').strip()
            p_ex = str(p.get('exam') or '').strip()
            p_acc = str(p.get('accession_no') or '').strip()
            p_ord = str(p.get('order_no') or '').strip()
            p_req = p_acc if p_acc else p_ord
            if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
                p['confirmed'] = True
                break

        time_str = time.strftime('%H:%M:%S')
        # 避免重複寫入
        for h in confirmed_history:
            if h["id"] == request_id:
                return
        confirmed_history.append({
            "id": request_id,
            "name": patient_info.get("name"),
            "record_no": patient_info.get("record_no"),
            "bed": patient_info.get("bed"),
            "exam": patient_info.get("exam"),
            "time": time_str
        })
        if len(confirmed_history) > 50:
            confirmed_history.pop(0)

def log_dispatch(patient_info, time_str):
    try:
        date_str = time.strftime("%Y-%m-%d")
        log_file = f"dispatch_{date_str}.log"
        time_stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        name = patient_info.get("name", "未知")
        record_no = patient_info.get("record_no", "未知")
        exam = patient_info.get("exam", "未知")
        bed = patient_info.get("bed", "未知")
        log_line = f"[{time_stamp}] 病患: {name} ({record_no}) | 檢查: {exam} | 床號: {bed} | 已發送通知\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
        print(f"[日誌] 寫入發送日誌: {log_line.strip()}")
    except Exception as e:
        print(f"[警告] 寫入發送日誌失敗: {e}")

def sort_patients(patients):
    """排序病患：語音提到 (最上端) -> 已報到 (次之) -> 未報到 (中端) -> 已分派 (最下端)。同狀態下依 OrderNo 降序排序。"""
    # 穩定排序：先依單號降序 (新單在上)
    patients_by_date = sorted(patients, key=lambda x: x.get('order_no', ''), reverse=True)
    # 狀態優先級：語音提到 (0) -> 已報到 (1) -> 未報到 (2) -> 已分派 (3)
    def get_status_priority(p):
        if p.get('voice_mentioned'):
            return 0
        elif p.get('dispatched'):
            return 3
        elif p.get('checked_in'):
            return 1
        else:
            return 2
    return sorted(patients_by_date, key=get_status_priority)

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <title>Portable 收發訊息</title>
        <link rel="stylesheet" href="/static/css/style.css">
    </head>
    <body>
        <div class="container">
            <h1>Portable 收發訊息</h1>
            <div style="display: flex; flex-direction: column; gap: 15px; margin-top: 20px;">
                <a href="/sender" style="text-decoration: none;">
                    <button style="width: 100%;">前往發送端 (Sender)</button>
                </a>
                <a href="/receiver" style="text-decoration: none;">
                    <button style="width: 100%;">前往接收端 (Receiver)</button>
                </a>
            </div>
        </div>
    </body>
    </html>
    '''

patients_data = []

@app.route('/sender')
def sender():
    return render_template('sender.html', patients=patients_data, custom_message=system_settings.get('custom_message', ''))

@app.route('/receiver')
def receiver():
    return render_template('receiver.html')

@app.route('/mobile')
def mobile_receiver():
    return render_template('mobile_receiver.html')

@app.route('/sms_settings')
def sms_settings_page():
    return render_template('sms_settings.html')

@app.route('/api/sms_settings', methods=['GET', 'POST'])
def api_sms_settings():
    global sms_settings
    if request.method == 'POST':
        data = request.get_json() or {}
        sms_settings['rules'] = data.get('rules', [])
        save_sms_settings(sms_settings)
        return jsonify({"status": "success"})
    return jsonify(sms_settings)

@app.route('/api/clear_voice_mention', methods=['POST'])
def clear_voice_mention():
    global patients_data
    data = request.get_json() or {}
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    acc = str(data.get('accession_no') or '').strip()
    ord_no = str(data.get('order_no') or '').strip()
    req_no = acc if acc else ord_no
    
    patient_key = f"{record_no}|{exam}|{req_no}"
    for p in patients_data:
        p_rec = str(p.get('record_no') or '').strip()
        p_ex = str(p.get('exam') or '').strip()
        p_acc = str(p.get('accession_no') or '').strip()
        p_ord = str(p.get('order_no') or '').strip()
        p_req = p_acc if p_acc else p_ord
        if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
            p['voice_mentioned'] = False
            break
            
    patients_data = sort_patients(patients_data)
    socketio.emit('patients_updated', patients_data)
    return jsonify({"status": "success"})

@app.route('/manifest.json')
def serve_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def serve_sw():
    response = app.make_response(app.send_static_file('sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    global system_settings
    if request.method == 'POST':
        data = request.get_json() or {}
        system_settings['custom_message'] = data.get('custom_message', '').strip()
        save_settings(system_settings)
        return jsonify({"status": "success"})
    return jsonify(system_settings)

@app.route('/api/patients')
def api_patients():
    return jsonify(patients_data)

@app.route('/api/history')
def api_history():
    return jsonify(confirmed_history)

@app.route('/api/pending_check_ins', methods=['GET'])
def get_pending_check_ins():
    global pending_hospital_check_ins
    check_ins = list(pending_hospital_check_ins)
    pending_hospital_check_ins.clear()
    return jsonify(check_ins)

@app.route('/api/voice_dispatch', methods=['POST'])
def voice_dispatch():
    global patients_data
    data = request.get_json()
    text = data.get('text', '')
    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400
        
    print(f"[{time.strftime('%H:%M:%S')}] 收到來電通話語音對話: {text}")
    
    # 進行對話分析，並 cross-reference 目前爬蟲抓到的病患清單
    matched_patient = None
    
    # 1. 先用病歷號比對 (6-10 位數字)
    record_numbers = re.findall(r'\d{6,10}', text)
    if record_numbers:
        for r_no in record_numbers:
            r_no_clean = str(r_no).strip()
            for p in patients_data:
                if str(p.get('record_no', '')).strip() == r_no_clean:
                    matched_patient = p
                    break
            if matched_patient:
                break
                
    # 2. 如果病歷號沒配對到，用病患姓名比對
    if not matched_patient:
        for p in patients_data:
            p_name = str(p.get('name', '')).strip()
            if p_name and p_name in text:
                matched_patient = p
                break
                
    # 3. 如果找到了配對的病患，標記語音提到並廣播彈窗通知，由操作人員決定是否報到
    if matched_patient:
        matched_record_no = str(matched_patient.get('record_no', '')).strip()
        matched_exam = str(matched_patient.get('exam', '')).strip()
        matched_acc = str(matched_patient.get('accession_no', '')).strip()
        matched_ord = str(matched_patient.get('order_no', '')).strip()
        matched_req = matched_acc if matched_acc else matched_ord
        patient_key = f"{matched_record_no}|{matched_exam}|{matched_req}"
        
        # 標記為語音提到，最優先置頂
        for p in patients_data:
            p_rec = str(p.get('record_no', '')).strip()
            p_ex = str(p.get('exam', '')).strip()
            p_acc = str(p.get('accession_no', '')).strip()
            p_ord = str(p.get('order_no', '')).strip()
            p_req = p_acc if p_acc else p_ord
            if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
                p['voice_mentioned'] = True
                break
                
        patients_data = sort_patients(patients_data)
        socketio.emit('patients_updated', patients_data)
        
        # 廣播彈窗事件
        print(f"[語音提示] 來電語音提到病患: {matched_patient.get('name')}，發送彈窗廣播。")
        socketio.emit('voice_mention_alert', {
            'patient': matched_patient,
            'text': text
        })
        
        return jsonify({
            "status": "success", 
            "matched": True, 
            "patient": matched_patient,
            "action": "voice_mentioned"
        })
        
    return jsonify({
        "status": "success", 
        "matched": False, 
        "message": "在待發送名單中找不到符合的病患或病歷號"
    })

@app.route('/api/update_patients', methods=['POST'])
def update_patients():
    global patients_data
    data = request.get_json()
    if data is not None:
        # 不再過濾已發送病患，改為完整保留並標記狀態
        filtered_data = []
        for p in data:
            record_no = str(p.get('record_no') or '').strip()
            exam = str(p.get('exam') or '').strip()
            # 確保寫入 patients_data 的欄位值是經過標準化（字串化與去除空白）的
            p['record_no'] = record_no
            p['exam'] = exam
            
            acc = str(p.get('accession_no') or '').strip()
            ord_no = str(p.get('order_no') or '').strip()
            req_no = acc if acc else ord_no
            patient_key = f"{record_no}|{exam}|{req_no}"
            # 優先保留醫院端的已報到狀態 (如 status == '21')，或本系統手動/語音報到的狀態
            p['checked_in'] = p.get('checked_in', False) or (patient_key in checked_in_patients)
            # 優先保留確認/回覆狀態
            p['confirmed'] = p.get('confirmed', False) or (patient_key in confirmed_patients)
            # 優先保留語音提到狀態
            existing_voice_mentioned = False
            for old_p in patients_data:
                old_rec = old_p.get('record_no')
                old_ex = old_p.get('exam')
                old_acc = old_p.get('accession_no')
                old_ord = old_p.get('order_no')
                old_req = old_acc if old_acc else old_ord
                if f"{old_rec}|{old_ex}|{old_req}" == patient_key:
                    existing_voice_mentioned = old_p.get('voice_mentioned', False)
                    break
            p['voice_mentioned'] = p.get('voice_mentioned', False) or existing_voice_mentioned
            # 只有醫院端真正分派才設為 dispatched。本地發送使用 local_dispatched 追蹤。
            p['dispatched'] = p.get('dispatched', False)
            p['local_dispatched'] = (patient_key in sent_patients)
            p['dispatch_time'] = dispatch_times.get(patient_key, "")
            p['custom_message'] = dispatch_messages.get(patient_key, "")
            filtered_data.append(p)
                
        patients_data = sort_patients(filtered_data)
        socketio.emit('patients_updated', patients_data)
        return jsonify({"status": "success", "count": len(patients_data)})
    return jsonify({"status": "error"}), 400

@app.route('/api/sync_errors', methods=['GET'])
def get_sync_errors():
    log_file = "sync_errors.log"
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 回傳最後 100 筆記錄
        return jsonify(lines[-100:])
    except Exception as e:
        return jsonify([f"讀取日誌失敗: {e}"])

@app.route('/api/local_errors', methods=['GET'])
def get_local_errors():
    log_file = "check_in_errors.log"
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 回傳最後 100 筆記錄
        return jsonify(lines[-100:])
    except Exception as e:
        return jsonify([f"讀取日誌失敗: {e}"])

@app.route('/api/clear_errors', methods=['POST'])
def clear_errors():
    for log_file in ["sync_errors.log", "check_in_errors.log"]:
        try:
            if os.path.exists(log_file):
                with open(log_file, "w", encoding="utf-8") as f:
                    f.truncate(0)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success"})

@socketio.on('connect')
def handle_connect():
    print(f"[系統] 新客戶端建立 Socket 連線: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    global agent_sid, android_sid
    if request.sid == agent_sid:
        agent_sid = None
        print("[系統] 代理端 (本機) 已中斷連線。")
    elif request.sid == android_sid:
        android_sid = None
        print("[系統] Android 簡訊/來電控制端已中斷連線。")
    else:
        print(f"[系統] 客戶端中斷連線: {request.sid}")

@socketio.on('register_agent')
def handle_register_agent():
    global agent_sid
    agent_sid = request.sid
    print(f"[系統] 代理端 (本機) 已成功註冊，連線 ID: {agent_sid}")

@socketio.on('register_android')
def handle_register_android():
    global android_sid
    android_sid = request.sid
    print(f"[系統] Android 簡訊/來電控制端已成功註冊，連線 ID: {android_sid}")

@socketio.on('clear_voice_mention')
def handle_clear_voice_mention(data):
    global patients_data
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    acc = str(data.get('accession_no') or '').strip()
    ord_no = str(data.get('order_no') or '').strip()
    req_no = acc if acc else ord_no
    
    patient_key = f"{record_no}|{exam}|{req_no}"
    for p in patients_data:
        p_rec = str(p.get('record_no') or '').strip()
        p_ex = str(p.get('exam') or '').strip()
        p_acc = str(p.get('accession_no') or '').strip()
        p_ord = str(p.get('order_no') or '').strip()
        p_req = p_acc if p_acc else p_ord
        if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
            p['voice_mentioned'] = False
            break
            
    patients_data = sort_patients(patients_data)
    socketio.emit('patients_updated', patients_data)

def log_server_sync_error(acc_no, action, message):
    try:
        time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{time_str}] 單號: {acc_no} | 動作: {action} | 原因: {message}\n"
        with open("sync_errors.log", "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[警告] 寫入伺服器端錯誤日誌檔失敗: {e}")

@socketio.on('agent_check_in_result')
def handle_agent_check_in_result(data):
    acc_no = data.get("accession_no")
    is_check = data.get("is_check_in", True)
    success = data.get("success", False)
    msg = data.get("message", "")
    action = "報到" if is_check else "取消報到"
    
    print(f"[系統] 收到代理端回報執行結果: 單號={acc_no}, {action} 成功={success}, 訊息={msg}")
    
    if not success and acc_no:
        log_server_sync_error(acc_no, action, msg)
        global patients_data
        target_p = None
        for p in patients_data:
            p_acc = str(p.get('accession_no') or '').strip()
            if p_acc == acc_no:
                target_p = p
                p['checked_in'] = not is_check
                break
                
        if target_p:
            record_no = str(target_p.get('record_no') or '').strip()
            exam = str(target_p.get('exam') or '').strip()
            patient_key = f"{record_no}|{exam}|{acc_no}"
            
            if is_check:
                if patient_key in checked_in_patients:
                    checked_in_patients.remove(patient_key)
            else:
                checked_in_patients.add(patient_key)
                
            patients_data = sort_patients(patients_data)
            socketio.emit('patients_updated', patients_data)
            
        socketio.emit('agent_sync_error', {
            "accession_no": acc_no,
            "action": action,
            "message": msg
        })

# 發送端發出請求
@socketio.on('send_request')
def handle_request(data):
    global patients_data
    request_id = data.get('id')
    patient_info = data.get('patient')
    current_requests[request_id] = {
        "status": "waiting",
        "patient": patient_info
    }
    
    custom_message = data.get('custom_message', '').strip()
    if not custom_message:
        custom_message = system_settings.get('custom_message', '')
    
    if patient_info:
        # 記錄為已發送
        record_no = str(patient_info.get('record_no') or '').strip()
        exam = str(patient_info.get('exam') or '').strip()
        acc = str(patient_info.get('accession_no') or '').strip()
        ord_no = str(patient_info.get('order_no') or '').strip()
        req_no = acc if acc else ord_no
        patient_key = f"{record_no}|{exam}|{req_no}"
        sent_patients.add(patient_key)
        
        # 記錄發送時間與自訂通知文字，並寫入日誌檔
        now_str = time.strftime('%H:%M')
        dispatch_times[patient_key] = now_str
        dispatch_messages[patient_key] = custom_message
        log_dispatch(patient_info, now_str)
        
        # 標記為本地已發送，不改變 dispatched，維持在原本狀態與排序
        for p in patients_data:
            p_rec = str(p.get('record_no') or '').strip()
            p_ex = str(p.get('exam') or '').strip()
            p_acc = str(p.get('accession_no') or '').strip()
            p_ord = str(p.get('order_no') or '').strip()
            p_req = p_acc if p_acc else p_ord
            if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
                p['local_dispatched'] = True
                p['dispatch_time'] = now_str
                p['custom_message'] = custom_message
                break
        patients_data = sort_patients(patients_data)
        socketio.emit('patients_updated', patients_data)

        # --- 簡訊發送號碼匹配與觸發 ---
        bed = patient_info.get('bed', '')
        phone = get_sms_number_for_bed(bed)
        if phone and android_sid:
            exam_name = patient_info.get('exam', '未知')
            pname = patient_info.get('name', '未知')
            sms_text = f"【Portable 醫令通知】病房床號: {bed} | 檢查項目: {exam_name} | 病患: {pname} ({record_no})，請為其準備檢查。"
            print(f"[系統簡訊] 匹配到病房 {bed} 對應手機 {phone}，向 Android 端發送發簡訊指令。")
            socketio.emit('send_sms', {'phone': phone, 'message': sms_text}, room=android_sid)
        elif phone and not android_sid:
            print(f"[系統簡訊警告] 匹配到簡訊接收電話 {phone}，但 Android 簡訊發送端未連線！")
    
    patient_name = patient_info.get('name') if patient_info else 'Unknown'
    print(f"收到請求: {request_id} (病患: {patient_name})")
    # 推播給接收端
    emit('new_request', {'id': request_id, 'patient': patient_info, 'custom_message': custom_message}, broadcast=True)

# 接收端按下確認
@socketio.on('confirm_request')
def handle_confirm(data):
    request_id = data.get('id')
    if request_id in current_requests:
        patient_info = None
        if isinstance(current_requests[request_id], dict):
            current_requests[request_id]["status"] = "confirmed"
            patient_info = current_requests[request_id].get("patient")
        else:
            current_requests[request_id] = "confirmed"
            
        print(f"請求已確認: {request_id}")
        
        if patient_info:
            add_to_history(request_id, patient_info)
            
        # 通知發送端，並附帶病患資訊
        emit('request_confirmed', {'id': request_id, 'patient': patient_info}, broadcast=True)
        # 廣播更新後的病患清單，使所有接收端/發送端同步更新狀態
        socketio.emit('patients_updated', patients_data)

# 手動報到請求
@socketio.on('check_in_patient')
def handle_check_in(data):
    global patients_data
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    acc = str(data.get('accession_no') or '').strip()
    ord_no = str(data.get('order_no') or '').strip()
    req_no = acc if acc else ord_no
    
    patient_key = f"{record_no}|{exam}|{req_no}" if req_no else f"{record_no}|{exam}"
    checked_in_patients.add(patient_key)
    
    # 在記憶體中更新目前病患狀態
    accession_no = acc if acc else None
    for p in patients_data:
        p_record = str(p.get('record_no') or '').strip()
        p_exam = str(p.get('exam') or '').strip()
        p_acc = str(p.get('accession_no') or '').strip()
        p_ord = str(p.get('order_no') or '').strip()
        
        match = False
        if p_record == record_no and p_exam == exam:
            if acc and p_acc and acc == p_acc:
                match = True
            elif ord_no and p_ord and ord_no == p_ord:
                match = True
            elif not acc and not p_acc and not ord_no and not p_ord:
                match = True
            
        if match:
            p['checked_in'] = True
            if p_acc:
                accession_no = p_acc
            break
            
    print(f"病患已手動報到: {record_no} (項目: {exam}) 單號: {req_no}")
    
    # 記錄待同步報到狀態至醫院系統的任務
    if accession_no:
        if agent_sid:
            print(f"[系統] 轉發報到請求給本機代理端 (AccessionNo: {accession_no})")
            socketio.emit('agent_check_in', {
                "accession_no": accession_no,
                "is_check_in": True
            }, room=agent_sid)
        else:
            print(f"[系統警告] 代理端不在線，將報到任務寫入佇列等待輪詢...")
            pending_hospital_check_ins.append({
                "accession_no": accession_no,
                "is_check_in": True
            })
        
    patients_data = sort_patients(patients_data)
    # 廣播給所有發送端更新畫面
    socketio.emit('patients_updated', patients_data)

# 取消手動報到請求
@socketio.on('cancel_check_in_patient')
def handle_cancel_check_in(data):
    global patients_data
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    acc = str(data.get('accession_no') or '').strip()
    ord_no = str(data.get('order_no') or '').strip()
    req_no = acc if acc else ord_no
    
    patient_key = f"{record_no}|{exam}|{req_no}" if req_no else f"{record_no}|{exam}"
    if patient_key in checked_in_patients:
        checked_in_patients.remove(patient_key)
        
    # 在記憶體中更新目前病患狀態
    accession_no = acc if acc else None
    for p in patients_data:
        p_record = str(p.get('record_no') or '').strip()
        p_exam = str(p.get('exam') or '').strip()
        p_acc = str(p.get('accession_no') or '').strip()
        p_ord = str(p.get('order_no') or '').strip()
        
        match = False
        if p_record == record_no and p_exam == exam:
            if acc and p_acc and acc == p_acc:
                match = True
            elif ord_no and p_ord and ord_no == p_ord:
                match = True
            elif not acc and not p_acc and not ord_no and not p_ord:
                match = True
            
        if match:
            p['checked_in'] = False
            if p_acc:
                accession_no = p_acc
            break
            
    print(f"病患已取消手動報到: {record_no} (項目: {exam}) 單號: {req_no}")
    
    # 記錄待同步取消報到狀態至醫院系統的任務
    if accession_no:
        if agent_sid:
            print(f"[系統] 轉發取消報到請求給本機代理端 (AccessionNo: {accession_no})")
            socketio.emit('agent_check_in', {
                "accession_no": accession_no,
                "is_check_in": False
            }, room=agent_sid)
        else:
            print(f"[系統警告] 代理端不在線，將取消報到任務寫入佇列等待輪詢...")
            pending_hospital_check_ins.append({
                "accession_no": accession_no,
                "is_check_in": False
            })
        
    patients_data = sort_patients(patients_data)
    # 廣播給所有發送端更新畫面
    socketio.emit('patients_updated', patients_data)

if __name__ == '__main__':
    # 確保在 Flask debug 模式的 reloader 下不會重複啟動
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("=> 正在準備啟動系統...")
        
        # 使用 Thread 啟動爬蟲，避免 PyInstaller subprocess 產生 fork bomb
        from scraper import run_scraper
        def background_scraper():
            time.sleep(3) # 等待 Flask 啟動
            try:
                run_scraper()
            except Exception as e:
                print(f"爬蟲執行發生錯誤: {e}")
                
        threading.Thread(target=background_scraper, daemon=True).start()
        
        # 自動開啟網頁
        def open_browser():
            time.sleep(4)
            webbrowser.open("http://127.0.0.1:5000/")
        threading.Thread(target=open_browser, daemon=True).start()

    # 在正式打包環境中，關閉 debug 模式會更穩定
    is_debug = not getattr(sys, 'frozen', False)
    socketio.run(app, host='0.0.0.0', port=5000, debug=is_debug, allow_unsafe_werkzeug=True)
