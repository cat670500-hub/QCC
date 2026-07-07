@echo off
chcp 65001 >nul
echo ===================================================
echo   正在準備打包成執行檔 (這會需要幾分鐘時間)
echo ===================================================
echo.
echo [1/3] 安裝打包工具 (PyInstaller)...
python -m pip install --disable-pip-version-check pyinstaller

echo.
echo [2/3] 開始打包主程式與 Chromium 瀏覽器...
echo (這會把 Playwright 瀏覽器一起打包進去，檔案會有點大，請耐心等候)
python -m PyInstaller --noconfirm --onedir --name "Portable派遣系統" --hidden-import engineio.async_drivers.threading --add-data "templates;templates" --add-data "static;static" --add-data "%LOCALAPPDATA%\ms-playwright;ms-playwright" app.py

echo.
echo ===================================================
echo [3/3] 打包完成！
echo ===================================================
echo 您的執行檔已經放在資料夾內的 [dist] -> [Portable派遣系統] 裡面。
echo 您可以將整個 [Portable派遣系統] 資料夾，直接拷貝到「沒有安裝 Python 的電腦」上執行。
echo.
pause
