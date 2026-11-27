@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 학교장터(S2B) 최근 30일 이사·집기 이전 견적요청을 찾는 중...
python src\main.py --s2b 30
pause
