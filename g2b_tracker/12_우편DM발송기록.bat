@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p N=보낸 묶음 이름 (주소록 시트 이름, 예: 학교1 / 병원1 / 기관1) : 
python src\main.py --dmdone %N%
pause
