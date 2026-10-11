"""GitHub에서 최신 코드를 받아 바뀐 파일만 덮어쓰는 자동 업데이트.

run.bat이 매번 실행 전에 부른다. 인터넷이 안 되거나 실패해도 지금 버전으로
계속 실행되도록 오류는 경고만 하고 넘어간다.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import urllib.request
import zipfile

REPO = "a01079301411-lab/blog-auto"
BRANCH = "claude/ecstatic-lamport-5i53ft"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 사용자가 고쳐 쓰는 파일은 이미 있으면 덮어쓰지 않는다
KEEP = {"settings.ini"}


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
