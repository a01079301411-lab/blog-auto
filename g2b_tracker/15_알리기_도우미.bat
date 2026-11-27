@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 알리기 도우미 - 로그인과 결제만 하시면 됩니다
echo ============================================================
echo   알리기 도우미: 필요한 화면과 파일은 제가 다 열어 드립니다.
echo   대표님은 [로그인 / 결제 / 붙여넣기] 만 하시면 됩니다.
echo ============================================================
echo.
echo [1/3] 우편 DM - 이번에 보낼 묶음 준비 중...
python src\main.py --dmfile
for /f "usebackq tokens=* delims=" %%a in (`powershell -NoProfile -Command "(Get-Content -Encoding UTF8 'output\_다음묶음.txt')[0]"`) do set LABEL=%%a
for /f "usebackq tokens=* delims=" %%a in (`powershell -NoProfile -Command "(Get-Content -Encoding UTF8 'output\_다음묶음.txt')[1]"`) do set XLSX=%%a
for /f "usebackq tokens=* delims=" %%a in (`powershell -NoProfile -Command "(Get-Content -Encoding UTF8 'output\_다음묶음.txt')[2]"`) do set PDF=%%a
start "" "https://www.epost.go.kr/"
explorer /select,"%XLSX%"
explorer /select,"%~dp0docs\우편DM\%PDF%"
echo.
echo   열린 것: 인터넷우체국 / 주소 파일 폴더 / PDF 폴더
echo   할 일:  1) 인터넷우체국 로그인
echo           2) 우편 → e-그린우편 → 신청접수
echo           3) 문서에 PDF, 받는 사람에 주소 파일을 끌어다 놓기 (흑백 / 양면)
echo           4) 결제
echo.
set /p DONE=결제까지 끝났으면 Y, 다음에 할 거면 그냥 Enter : 
if /i "%DONE%"=="Y" python src\main.py --dmdone %LABEL%
echo.
echo [2/3] 공공구매종합정보망 - 회사 소개 문구를 클립보드에 복사했습니다.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 'docs\smpp_소개문구.txt' | Set-Clipboard"
start "" "https://www.smpp.go.kr/"
echo   할 일:  로그인 → 기업정보(주요 제품·서비스) 칸에 Ctrl+V → 저장
echo           (확인서 3종 유효기간도 한 번 봐 주세요)
echo.
pause
echo [3/3] 학교장터 - 공급업체 가입 화면을 엽니다.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 'docs\smpp_소개문구.txt' | Set-Clipboard"
start "" "https://www.s2b.kr/"
echo   할 일:  회원가입 → 공급자(업체) → 사업자 공동인증서 → 업체 소개 칸에 Ctrl+V
echo           이미 가입했으면 창만 닫으세요. 견적요청 찾기는 매일 자동입니다.
echo.
echo 끝! 다음 주에 텔레그램으로 "주소록 새로 만듦"이 오면 이 파일을 다시 실행하세요.
pause
