@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================
echo   ZRG Oblivion Bot — Windows start
echo ========================================
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: pip install failed. Check Python installation.
  pause
  exit /b 1
)
echo.
echo Starting bot with auto-restart...
python run_forever.py
pause
