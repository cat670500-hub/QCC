import subprocess
import sys

def main():
    print("="*50)
    print("      Portable 醫療派遣系統 - 自動啟動程序      ")
    print("==================================================")
    print("\n[系統] 正在啟動主伺服器 (app.py)...")
    print("[系統] 伺服器啟動後，將自動開啟瀏覽器並啟動背景爬蟲程式。")
    print("[系統] 若要關閉系統，請直接關閉此視窗，或按下 Ctrl+C。\n")
    
    try:
        # 啟動 app.py，它會自動開啟瀏覽器並啟動背景爬蟲，避免重複執行與開啟多個視窗
        subprocess.run([sys.executable, "app.py"])
    except KeyboardInterrupt:
        print("\n[系統] 收到關閉指令，系統已安全關閉。")

if __name__ == "__main__":
    main()

