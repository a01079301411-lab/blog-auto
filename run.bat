@echo off
cd /d "%~dp0"
if "%~1"=="" goto usage

python -m shortform auto "%~1"
if errorlevel 1 goto failed
pause
exit /b

:usage
echo Drag and drop a video file onto run.bat
echo Edit settings.ini with Notepad to change options.
pause
exit /b

:failed
echo.
echo [FAILED] Please send a screenshot of the error above.
pause
exit /b 1
