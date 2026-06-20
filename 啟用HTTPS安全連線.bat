@echo off
chcp 65001 >nul
echo ===================================================
echo   Portable 醫療派遣系統 - 啟用 HTTPS 安全連線
echo   (iOS / Android 手機麥克風與語音功能支援)
echo ===================================================
echo.
echo 此動作將會下載安裝 SSL 憑證產生套件，並自動在本機生成安全連線憑證。
echo 啟用後，iOS (iPhone/iPad) 與手機端即可安全啟用麥克風與語音指令功能。
echo.
pause
python generate_cert.py
echo.
echo 啟用完成！請直接執行「啟動系統.bat」重新啟動系統。
echo.
pause
