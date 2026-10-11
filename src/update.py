"""최신 버전 받기: 업데이트.bat 을 더블클릭하면 실행된다.

GitHub에서 최신 프로그램을 받아 이 폴더에 덮어쓴다.
- 절대 건드리지 않는 것: .env, 로그인 정보, 발행 기록, 사진, 미리보기, 실행 기록
- 사장님이 고칠 수 있는 파일(data, prompts, samples): 사장님이 고친 적이 있으면 덮어쓰지 않고
  새 버전을 '파일이름.새버전' 으로 옆에 둔다. 덮어쓸 때는 예전 파일을 backup 폴더에 남긴다.
"""
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_URL = (
    "https://github.com/a01079301411-lab/blog-auto/archive/refs/heads/"
    "claude/naver-blog-automation-khfiwn.zip"
)
STATE_FILE = ROOT / ".update_state.json"  # 지난번 업데이트로 받은 파일들의 지문
NEVER_TOUCH = {
    ".env", "browser_profile", "output", "logs", "photos", "backup", ".update_state.json",
    "data/history.json", "data/links_cache.json",
}
USER_EDITABLE = ("data/", "prompts/", "samples/")  # 사장님이 직접 고칠 수 있는 파일


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def protected(rel):
    return any(rel == p or rel.startswith(p + "/") for p in NEVER_TOUCH)


def main():
    print("최신 버전을 받는 중...")
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=60) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
    except Exception as e:
        print(f"받지 못했어요. 인터넷 연결을 확인해 주세요. ({e})")
        return

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    backup_dir = ROOT / "backup" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    updated, kept, new_state = [], [], {}
    old_requirements = (ROOT / "requirements.txt").read_bytes() if (ROOT / "requirements.txt").exists() else b""

    for info in archive.infolist():
        if info.is_dir():
            continue
        rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""  # 맨 앞 폴더 이름 빼기
        if not rel or protected(rel):
            continue
        data = archive.read(info)
        target = ROOT / rel
        new_state[rel] = fingerprint(data)
        current = target.read_bytes() if target.exists() else None
        if current == data:
            continue

        if current is not None and rel.startswith(USER_EDITABLE):
            if rel in state and fingerprint(current) != state[rel]:
                # 사장님이 고친 파일은 덮어쓰지 않는다.
                # 우리 쪽 새 버전이 실제로 바뀌었을 때만 '.새버전'으로 옆에 둔다.
                if new_state[rel] != state[rel]:
                    target.with_name(target.name + ".새버전").write_bytes(data)
                    kept.append(rel)
                new_state[rel] = state[rel]
                continue
            (backup_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_dir / rel)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        updated.append(rel)

    STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")

    if not updated and not kept:
        print("이미 최신 버전이에요.")
        return
    print(f"\n바뀐 파일 {len(updated)}개를 새로 받았어요.")
    for rel in updated:
        print(f"  - {rel}")
    if kept:
        print("\n사장님이 고친 파일은 그대로 두고, 새 버전을 '.새버전' 이름으로 옆에 두었어요:")
        for rel in kept:
            print(f"  - {rel}  (새 버전: {rel}.새버전)")
    if backup_dir.exists():
        print(f"\n덮어쓴 파일의 예전 내용은 여기에 있어요: {backup_dir}")

    if (ROOT / "requirements.txt").read_bytes() != old_requirements:
        print("\n필요한 부품이 바뀌어서 설치합니다...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "-q", "-r", "requirements.txt"], cwd=ROOT)
    print("\n업데이트 끝!")


if __name__ == "__main__":
    main()
