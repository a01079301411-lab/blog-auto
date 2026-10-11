@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   shortform 설치 (숏폼 자동 편집기)
echo ============================================
echo.

set NEED_RESTART=0

python --version >nul 2>nul
if errorlevel 1 goto install_python
echo [OK] Python
goto check_ffmpeg

:install_python
echo [설치] Python 3.12 ...
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
set NEED_RESTART=1

:check_ffmpeg
ffmpeg -version >nul 2>nul
if errorlevel 1 goto install_ffmpeg
echo [OK] FFmpeg
goto check_restart

:install_ffmpeg
echo [설치] FFmpeg ...
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
set NEED_RESTART=1

:check_restart
if "%NEED_RESTART%"=="0" goto pip_install
echo.
echo --------------------------------------------
echo  프로그램을 새로 설치했어요.
echo  이 창을 닫고 install.bat 을 한 번 더 실행해 주세요.
echo --------------------------------------------
pause
exit /b

:pip_install
echo.
echo [설치] 파이썬 패키지 (몇 분 걸려요) ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [실패] 패키지 설치에 실패했어요. 위 오류 메시지를 확인해 주세요.
  pause
  exit /b 1
)

if defined ANTHROPIC_API_KEY goto done
echo.
echo --------------------------------------------
echo  Claude API 키를 입력해 주세요 (sk-ant- 로 시작).
echo  https://console.anthropic.com 에서 만들 수 있어요.
echo  하이라이트 자동 선정에만 필요해요. 없으면 그냥 Enter.
echo --------------------------------------------
set /p APIKEY=API 키: 
if "%APIKEY%"=="" goto done
setx ANTHROPIC_API_KEY "%APIKEY%" >nul
echo [OK] API 키 저장 완료

:done
echo.
echo ============================================
echo  설치 끝! 영상 파일을 run.bat 위로 끌어다 놓으면 시작해요.
echo ============================================
pause
