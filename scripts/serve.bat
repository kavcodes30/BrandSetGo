@echo off
title BrandSetGo  -  http://localhost:8000
cd /d "%~dp0..\backend"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) else (
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
)
echo.
echo The server stopped. Press any key to close this window.
pause >nul
