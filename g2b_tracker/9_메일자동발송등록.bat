@echo off
chcp 65001 >nul
cd /d "%~dp0"
schtasks /Create /SC DAILY /TN "G2B_Mail" /TR "\"%~dp0auto_mail.bat\"" /ST 08:30 /RI 30 /DU 10:00 /F
if errorlevel 1 (
  echo Failed. Right-click this file and choose "Run as administrator".
) else (
  echo OK. Checks every 30 minutes from 08:30 to 18:30 and sends pending proposal mails.
  echo To remove: schtasks /Delete /TN G2B_Mail /F
)
pause
