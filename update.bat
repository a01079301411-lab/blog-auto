@echo off
cd /d "%~dp0"
echo ============================================
echo   shortform update
echo ============================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $url='https://github.com/a01079301411-lab/blog-auto/archive/refs/heads/claude/ecstatic-lamport-5i53ft.zip'; $root=(Get-Location).Path; $zip=Join-Path $env:TEMP 'shortform_update.zip'; $tmp=Join-Path $env:TEMP 'shortform_update'; Write-Host 'Downloading latest version...'; Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing; if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }; Expand-Archive -Path $zip -DestinationPath $tmp -Force; $src=(Get-ChildItem -Path $tmp -Directory)[0].FullName; $n=0; Get-ChildItem -Path $src -Recurse -File | ForEach-Object { $rel=$_.FullName.Substring($src.Length+1); $dest=Join-Path $root $rel; if ($rel -eq 'update.bat') { return }; if ($rel -eq 'settings.ini' -and (Test-Path $dest)) { return }; New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null; Copy-Item -Path $_.FullName -Destination $dest -Force; $n++ }; Remove-Item $tmp -Recurse -Force; Remove-Item $zip -Force; Write-Host ('Updated ' + $n + ' files.')"
if errorlevel 1 goto failed
echo.
echo Checking Python packages...
python -m pip install -q -r requirements.txt
echo.
echo ============================================
echo  Update complete! Drag a video onto run.bat.
echo ============================================
pause
exit /b

:failed
echo.
echo [FAILED] Update failed. Please send a screenshot of this window.
pause
exit /b 1
