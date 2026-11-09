@echo off
cd /d "%~dp0"
python -m shortform.update
python -m shortform.shortcut
where pythonw >nul 2>nul
if errorlevel 1 goto console
start "" pythonw -m shortform.start %*
exit /b

:console
python -m shortform.start %*
