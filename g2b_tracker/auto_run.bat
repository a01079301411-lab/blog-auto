@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
python src\main.py --quiet >> logs\auto_run.log 2>&1
