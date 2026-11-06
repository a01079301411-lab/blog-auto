@echo off
chcp 65001 >nul
cd /d "%~dp0"
schtasks /Create /SC DAILY /TN "G2B_Tracker" /TR "\"%~dp0auto_run.bat\"" /ST 07:40 /F
if errorlevel 1 (
  echo Failed. Right-click this file and choose "Run as administrator".
) else (
  echo OK. Runs every day at 07:40. To remove: schtasks /Delete /TN G2B_Tracker /F
)
pause
