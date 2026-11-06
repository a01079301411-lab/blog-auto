@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install it and CHECK "Add python.exe to PATH".
  start https://www.python.org/downloads/
  pause
  exit /b
)
python src\setup.py
pause
