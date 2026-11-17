@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p N=몇 차를 보냈나요? (숫자만, 예: 1) : 
python src\main.py --dmdone %N%
pause
