import sys
import os
import threading
import time
import re
import webbrowser
import socket
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
    # 靜態資源、登入頁面與 API 同步接口不攔截
    if request.path.startswith('/static/') or request.path == '/login' or request.path == '/api/update_patients' or request.path == '/manifest.json' or request.path == '/sw.js':
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


def get_active_token():
    # 優先從環境變數取得
    token = os.environ.get('TPRIS_TOKEN')
    if token:
        return token
    
    # 若無，則以當前操作員的帳密動態登入取得
    account = os.environ.get('TPRIS_ACCOUNT')
    password = os.environ.get('TPRIS_PASSWORD')
    if account and password and account != '未設定' and password != '未設定':
        try:
            from scraper import login_and_get_token
            token = login_and_get_token(account, password)
            os.environ['TPRIS_TOKEN'] = token
            return token
        except Exception as e:
            print(f"[錯誤] 動態登入取得 Token 失敗: {e}")
    return None

def hospital_check_in(accession_no, is_check_in=True):
    """向醫院 TPRIS 系統寫回/同步報到或取消報到狀態"""
    if not accession_no:
        print("[同步警告] 醫令 AccessionNo 為空，無法寫回醫院系統報到狀態")
        return False
        
    token = get_active_token()
    if not token:
        print("[同步警告] 無法取得有效 Token，無法寫回醫院系統報到狀態")
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
            "Marge": False
        }
    else:
        payload = {
            "AccessionNos": [accession_no],
            "CheckInBackNote": "",
            "Marge": False
        }
        
    try:
        import requests
        # 關閉 SSL 驗證以防醫院內部網路凭证錯誤
        response = requests.put(url, headers=headers, json=payload, verify=False, timeout=10)
        action_name = "報到" if is_check_in else "取消報到"
        if response.status_code == 200:
            print(f"[同步成功] 成功將 {accession_no} 的{action_name}狀態寫回醫院 TPRIS 系統！")
            return True
        elif response.status_code == 401:
            # Token 過期，清除並重試一次
            print("[同步警告] Token 已過期，嘗試重新登入並重試...")
            os.environ.pop('TPRIS_TOKEN', None)
            return hospital_check_in(accession_no, is_check_in)
        else:
            print(f"[同步失敗] 醫院系統回傳狀態碼: {response.status_code}, 內容: {response.text}")
            return False
    except Exception as e:
        print(f"[同步錯誤] 連線醫院系統寫回報到狀態時發生異常: {e}")
        return False


# 存放目前的請求狀態 (簡易版，不持久化)
current_requests = {}
# 存放已經發送過的病患，避免重複出現 (使用 record_no + exam 作為唯一鍵)
sent_patients = set()
# 存放已經手動報到過的病患
checked_in_patients = set()

def sort_patients(patients):
    """排序病患：未報到 (最上端) -> 已報到 (中端) -> 已分派 (最下端)。同狀態下依 OrderNo 降序排序。"""
    # 穩定排序：先依單號降序 (新單在上)
    patients_by_date = sorted(patients, key=lambda x: x.get('order_no', ''), reverse=True)
    # 再依狀態升序 (0: 未報到, 1: 已報到, 2: 已分派)
    return sorted(patients_by_date, key=lambda x: 2 if x.get('dispatched') else (1 if x.get('checked_in') else 0))

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
    return render_template('sender.html', patients=patients_data)

@app.route('/receiver')
def receiver():
    return render_template('receiver.html')

@app.route('/mobile')
def mobile_receiver():
    return render_template('mobile_receiver.html')

@app.route('/manifest.json')
def serve_manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def serve_sw():
    response = app.make_response(app.send_static_file('sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/api/patients')
def api_patients():
    return jsonify(patients_data)

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
                
    # 3. 如果找到了配對的病患，依據語音內容執行對應動作
    if matched_patient:
        matched_record_no = str(matched_patient.get('record_no', '')).strip()
        matched_exam = str(matched_patient.get('exam', '')).strip()
        patient_key = f"{matched_record_no}|{matched_exam}"
        
        # 情況 A：語音要求取消報到
        if "取消報到" in text:
            print(f"=> [語音自動取消報到] 成功匹配病患 {matched_patient['name']} ({matched_record_no})，進行取消報到變更...")
            if patient_key in checked_in_patients:
                checked_in_patients.remove(patient_key)
            
            for p in patients_data:
                p_rec = str(p.get('record_no', '')).strip()
                p_ex = str(p.get('exam', '')).strip()
                if f"{p_rec}|{p_ex}" == patient_key:
                    p['checked_in'] = False
                    break
            
            # 非同步在背景將取消報到狀態同步至醫院 TPRIS 系統
            accession_no = matched_patient.get('accession_no')
            if accession_no:
                threading.Thread(target=lambda: hospital_check_in(accession_no, is_check_in=False), daemon=True).start()
                
            patients_data = sort_patients(patients_data)
            socketio.emit('patients_updated', patients_data)
            
            return jsonify({
                "status": "success", 
                "matched": True, 
                "patient": matched_patient,
                "action": "cancel_check_in"
            })
            
        # 情況 B：語音要求報到
        elif "報到" in text:
            print(f"=> [語音自動報到] 成功匹配病患 {matched_patient['name']} ({matched_record_no})，進行報到狀態變更...")
            checked_in_patients.add(patient_key)
            
            for p in patients_data:
                p_rec = str(p.get('record_no', '')).strip()
                p_ex = str(p.get('exam', '')).strip()
                if f"{p_rec}|{p_ex}" == patient_key:
                    p['checked_in'] = True
                    break
            
            # 非同步在背景將報到狀態同步至醫院 TPRIS 系統
            accession_no = matched_patient.get('accession_no')
            if accession_no:
                threading.Thread(target=lambda: hospital_check_in(accession_no, is_check_in=True), daemon=True).start()
                
            patients_data = sort_patients(patients_data)
            socketio.emit('patients_updated', patients_data)
            
            return jsonify({
                "status": "success", 
                "matched": True, 
                "patient": matched_patient,
                "action": "check_in"
            })
            
        # 情況 C：預設為執行自動派遣
        else:
            req_id = 'REQ-VOICE-' + str(int(time.time()))
            print(f"=> [語音自動派遣] 成功匹配病患 {matched_patient['name']} ({matched_record_no})，開始自動派遣...")
            
            # 記錄為已發送，避免重複出現在待發送清單中
            sent_patients.add(patient_key)
            
            # 不要從全域剔除，改為標記已分派，並推播更新發送端畫面
            matched_patient['dispatched'] = True
            for p in patients_data:
                p_rec = str(p.get('record_no', '')).strip()
                p_ex = str(p.get('exam', '')).strip()
                if f"{p_rec}|{p_ex}" == patient_key:
                    p['dispatched'] = True
                    break
            patients_data = sort_patients(patients_data)
            socketio.emit('patients_updated', patients_data)
            
            # 廣播新派遣請求給接收端 (Receiver)
            socketio.emit('new_request', {'id': req_id, 'patient': matched_patient})
            current_requests[req_id] = "waiting"
            
            # 4. 分析對話中是否有接受/確認/抵達等肯定的意思
            is_confirm = any(word in text for word in ["接受", "確認", "好的", "收到了", "10分鐘", "十分鐘", "行", "可以", "照"])
            if is_confirm:
                current_requests[req_id] = "confirmed"
                socketio.emit('request_confirmed', {'id': req_id})
                print(f"=> [語音自動確認] 對話中偵測到肯定語意，已為其自動核准派遣！")
                
            return jsonify({
                "status": "success", 
                "matched": True, 
                "patient": matched_patient,
                "action": "dispatched_and_confirmed" if is_confirm else "dispatched"
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
            
            patient_key = f"{record_no}|{exam}"
            # 優先保留醫院端的已報到狀態 (如 status == '21')，或本系統手動/語音報到的狀態
            p['checked_in'] = p.get('checked_in', False) or (patient_key in checked_in_patients)
            p['dispatched'] = p.get('dispatched', False) or (patient_key in sent_patients)
            filtered_data.append(p)
                
        patients_data = sort_patients(filtered_data)
        socketio.emit('patients_updated', patients_data)
        return jsonify({"status": "success", "count": len(patients_data)})
    return jsonify({"status": "error"}), 400

# 發送端發出請求
@socketio.on('send_request')
def handle_request(data):
    global patients_data
    request_id = data.get('id')
    patient_info = data.get('patient')
    current_requests[request_id] = "waiting"
    
    if patient_info:
        # 記錄為已發送
        record_no = str(patient_info.get('record_no') or '').strip()
        exam = str(patient_info.get('exam') or '').strip()
        patient_key = f"{record_no}|{exam}"
        sent_patients.add(patient_key)
        
        # 不要從全域剔除，改為標記已分派，並發送推播更新所有發送端畫面
        for p in patients_data:
            p_rec = str(p.get('record_no') or '').strip()
            p_ex = str(p.get('exam') or '').strip()
            if f"{p_rec}|{p_ex}" == patient_key:
                p['dispatched'] = True
                break
        patients_data = sort_patients(patients_data)
        socketio.emit('patients_updated', patients_data)
    
    patient_name = patient_info.get('name') if patient_info else 'Unknown'
    print(f"收到請求: {request_id} (病患: {patient_name})")
    # 推播給接收端
    emit('new_request', {'id': request_id, 'patient': patient_info}, broadcast=True)

# 接收端按下確認
@socketio.on('confirm_request')
def handle_confirm(data):
    request_id = data.get('id')
    if request_id in current_requests:
        current_requests[request_id] = "confirmed"
        print(f"請求已確認: {request_id}")
        # 通知發送端
        emit('request_confirmed', {'id': request_id}, broadcast=True)

# 手動報到請求
@socketio.on('check_in_patient')
def handle_check_in(data):
    global patients_data
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    patient_key = f"{record_no}|{exam}"
    
    checked_in_patients.add(patient_key)
    
    # 在記憶體中更新目前病患狀態
    accession_no = None
    for p in patients_data:
        p_record = str(p.get('record_no') or '').strip()
        p_exam = str(p.get('exam') or '').strip()
        if p_record == record_no and p_exam == exam:
            p['checked_in'] = True
            accession_no = p.get('accession_no')
            break
            
    print(f"病患已手動報到: {record_no} (項目: {exam})")
    
    # 非同步在背景將報到狀態同步至醫院 TPRIS 系統
    if accession_no:
        def do_sync():
            hospital_check_in(accession_no, is_check_in=True)
        threading.Thread(target=do_sync, daemon=True).start()
        
    patients_data = sort_patients(patients_data)
    # 廣播給所有發送端更新畫面
    socketio.emit('patients_updated', patients_data)

# 取消手動報到請求
@socketio.on('cancel_check_in_patient')
def handle_cancel_check_in(data):
    global patients_data
    record_no = str(data.get('record_no') or '').strip()
    exam = str(data.get('exam') or '').strip()
    patient_key = f"{record_no}|{exam}"
    
    if patient_key in checked_in_patients:
        checked_in_patients.remove(patient_key)
        
    # 在記憶體中更新目前病患狀態
    accession_no = None
    for p in patients_data:
        p_record = str(p.get('record_no') or '').strip()
        p_exam = str(p.get('exam') or '').strip()
        if p_record == record_no and p_exam == exam:
            p['checked_in'] = False
            accession_no = p.get('accession_no')
            break
            
    print(f"病患已取消手動報到: {record_no} (項目: {exam})")
    
    # 非同步在背景將取消報到狀態同步至醫院 TPRIS 系統
    if accession_no:
        def do_sync():
            hospital_check_in(accession_no, is_check_in=False)
        threading.Thread(target=do_sync, daemon=True).start()
        
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
