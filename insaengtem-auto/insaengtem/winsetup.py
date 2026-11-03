"""Windows 연동: 바탕화면 아이콘, 자동발행(작업 스케줄러), 알림, 시작하기 체크리스트."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT, SECRETS, env

IS_WIN = os.name == "nt"
TASKS = {
    # 이름: (설명, schtasks 스케줄 인자, run_task 모드)
    "insaengtem_run_due": ("5분마다 게시 시각 된 승인 건 게시", ["/SC", "MINUTE", "/MO", "5"], "run-due"),
    "insaengtem_inbox": ("매시 새 답글 알림", ["/SC", "HOURLY", "/ST", "00:10"], "inbox"),
    "insaengtem_weekly": ("일요일 21:00 다음 주 원고·영상·일정 준비", ["/SC", "WEEKLY", "/D", "SUN", "/ST", "21:00"], "weekly"),
}
NO_WINDOW = 0x08000000 if IS_WIN else 0


def pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)


# ------------------------------------------------------------------ 자동발행 (작업 스케줄러)
def task_command(mode: str) -> str:
    return f'"{pythonw()}" "{ROOT / "run_task.pyw"}" {mode}'


def autopublish_status() -> dict:
    if not IS_WIN:
        return {k: None for k in TASKS}
    return {k: _run(["schtasks", "/Query", "/TN", k]).returncode == 0 for k in TASKS}


def autopublish(on: bool) -> list[str]:
    if not IS_WIN:
        return ["Windows 가 아니라서 작업 스케줄러를 쓸 수 없습니다 (cron 으로 run_task.pyw 를 등록하세요)."]
    out = []
    for name, (desc, sched, mode) in TASKS.items():
        if on:
            r = _run(["schtasks", "/Create", "/F", "/TN", name, "/TR", task_command(mode), *sched])
        else:
            r = _run(["schtasks", "/Delete", "/F", "/TN", name])
        out.append(f"{'켬' if on else '끔'} {desc}: {'OK' if r.returncode == 0 else (r.stderr or r.stdout).strip()}")
    return out


# ------------------------------------------------------------------ 알림
def notify(title: str, msg: str) -> None:
    """Windows 우측 하단 풍선 알림(외부 모듈 없음). 실패해도 무시."""
    if not IS_WIN:
        print(f"[알림] {title}: {msg}")
        return
    t = title.replace("'", "''")
    m = msg.replace("'", "''")[:250]
    ps = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
          "$n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information;"
          f"$n.Visible=$true; $n.ShowBalloonTip(15000,'{t}','{m}','Info'); Start-Sleep -s 15; $n.Dispose()")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], creationflags=NO_WINDOW)
    except OSError:
        pass


# ------------------------------------------------------------------ 바탕화면 아이콘
def desktop_dir() -> Path:
    if IS_WIN:
        r = _run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"])
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    return Path.home() / "Desktop"


def make_icon() -> Path:
    ico = ROOT / "assets" / "app.ico"
    if ico.exists():
        return ico
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, 248, 248], radius=56, fill=(255, 107, 26, 255))
    try:
        from video.render import FB, font  # noqa: F401
        f = ImageFont.truetype(FB, 120, index=1 if "NotoSansCJK" in FB else 0)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    d.text((128, 132), "인생", font=f, fill="white", anchor="mm")
    im.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ico


def create_shortcut() -> str:
    ico = make_icon()
    target = pythonw()
    args = "-m insaengtem.app"
    lnk = desktop_dir() / "인생템연구소 자동발행.lnk"
    if not IS_WIN:
        return "Windows 에서만 바탕화면 아이콘을 만듭니다."
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{target}'; $s.Arguments='{args}'; $s.WorkingDirectory='{ROOT}';"
          f"$s.IconLocation='{ico}'; $s.Description='인생템연구소 인스타·스레드 자동발행·관리'; $s.Save()")
    r = _run(["powershell", "-NoProfile", "-Command", ps])
    return str(lnk) if r.returncode == 0 else f"실패: {r.stderr.strip()}"


# ------------------------------------------------------------------ 시작하기 체크리스트
def checklist() -> list[dict]:
    from .catalog import load_links
    links = load_links()
    auto = autopublish_status()
    s = __import__("insaengtem.config", fromlist=["settings"]).settings()
    th_mode = s["publish_mode"]["threads"]
    items = [
        ("python", "프로그램 설치", True, "설치.bat 실행 완료"),
        ("ffmpeg", "ffmpeg(영상 합치기)", bool(shutil.which("ffmpeg")), "설치.bat 이 자동 설치. 안 되면 PC 재시작"),
        ("links", "제휴 링크(sl 토큰) 등록", len(links) > 0, f"{len(links)}개 등록됨" if links else "원본 zip 의 _catalog.json 가져오기"),
        ("anthropic", "Claude API 키(원고 자동 작성)", bool(env("ANTHROPIC_API_KEY")), "선택. 없으면 규칙 템플릿으로 작성"),
        ("ig", "인스타 API 토큰", bool(env("IG_USER_ID") and env("IG_ACCESS_TOKEN")), "게시·성과 수집에 필요"),
        ("threads", "스레드 API 토큰", bool(env("THREADS_USER_ID") and env("THREADS_ACCESS_TOKEN")), "게시·성과·답글에 필요"),
        ("media", "스레드 영상 공개주소", th_mode == "web" or bool(env("MEDIA_BASE_URL") or env("S3_BUCKET")),
         "R2/S3 설정 또는 스레드를 '웹 모드'로"),
        ("chrome", "크롬 로그인(스레드·비즈니스 스위트·YOGO)", (ROOT / (env("CHROME_PROFILE_DIR") or "chrome-profile-insaengtem")).exists(),
         "[크롬 로그인] 버튼 → 로그인 후 창 닫기"),
        ("auto", "자동발행 켜기", bool(auto) and all(v for v in auto.values() if v is not None) and IS_WIN, "[자동발행 켜기] 버튼"),
    ]
    return [{"id": i, "label": l, "ok": ok, "hint": h} for i, l, ok, h in items]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "shortcut"
    if cmd == "shortcut":
        print(create_shortcut())
    elif cmd == "icon":
        print(make_icon())
    elif cmd in ("on", "off"):
        print("\n".join(autopublish(cmd == "on")))
