@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python is not installed.
  echo Install it from the page that opens now, and CHECK "Add python.exe to PATH".
  echo Then run this file again.
  start https://www.python.org/downloads/
  pause
  exit /b
)
python src\setup.py
pause
