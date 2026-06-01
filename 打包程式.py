import os
import subprocess
import sys

print("===================================================")
print("  正在準備打包成執行檔 (這會需要幾分鐘時間)")
print("===================================================")
print("\n[1/2] 檢查打包工具 (PyInstaller)...")
subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"])

print("\n[2/2] 開始打包主程式與 HAR 檔案...")
print("(使用 HAR 檔案解析，打包速度極快且檔案體積小！)")

command = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",
    "--name", "Portable派遣系統",
    "--add-data", "templates;templates",
    "--add-data", "static;static",
    "--add-data", "tprisweb.shh.org.tw.har;.",
    "--hidden-import", "engineio.async_drivers.threading",
    "app.py"
]

try:
    subprocess.check_call(command)
    print("\n===================================================")
    print(" [完成] 打包成功！")
    print("===================================================")
    print("您的執行檔已經放在資料夾內的 [dist] -> [Portable派遣系統] 裡面。")
    print("您可以將整個 [Portable派遣系統] 資料夾，直接拷貝到「沒有安裝 Python 的電腦」上執行。")
except Exception as e:
    print(f"\n打包過程中發生錯誤: {e}")

input("\n按 Enter 鍵結束...")

