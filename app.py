import sys
import os
import threading
import time
import webbrowser
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

# 判斷是否為 PyInstaller 打包後的執行檔
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    # 讓 Playwright 讀取打包進來的瀏覽器
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(sys._MEIPASS, 'ms-playwright')
else:
    app = Flask(__name__)

app.config['SECRET_KEY'] = 'hospital-secret!'
# 明確指定 async_mode='threading' 避免 PyInstaller 打包後找不到非同步驅動
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 存放目前的請求狀態 (簡易版，不持久化)
current_requests = {}
# 存放已經發送過的病患，避免重複出現 (使用 record_no + exam 作為唯一鍵)
sent_patients = set()

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
