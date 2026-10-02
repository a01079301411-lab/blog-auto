@echo off
REM Windows Task Scheduler entry: posts at a random time inside the publish window
cd /d "%~dp0"
python src\main.py --schedule
