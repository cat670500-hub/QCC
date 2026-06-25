import sys

# 優先啟動 gevent 猴子補丁以支援協程，徹底避免 Windows 環境下 HTTPS / Socket.IO 的執行緒死鎖問題
has_gevent = False
if not getattr(sys, 'frozen', False):
    try:
        from gevent import monkey
        monkey.patch_all()
        print("[系統] 已啟用 gevent 協程與猴子補丁支援！")
        has_gevent = True
        
        # 覆寫 gevent Hub 的錯誤處理以靜音 SSL 自簽憑證警告所引發的 SSLError 堆疊追蹤
        try:
            from gevent.hub import Hub
            original_handle_error = Hub.handle_error
            
            def custom_hub_handle_error(self, context, type, value, tb):
                import ssl
                # 判斷是否為 SSL 握手相關錯誤（例如手機端不信任自簽憑證產生的 sslv3 alert 警告）
                if type is not None and (issubclass(type, ssl.SSLError) or "SSLError" in type.__name__ or "sslv3 alert" in str(value)):
                    # 已靜音自簽憑證未授信之握手錯誤，不輸出任何日誌以避免洗版
                    return
                return original_handle_error(self, context, type, value, tb)
                
            Hub.handle_error = custom_hub_handle_error
            print("[系統] 已啟用 gevent 全域 SSL 錯誤抑制機制！")
        except Exception as e:
            print(f"[系統警告] 啟用 gevent 全域 SSL 錯誤抑制失敗: {e}")
            
        # 啟用 SSL 雙模 (HTTP + HTTPS 同埠相容與自動重定向) 支援
        try:
            import gevent.server
            import socket
            import ssl
            from urllib.parse import urlparse
            
            original_wrap_socket_and_handle = gevent.server.StreamServer.wrap_socket_and_handle
            
            def custom_wrap_socket_and_handle(self, client_socket, address):
                if hasattr(self, 'wrap_socket'):
                    first_byte = b''
                    try:
                        # 協程非阻塞 Socket 必須等待資料可讀再進行 peek，以防直接返回 BlockingIOError (b'')
                        # 使用較長超時時間 (30 秒) 以容納瀏覽器預連線 (speculative connection)
                        from gevent.select import select
                        ready = select([client_socket], [], [], 30.0)
                        if ready[0]:
                            first_byte = client_socket.recv(1, socket.MSG_PEEK)
                        else:
                            first_byte = b''
                    except Exception:
                        first_byte = b''
                    
                    # 若為預建連線超時、斷線或無資料發送，直接關閉 socket 並返回，避免進入 SSL 握手導致拋出 SSLError
                    if not first_byte:
                        try:
                            client_socket.close()
                        except Exception:
                            pass
                        return
                    
                    if first_byte != b'\x16' and first_byte != b'\x80':
                        # 說明是明文 HTTP 請求，直接以明文處理，不再強制進行 HTTPS 重定向。
                        # 這可以讓不支援或無法信任自簽憑證的手機 Chrome 正常登入與使用系統。
                        try:
                            self.handle(client_socket, address)
                        except Exception as e:
                            print(f"[系統雙模錯誤] 處理明文請求失敗: {e}")
                        return
                
                try:
                    return original_wrap_socket_and_handle(self, client_socket, address)
                except ssl.SSLError as e:
                    # 靜音常見的 SSL 握手錯誤（例如自簽憑證未被手機信任），避免日誌洗版
                    try:
                        client_socket.close()
                    except Exception:
                        pass
                    return
                except Exception as e:
                    # 靜音其他連線例外
                    try:
                        client_socket.close()
                    except Exception:
                        pass
                    return
                
            gevent.server.StreamServer.wrap_socket_and_handle = custom_wrap_socket_and_handle
            print("[系統] 已啟用 SSL 雙模並存與錯誤抑制機制！")
        except Exception as e:
            print(f"[系統警告] 啟用 SSL 雙模相容失敗: {e}")
    except ImportError:
        pass

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

if has_gevent:
    # 協程模式下，原生支援 WebSocket 連線，不需限制為 polling 模式
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
else:
    # 執行緒模式下限制為 polling 模式，避免 Windows SSL 握手死鎖
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', transports=['polling'])

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
        'port': 5000,
        'protocol': request.scheme
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

def log_voice_call(text, matched_patient=None, phone_number="未知"):
    try:
        time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        if matched_patient:
            name = matched_patient.get('name', '未知')
            rec_no = matched_patient.get('record_no', '未知')
            bed = matched_patient.get('bed', '無')
            log_line = f"[{time_str}] 來電: {phone_number} | 語音:「{text}」 | 已配對: {name} ({rec_no}) - 床號: {bed}\n"
        else:
            log_line = f"[{time_str}] 來電: {phone_number} | 語音:「{text}」 | 未配對病患\n"
        with open("voice_calls.log", "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[警告] 寫入語音來電日誌失敗: {e}")

def get_voice_logs_list():
    log_file = "voice_calls.log"
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.strip() for line in lines[-100:]]
    except Exception:
        return []

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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Portable 語音派遣系統</title>
        <link rel="stylesheet" href="/static/css/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Outfit', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 0;
            }
            .index-container {
                background: rgba(30, 41, 59, 0.7);
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 24px;
                padding: 2.5rem 2rem;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                text-align: center;
                width: 90%;
                max-width: 450px;
                color: #f8fafc;
            }
            .index-title {
                font-size: 1.8rem;
                font-weight: 700;
                margin-bottom: 2rem;
                background: linear-gradient(to right, #38bdf8, #34d399);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .index-btn {
                background: linear-gradient(135deg, #0ea5e9, #0284c7);
                color: white;
                border: none;
                padding: 14px 24px;
                border-radius: 14px;
                font-size: 1.05rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
            }
            .index-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(14, 165, 233, 0.4);
                background: linear-gradient(135deg, #38bdf8, #0ea5e9);
            }
            .index-btn:active {
                transform: translateY(0);
            }
            .btn-link {
                text-decoration: none;
                width: 100%;
            }
            .btn-group {
                display: flex;
                flex-direction: column;
                gap: 16px;
            }
        </style>
    </head>
    <body>
        <div class="index-container">
            <h1 class="index-title">🏥 Portable 語音派遣系統</h1>
            <div class="btn-group">
                <a href="/sender" class="btn-link">
                    <button class="index-btn">💻 前往發送端 (Sender)</button>
                </a>
                <a href="/mobile" class="btn-link">
                    <button class="index-btn" style="background: linear-gradient(135deg, #10b981, #059669); box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);">📱 前往手機接收端 (Mobile)</button>
                </a>
                <a href="/receiver" class="btn-link">
                    <button class="index-btn" style="background: linear-gradient(135deg, #6366f1, #4f46e5); box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);">🖥️ 前往接收端 (Receiver)</button>
                </a>
            </div>
        </div>
    </body>
    </html>
    '''

patients_data = [
    {
        "name": "王大同",
        "record_no": "12345678",
        "bed": "11B01",
        "exam": "Chest(AP)Portable",
        "source": "住院",
        "accession_no": "ACC12345678",
        "order_no": "ORD12345678",
        "checked_in": False,
        "dispatched": False,
        "voice_mentioned": False
    },
    {
        "name": "李小美",
        "record_no": "87654321",
        "bed": "急診",
        "exam": "KUB",
        "source": "急診",
        "accession_no": "ACC87654321",
        "order_no": "ORD87654321",
        "checked_in": False,
        "dispatched": False,
        "voice_mentioned": False
    }
]

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
            p['voice_alert'] = None
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

@app.route('/api/upload_recording', methods=['POST'])
def upload_recording():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "無上傳檔案"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "檔名為空"}), 400
    
    from werkzeug.utils import secure_filename
    os.makedirs('recordings', exist_ok=True)
    filename = secure_filename(file.filename)
    filepath = os.path.join('recordings', filename)
    file.save(filepath)
    print(f"[錄音上傳] 已成功接收並儲存通話錄音檔: {filepath}")
    return jsonify({"status": "success", "filepath": filepath})

@app.route('/api/pending_check_ins', methods=['GET'])
def get_pending_check_ins():
    global pending_hospital_check_ins
    check_ins = list(pending_hospital_check_ins)
    pending_hospital_check_ins.clear()
    return jsonify(check_ins)

def is_fuzzy_name_match(text, patient_name):
    """
    模糊比對中文姓名，容許語音辨識同音字誤差 (如「李小美」與「李小妹」比對)
    """
    if not text or not patient_name:
        return False
    text = str(text).lower()
    patient_name = str(patient_name).lower()
    
    if patient_name in text:
        return True
        
    name_len = len(patient_name)
    if name_len >= 2:
        for i in range(len(text) - name_len + 1):
            sub_str = text[i:i+name_len]
            match_count = sum(1 for a, b in zip(sub_str, patient_name) if a == b)
            threshold = name_len if name_len == 2 else name_len - 1
            if match_count >= threshold:
                return True
    return False

def is_fuzzy_bed_match(text, bed_no):
    """
    模糊比對床號，處理常見的語音辨識英文與數字誤差 (例如: 11B01 辨識為 11比01 或 十一逼洞么)
    """
    if not text or not bed_no:
        return False
        
    # 去除所有空白與轉小寫
    import re
    text_clean = str(text).replace(" ", "").replace("　", "").lower()
    bed_clean = str(bed_no).replace(" ", "").replace("　", "").lower()
    
    # 處理雙位數特例 (必須在單一數字轉換前執行)
    text_clean = text_clean.replace("二十", "20")
    text_clean = text_clean.replace("三十", "30")
    text_clean = text_clean.replace("四十", "40")
    text_clean = text_clean.replace("五十", "50")
    text_clean = text_clean.replace("六十", "60")
    text_clean = text_clean.replace("七十", "70")
    text_clean = text_clean.replace("八十", "80")
    text_clean = text_clean.replace("九十", "90")
    text_clean = text_clean.replace("十一", "11")
    text_clean = text_clean.replace("十二", "12")
    text_clean = text_clean.replace("十三", "13")
    text_clean = text_clean.replace("十四", "14")
    text_clean = text_clean.replace("十五", "15")
    text_clean = text_clean.replace("十六", "16")
    text_clean = text_clean.replace("十七", "17")
    text_clean = text_clean.replace("十八", "18")
    text_clean = text_clean.replace("十九", "19")
    text_clean = re.sub(r'[十石時實食]', '10', text_clean)
    
    # 針對台灣護理人員常見發音的語音誤判進行正規化 (英文字母)
    text_clean = re.sub(r'[欸誒黑]', 'a', text_clean)
    text_clean = re.sub(r'[比逼嗶幣必壁閉鼻筆避臂]', 'b', text_clean)
    text_clean = re.sub(r'[西吸希洗細戲系]', 'c', text_clean)
    text_clean = re.sub(r'[低滴豬弟地底第]', 'd', text_clean)
    text_clean = re.sub(r'[伊依醫衣易]', 'e', text_clean)
    text_clean = re.sub(r'[欸夫]', 'f', text_clean)
    text_clean = re.sub(r'[居雞機基吉]', 'g', text_clean)
    text_clean = re.sub(r'[欸取]', 'h', text_clean)
    text_clean = re.sub(r'[愛]', 'i', text_clean)
    text_clean = re.sub(r'[賊街接]', 'j', text_clean)
    text_clean = re.sub(r'[虧客]', 'k', text_clean)
    text_clean = re.sub(r'[欸樓]', 'l', text_clean)
    text_clean = re.sub(r'[欸母]', 'm', text_clean)
    text_clean = re.sub(r'[恩]', 'n', text_clean)
    text_clean = re.sub(r'[歐偶]', 'o', text_clean)
    text_clean = re.sub(r'[批屁劈]', 'p', text_clean)
    text_clean = re.sub(r'[區去取]', 'q', text_clean)
    text_clean = re.sub(r'[阿啊]', 'r', text_clean)
    text_clean = re.sub(r'[欸死斯絲]', 's', text_clean)
    text_clean = re.sub(r'[梯踢體]', 't', text_clean)
    text_clean = re.sub(r'[優油]', 'u', text_clean)
    text_clean = re.sub(r'[微威]', 'v', text_clean)
    text_clean = re.sub(r'[大波溜]', 'w', text_clean)
    text_clean = re.sub(r'[欸克斯]', 'x', text_clean)
    text_clean = re.sub(r'[歪外]', 'y', text_clean)
    text_clean = re.sub(r'[立力麗]', 'z', text_clean)
    
    # 特殊的連音誤判 (十一B 聽起來像 CB)
    text_clean = text_clean.replace("cb", "11b")
    text_clean = text_clean.replace("ca", "11a")
    text_clean = text_clean.replace("cc", "11c")
    
    # 數字軍警用與常見發音
    text_clean = re.sub(r'[洞動棟零林鈴靈]', '0', text_clean)
    text_clean = re.sub(r'[么要一以已義意]', '1', text_clean) # 移除了"伊依"，因為它們已配對到'e'
    text_clean = re.sub(r'[兩二兒耳而]', '2', text_clean)
    text_clean = re.sub(r'[散山三傘]', '3', text_clean)
    text_clean = re.sub(r'[速事寺四死獅]', '4', text_clean)
    text_clean = re.sub(r'[無舞五屋物誤]', '5', text_clean)
    text_clean = re.sub(r'[溜流六路綠]', '6', text_clean)
    text_clean = re.sub(r'[拐漆七起氣妻]', '7', text_clean)
    text_clean = re.sub(r'[杯八把爸霸吧]', '8', text_clean)
    text_clean = re.sub(r'[勾狗酒九久舊舅]', '9', text_clean)
    
    # 處理急診的常見語音誤判
    text_clean = re.sub(r'[極吉級幾集即急][疹診整]', '急診', text_clean)
    
    # 移除常見的口語贅字與奇怪的辨識結果 (如「床頭板」被聽成「臭豆腐」)
    fluff_pattern = r'[樓床房號室區的那個這有在幫我照一下位病患臭豆腐蘿蔔老婆豆pro]'
    text_clean = re.sub(fluff_pattern, '', text_clean)
    bed_clean = re.sub(fluff_pattern, '', bed_clean)
    
    # 針對英文字母後面的「0」進行防呆正規化 (例如 11B01 和 11B1 應該要能互通)
    # 把字母後面的 0 拔掉，讓 11b01 變成 11b1
    text_clean = re.sub(r'([a-z])0+(\d)', r'\1\2', text_clean)
    bed_clean = re.sub(r'([a-z])0+(\d)', r'\1\2', bed_clean)
    
    if bed_clean in text_clean:
        return True
        
    return False

@app.route('/api/voice_dispatch', methods=['POST'])
def voice_dispatch():
    global patients_data
    data = request.get_json()
    text = data.get('text', '')
    phone_number = data.get('phone_number', '未知')
    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400
        
    print(f"[{time.strftime('%H:%M:%S')}] 收到來電: {phone_number}, 語音對話: {text}")
    
    # 進行對話分析，並 cross-reference 目前爬蟲抓到的病患清單
    matched_patients = []
    
    # 1. 先用病歷號比對 (6-10 位數字)
    record_numbers = re.findall(r'\d{6,10}', text)
    if record_numbers:
        for r_no in record_numbers:
            r_no_clean = str(r_no).strip()
            for p in patients_data:
                if str(p.get('record_no', '')).strip() == r_no_clean:
                    matched_patients.append(p)
                    
    # 2. 如果病歷號沒配對到，用病患姓名比對
    if not matched_patients:
        for p in patients_data:
            p_name = str(p.get('name', '')).strip()
            if p_name and is_fuzzy_name_match(text, p_name):
                matched_patients.append(p)
                
    # 3. 如果姓名也沒配對到，用床號比對
    if not matched_patients:
        for p in patients_data:
            p_bed = str(p.get('bed', '')).strip()
            if p_bed and p_bed != "(無病房資料)" and len(p_bed) >= 2 and is_fuzzy_bed_match(text, p_bed):
                matched_patients.append(p)
                
    # 永遠紀錄語音歷程，方便除錯與追蹤 (取第一筆代表)
    first_match = matched_patients[0] if matched_patients else None
    log_voice_call(text, first_match, phone_number)
                
    # 4. 如果找到了配對的病患，根據語音內容判斷是否觸發動作
    if matched_patients:
        alert_text = "🚨 需照相"
        
        # 標記所有匹配到的病患
        for mp in matched_patients:
            matched_record_no = str(mp.get('record_no', '')).strip()
            matched_exam = str(mp.get('exam', '')).strip()
            matched_acc = str(mp.get('accession_no', '')).strip()
            matched_ord = str(mp.get('order_no', '')).strip()
            matched_req = matched_acc if matched_acc else matched_ord
            patient_key = f"{matched_record_no}|{matched_exam}|{matched_req}"
            
            for p in patients_data:
                p_rec = str(p.get('record_no', '')).strip()
                p_ex = str(p.get('exam', '')).strip()
                p_acc = str(p.get('accession_no', '')).strip()
                p_ord = str(p.get('order_no', '')).strip()
                p_req = p_acc if p_acc else p_ord
                if f"{p_rec}|{p_ex}|{p_req}" == patient_key:
                    p['voice_mentioned'] = True
                    p['voice_alert'] = alert_text
                    break
                
        patients_data = sort_patients(patients_data)
        socketio.emit('patients_updated', patients_data)
        socketio.emit('voice_logs_updated', get_voice_logs_list())
        
        print(f"[語音提示] 來電語音提到病患 (共 {len(matched_patients)} 位)，更新卡片高亮狀態。")
        # 根據您的需求，取消畫面中央的彈出提醒，直接以卡片高亮標示即可
        # socketio.emit('voice_mention_alert', {
        #     'patient': matched_patients[0],
        #     'text': text
        # })
            
        return jsonify({
            "status": "success", 
            "matched": True, 
            "patient": matched_patients[0],
            "action": "voice_mentioned"
        })
        
    log_voice_call(text, None, phone_number)
    socketio.emit('voice_logs_updated', get_voice_logs_list())
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
            existing_voice_alert = None
            for old_p in patients_data:
                old_rec = old_p.get('record_no')
                old_ex = old_p.get('exam')
                old_acc = old_p.get('accession_no')
                old_ord = old_p.get('order_no')
                old_req = old_acc if old_acc else old_ord
                if f"{old_rec}|{old_ex}|{old_req}" == patient_key:
                    existing_voice_mentioned = old_p.get('voice_mentioned', False)
                    existing_voice_alert = old_p.get('voice_alert')
                    break
            p['voice_mentioned'] = p.get('voice_mentioned', False) or existing_voice_mentioned
            p['voice_alert'] = p.get('voice_alert') or existing_voice_alert
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

@app.route('/api/voice_logs', methods=['GET'])
def get_voice_logs():
    return jsonify(get_voice_logs_list())

@app.route('/api/clear_errors', methods=['POST'])
def clear_errors():
    for log_file in ["sync_errors.log", "check_in_errors.log", "voice_calls.log"]:
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
    global patients_data
    acc_no = data.get("accession_no")
    is_check = data.get("is_check_in", True)
    success = data.get("success", False)
    msg = data.get("message", "")
    action = "報到" if is_check else "取消報到"
    
    print(f"[系統] 收到代理端回報執行結果: 單號={acc_no}, {action} 成功={success}, 訊息={msg}")
    
    if not success and acc_no:
        log_server_sync_error(acc_no, action, msg)
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
                p['voice_mentioned'] = False
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
            p['voice_mentioned'] = False
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
            p['voice_mentioned'] = False
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
        
        # 檢查並清理佔用 port 5000 的程序，避免 WinError 10048 錯誤
        def kill_port_owner(port):
            import subprocess
            import os
            import time
            try:
                cmd = "netstat -ano"
                result = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
                pids = set()
                for line in result.split('\n'):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                pids.add(int(pid))
                            except ValueError:
                                pass
                
                current_pid = os.getpid()
                for pid in pids:
                    if pid != current_pid and pid > 0:
                        print(f"[系統] 偵測到連接埠 {port} 被其它程序 (PID: {pid}) 佔用，正在嘗試自動強制結束該程序以釋放連接埠...")
                        subprocess.call(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(1.5) # 等待作業系統釋放埠口
            except Exception as e:
                print(f"[系統警告] 無法自動釋放佔用的連接埠: {e}")

        kill_port_owner(5000)
        
        # 使用 Thread 啟動爬蟲，避免 PyInstaller subprocess 產生 fork bomb
        from scraper import run_scraper
        def background_scraper():
            time.sleep(3) # 等待 Flask 啟動
            try:
                # 若啟用 SSL，動態修改爬蟲的對接 API URL 為 HTTPS 模式
                if os.path.exists('cert.pem') and os.path.exists('key.pem'):
                    os.environ["FLASK_API_URL"] = "https://127.0.0.1:5000/api/update_patients"
                run_scraper()
            except Exception as e:
                print(f"爬蟲執行發生錯誤: {e}")
                
        threading.Thread(target=background_scraper, daemon=True).start()
        
        # 自動開啟網頁
        def open_browser():
            time.sleep(4)
            proto = 'https' if (os.path.exists('cert.pem') and os.path.exists('key.pem')) else 'http'
            webbrowser.open(f"{proto}://127.0.0.1:5000/")
        threading.Thread(target=open_browser, daemon=True).start()

        # 啟動每日 00:00 自動銷毀錄音檔案的背景排程
        import datetime
        import shutil
        def background_recordings_cleaner():
            while True:
                now = datetime.datetime.now()
                tomorrow = now.date() + datetime.timedelta(days=1)
                midnight = datetime.datetime.combine(tomorrow, datetime.time.min)
                sleep_seconds = (midnight - now).total_seconds()
                
                # 若已經到了午夜，先執行清理
                if sleep_seconds <= 1 or now >= midnight:
                    try:
                        recordings_dir = "recordings"
                        if os.path.exists(recordings_dir):
                            for filename in os.listdir(recordings_dir):
                                file_path = os.path.join(recordings_dir, filename)
                                if os.path.isfile(file_path) or os.path.islink(file_path):
                                    os.unlink(file_path)
                                elif os.path.isdir(file_path):
                                    shutil.rmtree(file_path)
                            print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [清理排程] 成功清理每日午夜過期錄音檔案！")
                    except Exception as e:
                        print(f"[清理排程警告] 執行每日清理時發生錯誤: {e}")
                    
                    # 重新計算下一個午夜
                    now = datetime.datetime.now()
                    tomorrow = now.date() + datetime.timedelta(days=1)
                    midnight = datetime.datetime.combine(tomorrow, datetime.time.min)
                    sleep_seconds = (midnight - now).total_seconds()

                time.sleep(min(sleep_seconds, 60))
                
        threading.Thread(target=background_recordings_cleaner, daemon=True).start()

    # 在正式打包環境中，關閉 debug 模式會更穩定
    is_debug = False
    
    ssl_cert = 'cert.pem'
    ssl_key = 'key.pem'
    if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
        print(f"[系統] 偵測到 SSL 憑證，將以安全連線 (HTTPS) 模式啟動主伺服器！")
        if has_gevent:
            # gevent 需要傳入 ssl.SSLContext 物件而非路徑元組
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)
            socketio.run(app, host='0.0.0.0', port=5000, debug=is_debug, ssl_context=context)
        else:
            socketio.run(app, host='0.0.0.0', port=5000, debug=is_debug, allow_unsafe_werkzeug=True, ssl_context=(ssl_cert, ssl_key))
    else:
        socketio.run(app, host='0.0.0.0', port=5000, debug=is_debug, allow_unsafe_werkzeug=True)
