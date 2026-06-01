import sys
import os
import threading
import time
import re
import webbrowser
from flask import Flask, render_template, jsonify, request
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

# 存放目前的請求狀態 (簡易版，不持久化)
current_requests = {}
# 存放已經發送過的病患，避免重複出現 (使用 record_no + exam 作為唯一鍵)
sent_patients = set()
# 存放已經手動報到過的病患
checked_in_patients = set()

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
            for p in patients_data:
                if p.get('record_no') == r_no:
                    matched_patient = p
                    break
            if matched_patient:
                break
                
    # 2. 如果病歷號沒配對到，用病患姓名比對
    if not matched_patient:
        for p in patients_data:
            p_name = p.get('name')
            if p_name and p_name in text:
                matched_patient = p
                break
                
    # 3. 如果找到了配對的病患，自動執行派遣
    if matched_patient:
        req_id = 'REQ-VOICE-' + str(int(time.time()))
        print(f"=> [語音自動派遣] 成功匹配病患 {matched_patient['name']} ({matched_patient['record_no']})，開始自動派遣...")
        
        # 記錄為已發送，避免重複出現在待發送清單中
        patient_key = f"{matched_patient.get('record_no')}|{matched_patient.get('exam')}"
        sent_patients.add(patient_key)
        
        # 從全局待發送名單中剔除，並推播更新發送端畫面
        patients_data = [p for p in patients_data if f"{p.get('record_no')}|{p.get('exam')}" != patient_key]
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
        "matched": false, 
        "message": "在待發送名單中找不到符合的病患或病歷號"
    })

@app.route('/api/update_patients', methods=['POST'])
def update_patients():
    global patients_data
    data = request.get_json()
    if data is not None:
        # 過濾掉已經發送過的病患
        filtered_data = []
        for p in data:
            patient_key = f"{p.get('record_no')}|{p.get('exam')}"
            if patient_key not in sent_patients:
                # 標記病患是否已報到
                p['checked_in'] = (patient_key in checked_in_patients)
                filtered_data.append(p)
                
        patients_data = filtered_data
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
        patient_key = f"{patient_info.get('record_no')}|{patient_info.get('exam')}"
        sent_patients.add(patient_key)
        
        # 立刻從全局 patients_data 剔除，並發送推播更新所有發送端畫面
        patients_data = [p for p in patients_data if f"{p.get('record_no')}|{p.get('exam')}" != patient_key]
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
    record_no = data.get('record_no')
    exam = data.get('exam')
    patient_key = f"{record_no}|{exam}"
    
    checked_in_patients.add(patient_key)
    
    # 在記憶體中更新目前病患狀態
    for p in patients_data:
        if p.get('record_no') == record_no and p.get('exam') == exam:
            p['checked_in'] = True
            break
            
    print(f"病患已手動報到: {record_no} (項目: {exam})")
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
