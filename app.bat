@echo off
cd /d "%~dp0"
python --version >nul 2>nul
if errorlevel 1 goto need_install
python -c "import anthropic, PIL, cv2" >nul 2>nul
if errorlevel 1 goto need_install
python -m shortform.update
python -m shortform.shortcut
where pythonw >nul 2>nul
if errorlevel 1 goto console
start "" pythonw -m shortform.start %*
exit /b

:console
python -m shortform.start %*
exit /b

:need_install
echo This computer needs setup first. Running install.bat ...
call install.bat
