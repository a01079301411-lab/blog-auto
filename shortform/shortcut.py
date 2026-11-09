"""바탕화면에 '숏폼 자동 편집기' 아이콘을 만든다 (Windows).

아이콘을 더블클릭하면 콘솔 창 없이 프로그램 창(pythonw -m shortform.start)이 뜨고,
영상 파일을 아이콘 위로 끌어다 놓으면 그 영상이 목록에 들어간 채로 열린다.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "숏폼 자동 편집기.lnk"
ICON = os.path.join(ROOT, "shortform", "assets", "app_v2.ico")

# 경로는 환경 변수로 넘겨 PowerShell 따옴표 문제를 피한다
_PS = (
    "$d=[Environment]::GetFolderPath('Desktop');"
    "$name=$env:SF_NAME;"
    # 바탕화면이 원드라이브로 여러 컴퓨터에 동기화되면 아이콘 하나를 같이 쓰게 되어, 다른 컴퓨터에서는
    # 프로그램을 못 찾는다(흰 종이 아이콘). 그럴 땐 컴퓨터마다 이름이 다른 아이콘을 따로 만든다
    "if ($d -like '*OneDrive*') {"
    " $name='숏폼 자동 편집기 (' + $env:COMPUTERNAME + ').lnk';"
    " $old=Join-Path $d $env:SF_NAME;"
    " if (Test-Path $old) { $o=(New-Object -ComObject WScript.Shell).CreateShortcut($old);"
    "  if (-not (Test-Path $o.TargetPath) -or -not (Test-Path $o.WorkingDirectory)) { Remove-Item $old -Force } } };"
    "$p=Join-Path $d $name;"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
    # 이미 있어도 다른 컴퓨터 경로(바탕화면이 원드라이브로 동기화된 경우)나 예전 설정이면 고친다
    "if ((Test-Path $p) -and ($env:SF_FORCE -ne '1') -and ($s.TargetPath -eq $env:SF_TARGET)"
    " -and ($s.Arguments -eq '-m shortform.start') -and ($s.WorkingDirectory -eq $env:SF_ROOT)"
    " -and ($s.IconLocation -like ($env:SF_ICON + '*'))) { exit 0 };"
    "$s.TargetPath=$env:SF_TARGET;"
    "$s.Arguments='-m shortform.start';"
    "$s.WorkingDirectory=$env:SF_ROOT;"
    "$s.IconLocation=$env:SF_ICON + ',0';"
    "$s.Description='롱폼 영상으로 숏폼을 자동으로 만들어요';"
    "$s.Save();"
    "try { ie4uinit.exe -show } catch {};"  # 바뀐 아이콘이 바로 보이게 아이콘 캐시 새로 고침
    "Write-Host 'created'"
)


def _pythonw() -> str:
    exe = sys.executable
    folder = os.path.dirname(exe)
    cand = os.path.join(folder, "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def create(force: bool = False) -> bool:
    """바탕화면 아이콘을 만든다. 새로 만들었으면 True."""
    if sys.platform != "win32":
        return False
    env = {**os.environ, "SF_NAME": NAME, "SF_TARGET": _pythonw(), "SF_ROOT": ROOT,
           "SF_ICON": ICON, "SF_FORCE": "1" if force else "0"}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", _PS], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "created" in r.stdout


if __name__ == "__main__":
    if create(force="--force" in sys.argv):
        print("바탕화면에 '숏폼 자동 편집기' 아이콘을 만들었어요.")
