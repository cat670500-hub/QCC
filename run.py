import subprocess
import webbrowser
import time
import sys

def main():
    print("="*40)
    print(" Portable 醫療派遣系統 - 自動啟動程序 ")
    print("="*40)
    
    print("[1/3] 正在啟動後端伺服器 (app.py)...")
    flask_process = subprocess.Popen([sys.executable, "app.py"])
    
    print("[2/3] 等待伺服器就緒...")
    time.sleep(3) # 等待 Flask 啟動
    
    print("[3/3] 開啟網頁與自動爬蟲 (scraper.py)...")
    webbrowser.open("http://127.0.0.1:5000/")
    scraper_process = subprocess.Popen([sys.executable, "scraper.py"])
    
    print("\n系統已全面啟動！您可以直接在瀏覽器中操作。")
    print("若要關閉系統，請直接關閉此終端機視窗，或按下 Ctrl+C。")
    
    try:
        # 保持主程式執行，並監控子程序
        flask_process.wait()
        scraper_process.wait()
    except KeyboardInterrupt:
        print("\n收到關閉指令，正在終止所有服務...")
        flask_process.terminate()
        scraper_process.terminate()
        print("系統已安全關閉。")

if __name__ == "__main__":
    main()
