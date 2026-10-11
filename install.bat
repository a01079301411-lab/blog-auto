@echo off
cd /d "%~dp0"
echo ============================================
echo   shortform setup
echo ============================================
echo.

set NEED_RESTART=0

python --version >nul 2>nul
if errorlevel 1 goto install_python
echo [OK] Python
goto check_ffmpeg

:install_python
echo [INSTALL] Python 3.12 ...
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
set NEED_RESTART=1

:check_ffmpeg
ffmpeg -version >nul 2>nul
if errorlevel 1 goto install_ffmpeg
echo [OK] FFmpeg
goto check_restart

:install_ffmpeg
echo [INSTALL] FFmpeg ...
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
set NEED_RESTART=1

:check_restart
if "%NEED_RESTART%"=="0" goto pip_install
echo.
echo --------------------------------------------
echo  New programs were installed.
echo  Close this window and run install.bat again.
echo --------------------------------------------
pause
exit /b

:pip_install
echo.
echo [INSTALL] Python packages (takes a few minutes) ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed

if defined ANTHROPIC_API_KEY goto done
echo.
echo --------------------------------------------
echo  Paste your Claude API key (starts with sk-ant-).
echo  Get one at https://console.anthropic.com
echo  Press Enter to skip.
echo --------------------------------------------
set /p APIKEY=API key: 
if "%APIKEY%"=="" goto done
setx ANTHROPIC_API_KEY "%APIKEY%" >nul
echo [OK] API key saved

:done
echo.
echo ============================================
echo  Done! Drag a video file onto run.bat to start.
echo  Edit settings.ini with Notepad to change options.
echo ============================================
pause
exit /b

:pip_failed
echo.
echo [FAILED] Package install failed. Check the error above.
pause
exit /b 1
