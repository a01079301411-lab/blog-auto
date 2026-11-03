@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m insaengtem.updater
) else (
  echo Run install first.
)
pause
