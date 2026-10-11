"""GitHub에서 최신 코드를 받아 바뀐 파일만 덮어쓰는 자동 업데이트.

run.bat이 매번 실행 전에 부른다. 인터넷이 안 되거나 실패해도 지금 버전으로
계속 실행되도록 오류는 경고만 하고 넘어간다.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import urllib.request
import zipfile

REPO = "a01079301411-lab/blog-auto"
BRANCH = "claude/ecstatic-lamport-5i53ft"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 사용자가 고쳐 쓰는 파일은 이미 있으면 덮어쓰지 않는다 (settings.ini는 아래에서 병합)
KEEP = {"settings.ini"}

# 마지막으로 받은 기본 settings.ini. 사용자가 바꾼 값과 기본값을 구분하는 데 쓴다
SETTINGS_BASE = ".settings_base.ini"

# 병합 기능이 생기기 전에 배포한 settings.ini 값 (기준 파일이 없을 때 사용)
FIRST_BASE = {
    "style": "green", "count": "7", "min_len": "20", "max_len": "60",
    "context": "꼴통사장 권기준 대표의 사업 강의. 창업, 매출, 사장 마인드, 크리에이터로 돈 버는 법",
    "speaker": "권기준 / 꼴통사장 대표", "focus": "0.5", "model": "small", "font": "",
}

_LINE = re.compile(r"^(\s*)([A-Za-z_]+)(\s*=\s*)(.*?)\s*$")


def _values(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith(("#", ";")):
            out[m.group(2)] = m.group(4)
    return out


def merge_settings(root: str, shipped: str) -> list[str]:
    """새로 배포된 기본값을 사용자 settings.ini에 반영한다.

    사용자가 직접 고친 값(이전 기본값과 다른 값)은 건드리지 않고,
    기본값 그대로인 항목만 새 기본값으로 바꾼다. 새로 생긴 항목은 추가한다.
    """
    path = os.path.join(root, "settings.ini")
    base_path = os.path.join(root, SETTINGS_BASE)
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    try:
        with open(base_path, encoding="utf-8") as f:
            base = _values(f.read())
    except FileNotFoundError:
        base = FIRST_BASE
    new = _values(shipped)
    mine = _values(text)

    changed = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _LINE.match(line)
        if not m or line.lstrip().startswith(("#", ";")):
            continue
        key, value = m.group(2), m.group(4)
        if key in new and value == base.get(key) and value != new[key]:
            lines[i] = f"{m.group(1)}{key}{m.group(3)}{new[key]}"
            changed.append(f"{key}: {value} → {new[key]}")
    for key in new.keys() - mine.keys():  # 새로 생긴 설정
        lines.append(f"{key} = {new[key]}")
        changed.append(f"{key} = {new[key]} (새 설정)")

    if changed:
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(lines) + "\n")
    with open(base_path, "w", encoding="utf-8") as f:
        f.write(shipped)
    return changed


def update(root: str = ROOT, url: str = ZIP_URL) -> list[str]:
    """바뀐 파일을 덮어쓰고, 바뀐 파일 경로 목록을 돌려준다."""
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = resp.read()

    changed = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # 압축 안 경로는 "blog-auto-<브랜치>/shortform/cli.py" 형태
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            if not rel or rel.startswith(".") or ".." in rel.split("/"):
                continue
            dest = os.path.join(root, *rel.split("/"))
            if rel in KEEP and os.path.exists(dest):
                if rel == "settings.ini":
                    shipped = zf.read(info).decode("utf-8-sig").replace("\r\n", "\n")
                    changed += [f"settings.ini ({c})" for c in merge_settings(root, shipped)]
                continue
            new = zf.read(info)
            try:
                with open(dest, "rb") as f:
                    if f.read() == new:
                        continue  # 같은 내용은 건드리지 않는다 (실행 중인 run.bat 보호)
            except FileNotFoundError:
                pass
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".new"
            with open(tmp, "wb") as f:
                f.write(new)
            os.replace(tmp, dest)
            changed.append(rel)
    return changed


def main() -> None:
    print("[업데이트 확인]", end=" ", flush=True)
    try:
        changed = update()
    except Exception as e:  # 인터넷 문제 등: 지금 버전으로 계속
        print(f"건너뜀 ({type(e).__name__}: {e})")
        return
    if not changed:
        print("최신 버전이에요.")
        return
    print(f"{len(changed)}개 파일을 새 버전으로 바꿨어요.")
    for rel in changed:
        print(f"  - {rel}")
    if "requirements.txt" in changed:
        print("[업데이트] 필요한 패키지 설치 중...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                        os.path.join(ROOT, "requirements.txt")])


if __name__ == "__main__":
    main()
