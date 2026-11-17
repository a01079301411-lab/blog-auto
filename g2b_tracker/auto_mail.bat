@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
python src\main.py --mail --quiet >> logs\auto_mail.log 2>&1
