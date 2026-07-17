@echo off
rem ============================================================
rem  QoE Normalizer local web app launcher (Windows) - execution shell.
rem  What it does: (1) check Python/deps (2) start web server (3) open browser.
rem  Does NOT reimplement the pipeline/web logic - only calls python -m src.web.app.
rem  The 2 API keys are entered in the web screen (do NOT put keys in this script).
rem  Note: on-screen messages are ASCII-only on purpose to avoid console encoding issues.
rem ============================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo    QoE Normalizer - starting
echo ============================================
echo.

rem --- 1) Python check (prefer py launcher -> fallback to python) ---
set "PYEXE=py -3"
py -3 --version >nul 2>&1
if errorlevel 1 (
  set "PYEXE=python"
  python --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Python not found.
    echo   1. Install Python 3 from https://www.python.org
    echo   2. On the installer screen, be sure to check "Add Python to PATH".
    echo   3. After installing, run this file again.
    echo.
    pause
    exit /b 1
  )
)

rem --- 2) Dependency check (try importing flask; install once if missing) ---
%PYEXE% -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Required libraries are missing. Installing them once...
  %PYEXE% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install libraries.
    echo   Check your internet connection, or run this manually:
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
)

rem --- 3) Port 5000 check (if already in use, just open the browser instead) ---
netstat -ano | findstr /c:":5000 " | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [INFO] Port 5000 is already in use. The web app may already be running.
  echo        Opening browser to the existing server: http://127.0.0.1:5000
  start "" "http://127.0.0.1:5000"
  echo.
  pause
  exit /b 0
)

rem --- 4) Auto-open browser (after server is ready, ~3s) + run server in foreground ---
echo.
echo ============================================================
echo   QoE Normalizer is running. Keep this window OPEN while using the app.
echo.
echo   Open in browser:  http://127.0.0.1:5000
echo   (Your browser will open automatically in a few seconds.)
echo.
echo   To STOP: close this window (or press Ctrl+C).
echo.
echo   Enter the 2 keys (OpenDART / Anthropic) in the web screen.
echo ============================================================
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:5000'"
%PYEXE% -m src.web.app

echo.
echo Server has stopped.
pause
endlocal
