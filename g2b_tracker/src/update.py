"""최신 버전 받기 (업데이트.bat). .env, output, logs, 영업DB.xlsx, 기록은 절대 건드리지 않는다.
사장님이 고친 data 파일(keywords.json, watchlist.txt, targets.csv)은 덮어쓰지 않고 '.새버전'으로 옆에 둔다."""
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_URL = "https://github.com/a01079301411-lab/blog-auto/archive/refs/heads/claude/magical-darwin-l927px.zip"
SUB = "g2b_tracker/"
STATE = ROOT / ".update_state.json"
NEVER = {".env", "output", "logs", "backup", "영업DB.xlsx", "data/seen.json", "data/state.json", "data/contacts.json", "data/contacts_v2.json", "data/schools.json", "data/my_contacts.csv", ".update_state.json"}


def fp(b):
    return hashlib.sha256(b).hexdigest()


def main():
    print("최신 버전 받는 중...")
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=60) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
    except Exception as e:
        print(f"받지 못했어요: {e}")
        return
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    new_state, changed, kept = {}, [], []
    for info in z.infolist():
        parts = info.filename.split("/", 1)
        if info.is_dir() or len(parts) < 2 or not parts[1].startswith(SUB):
            continue
        rel = parts[1][len(SUB):]
        if not rel or any(rel == p or rel.startswith(p + "/") for p in NEVER):
            continue
        data = z.read(info)
        target = ROOT / rel
        new_state[rel] = fp(data)
        cur = target.read_bytes() if target.exists() else None
        if cur == data:
            continue
        if cur is not None and rel.startswith("data/") and rel in state and fp(cur) != state[rel]:
            target.with_name(target.name + ".새버전").write_bytes(data)
            new_state[rel] = state[rel]
            kept.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        changed.append(rel)
    STATE.write_text(json.dumps(new_state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"업데이트 {len(changed)}개 파일." + (f" 직접 고치신 파일 {len(kept)}개는 그대로 두고 '.새버전'을 옆에 놨어요." if kept else ""))
    import subprocess, sys
    subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])


if __name__ == "__main__":
    main()
