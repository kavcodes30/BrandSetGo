@echo off
setlocal EnableDelayedExpansion
title BrandSetGo
cd /d "%~dp0"

echo ============================================================
echo   BrandSetGo  -  brand governance workspace
echo ============================================================
echo.

if /I "%~1"=="reset" (
  echo [i] Resetting the database...
  if exist "backend\brandsetgo.db" del /q "backend\brandsetgo.db"
  echo [i] Start the app and sign up, or run "run.bat seed" for demo accounts.
  echo.
)

REM ---------- 1. Python ----------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [X] Python was not found on PATH.
  echo.
  echo     Install Python 3.11 or newer from:
  echo       https://www.python.org/downloads/
  echo     During setup tick "Add python.exe to PATH", then run run.bat again.
  echo.
  pause
  exit /b 1
)

REM ---------- 2. virtual environment ----------
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/3] Creating the Python environment...
  %PY% -m venv backend\.venv
  if errorlevel 1 (
    echo [X] Could not create backend\.venv
    pause
    exit /b 1
  )
) else (
  echo [1/3] Python environment found.
)

echo [2/3] Installing dependencies...
"backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"backend\.venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 (
  echo [X] Dependency install failed. Check your internet connection and try again.
  pause
  exit /b 1
)

REM ---------- 3. configuration ----------
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul

findstr /r /c:"^SARVAM_API_KEY=..*" "backend\.env" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [3/3] Sarvam AI key
  echo       Checking the bundled key...
  pushd backend
  ".venv\Scripts\python.exe" -c "import sys;sys.path.insert(0,'.');from app.core.config import settings;print('      connected' if settings.api_key else '      NOT CONFIGURED')"
  popd
  echo.
) else (
  echo [3/3] Sarvam AI key already configured.
)

if /I "%~1"=="seed" (
  echo Creating demo accounts with generated passwords...
  pushd backend
  ".venv\Scripts\python.exe" -m app.scripts.seed_demo
  popd
  echo.
)

REM ---------- start ----------
echo Starting BrandSetGo on http://localhost:8000
start "BrandSetGo" cmd /k ""%~dp0scripts\serve.bat""

echo Waiting for the server...
powershell -NoProfile -Command "for($i=0;$i -lt 160;$i++){try{$r=Invoke-WebRequest -UseBasicParsing 'http://localhost:8000/health' -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0}}catch{}; Start-Sleep -Milliseconds 500}; exit 1"
if errorlevel 1 (
  echo [X] The server did not start. Read the "BrandSetGo" window for the error.
  pause
  exit /b 1
)

start "" "http://localhost:8000"

echo.
echo ============================================================
echo   App   http://localhost:8000
echo   API   http://localhost:8000/docs
echo.
echo   The BrandSetGo window is the server. Close it to stop.
echo   First sign-up becomes the platform admin.
echo   run.bat seed    creates demo accounts with printed passwords
echo   run.bat reset   wipes the database
echo ============================================================
echo.
timeout /t 6 >nul
endlocal
