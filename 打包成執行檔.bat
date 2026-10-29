@echo off
chcp 65001 >nul
echo ===================================================
echo   正在準備打包程式 (這會需要數十秒時間)
echo ===================================================
echo.
echo [1/2] 檢查打包工具 (PyInstaller)...
python -m pip install --disable-pip-version-check pyinstaller
echo.
echo [2/2] 開始打包主程式 Portable派遣系統...
python -m PyInstaller --noconfirm build_app.spec
echo.
echo 複製必要憑證與設定檔至 dist 目錄...
copy cert.pem dist\Portable派遣系統\ >nul 2>&1
copy key.pem dist\Portable派遣系統\ >nul 2>&1
if exist .env copy .env dist\Portable派遣系統\ >nul 2>&1
if exist settings.json copy settings.json dist\Portable派遣系統\ >nul 2>&1
if exist sms_settings.json copy sms_settings.json dist\Portable派遣系統\ >nul 2>&1
echo.
echo ===================================================
echo 打包完成！
echo ===================================================
echo 您的執行檔已生成於資料夾 [dist] -> [Portable派遣系統] 中。
echo 您可以將整個 [Portable派遣系統] 資料夾複製到未安裝 Python 的電腦上直接使用。
echo.
pause
