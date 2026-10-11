@echo off
chcp 65001 >nul
setlocal

rem ================= 설정 (메모장으로 열어서 바꾸세요) =================
rem 디자인: green / magenta / overlay / basic / 또는 내스타일.json
set STYLE=green
rem 만들 숏폼 개수
set COUNT=7
rem 영상 설명: 누가, 무슨 내용인지 (하이라이트와 제목이 더 정확해져요)
set CONTEXT=꼴통사장 권기준 대표의 사업 강의. 창업, 매출, 사장 마인드, 크리에이터로 돈 버는 법
rem 인물 소개 줄에 고정으로 넣을 문구 (비우면 AI가 정함)
set SPEAKER=권기준 / 꼴통사장 대표
rem 음성 인식 모델: small (빠름) / medium / large-v3 (정확, 느림)
set MODEL=small
rem ====================================================================

if "%~1"=="" (
  echo 영상 파일을 run.bat 위로 끌어다 놓으세요.
  pause
  exit /b
)

cd /d "%~dp0"
set "OUT=%~dpn1_shorts"
set "EXTRA="
if not "%SPEAKER%"=="" set EXTRA=--speaker "%SPEAKER%"

python -m shortform shorts "%~1" -o "%OUT%" -n %COUNT% --style %STYLE% --model %MODEL% --context "%CONTEXT%" %EXTRA%
if errorlevel 1 (
  echo.
  echo [실패] 위 오류 메시지를 확인해 주세요.
  pause
  exit /b 1
)

echo.
echo 완료! 결과 폴더: %OUT%
start "" "%OUT%"
pause
