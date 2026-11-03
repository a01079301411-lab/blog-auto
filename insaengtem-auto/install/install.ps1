# 인생템연구소 자동발행 — 설치 스크립트 (설치.bat 이 실행)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Say($m) { Write-Host "`n▶ $m" -ForegroundColor Cyan }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}
function Find-Python {
  foreach ($c in @("py -3", "python")) {
    try {
      $v = & cmd /c "$c -c ""import sys;print(sys.version_info[:2]>=(3,10))"" 2>nul"
      if ($v -eq "True") { return $c }
    } catch {}
  }
  return $null
}

Write-Host "=== 인생템연구소 자동발행 설치 ===" -ForegroundColor Yellow
Write-Host "설치 폴더: $Root"

# 1) Python
Say "1/6 Python 확인"
$py = Find-Python
if (-not $py) {
  Write-Host "Python 3.10 이상이 없어 설치합니다 (winget)..."
  try { winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements }
  catch { Write-Host "winget 이 없습니다. https://www.python.org/downloads/ 에서 Python 설치('Add to PATH' 체크) 후 다시 실행하세요." -ForegroundColor Red; exit 1 }
  Refresh-Path
  $py = Find-Python
  if (-not $py) { Write-Host "Python 설치 후 PC를 재시작하고 설치.bat 을 다시 실행하세요." -ForegroundColor Red; exit 1 }
}
Write-Host "사용: $py"

# 2) 가상환경 + 패키지
Say "2/6 프로그램 구성요소 설치 (몇 분 걸릴 수 있음)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv" }
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "가상환경 생성 실패" -ForegroundColor Red; exit 1 }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "패키지 설치 실패. 인터넷 연결 확인 후 다시 실행하세요." -ForegroundColor Red; exit 1 }

# 3) 설정 파일
Say "3/6 설정 파일(.env)"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host ".env 생성" } else { Write-Host ".env 유지" }
function Set-EnvKey($k, $v) {
  $lines = @(Get-Content ".env" -Encoding UTF8)
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match "^\s*$k=") { $lines[$i] = "$k=$v"; $found = $true } }
  if (-not $found) { $lines += "$k=$v" }
  [IO.File]::WriteAllLines((Join-Path $Root ".env"), $lines, (New-Object Text.UTF8Encoding $false))
}

# 4) 브라우저(자동화용)
Say "4/6 브라우저 준비"
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) { Set-EnvKey "CHROME_CHANNEL" "chrome"; Write-Host "설치된 Chrome 사용" }
else { & $vpy -m playwright install chromium; Set-EnvKey "CHROME_CHANNEL" ""; Write-Host "Chromium 설치" }

# 5) ffmpeg
Say "5/6 ffmpeg(영상 합치기) 확인"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  try { winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements } catch { Write-Host "winget 으로 ffmpeg 설치 실패" }
  Refresh-Path
}
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) { $ffdir = Split-Path $ff.Source }
else {
  $hit = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  $ffdir = if ($hit) { $hit.DirectoryName } else { $null }
}
if ($ffdir) { Set-EnvKey "FFMPEG_DIR" $ffdir; Write-Host "ffmpeg: $ffdir" }
else { Write-Host "ffmpeg 를 찾지 못했습니다. PC 재시작 후 설치.bat 을 다시 실행하세요." -ForegroundColor Red }

# 6) 바탕화면 아이콘 + 실행
Say "6/6 바탕화면 아이콘 만들기"
& $vpy -m insaengtem.winsetup shortcut
Write-Host "`n✅ 설치 완료! 바탕화면의 '인생템연구소 자동발행' 아이콘을 더블클릭하세요." -ForegroundColor Green
Write-Host "   (지금 관리 화면을 엽니다)"
Start-Process (Join-Path $Root ".venv\Scripts\pythonw.exe") -ArgumentList "-m insaengtem.app" -WorkingDirectory $Root
