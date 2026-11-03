"""프로그램 업데이트 (GitHub 최신 버전 받아서 덮어쓰기, 내 데이터는 보존).

실행:  python -m insaengtem.updater [--check] [--force]
      (처음 한 번은 이 파일만 받아서 실행해도 됨: python updater_boot.py)
표준 라이브러리만 사용 — 패키지가 깨져 있어도 동작.

보존 규칙
- 절대 안 건드림 : .env, secrets/, .venv/, logs/, out/, backups/, chrome-profile*/, data/state/
- 없을 때만 추가 : data/ (등록 제품·원고·트렌드 가중치), assets/products/
- 합치기        : config/settings.json  (새 항목 추가, 내가 바꾼 값은 유지)
- 덮어쓰기      : 나머지(프로그램 코드·문서·설치 파일)
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

DEFAULT = {"repo": "a01079301411-lab/blog-auto", "branch": "claude/bold-mccarthy-s7y5jq", "subdir": "insaengtem-auto"}
PRESERVE = {".env", "secrets", ".venv", "logs", "out", "backups", "updater_boot.py"}
PRESERVE_PREFIX = ("chrome-profile",)
PRESERVE_PATHS = {"data/state"}
ADD_ONLY = ("data/", "assets/products/")
MERGE_JSON = {"config/settings.json"}


def find_root() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here, here.parent, Path.cwd()):
        if (cand / "run_task.pyw").exists() or (cand / "설치.bat").exists():
            return cand
    return Path.cwd()


ROOT = find_root()
VERSION = ROOT / "data" / "state" / "version.json"
UA = {"User-Agent": "insaengtem-updater", "Accept": "application/vnd.github+json"}


def cfg() -> dict:
    try:
        s = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
        return {**DEFAULT, **s.get("update", {})}
    except Exception:  # noqa: BLE001
        return DEFAULT


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def installed() -> dict:
    try:
        return json.loads(VERSION.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def check() -> dict:
    """원격 최신 커밋과 비교. {'latest','current','update','changes':[...]}"""
    c = cfg()
    latest = json.loads(_get(f"https://api.github.com/repos/{c['repo']}/commits/{c['branch']}"))
    cur = installed().get("sha")
    out = {"latest": latest["sha"][:7], "current": (cur or "")[:7] or "알 수 없음",
           "date": latest["commit"]["committer"]["date"][:10], "update": cur != latest["sha"], "changes": []}
    if out["update"]:
        try:
            if cur:
                cmp_ = json.loads(_get(f"https://api.github.com/repos/{c['repo']}/compare/{cur}...{latest['sha']}"))
                commits = cmp_.get("commits", [])
            else:
                commits = [latest]
            out["changes"] = [x["commit"]["message"].split("\n")[0] for x in commits][-20:]
        except Exception:  # noqa: BLE001
            out["changes"] = [latest["commit"]["message"].split("\n")[0]]
    out["_sha"] = latest["sha"]
    return out


def _rel_ok_to_overwrite(rel: str) -> str:
    """반환: 'skip' | 'add' | 'merge' | 'write'"""
    top = rel.split("/", 1)[0]
    if top in PRESERVE or top.startswith(PRESERVE_PREFIX) or any(rel == p or rel.startswith(p + "/") for p in PRESERVE_PATHS):
        return "skip"
    if rel in MERGE_JSON:
        return "merge"
    if rel.startswith(ADD_ONLY):
        return "add"
    return "write"


def _merge(new: dict, mine: dict) -> dict:
    out = dict(new)
    for k, v in mine.items():
        if isinstance(v, dict) and isinstance(new.get(k), dict):
            out[k] = _merge(new[k], v)
        elif k == "update":
            continue  # 업데이트 주소는 새 버전 값을 따름
        else:
            out[k] = v
    return out


def apply(force: bool = False, log=print) -> bool:
    c = cfg()
    info = check()
    if not info["update"] and not force:
        log(f"이미 최신 버전입니다 ({info['current']}).")
        return False
    log(f"새 버전 {info['latest']} ({info['date']}) 받는 중…")
    for ch in info["changes"]:
        log(f"  • {ch}")
    data = _get(f"https://codeload.github.com/{c['repo']}/zip/refs/heads/{c['branch']}")
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    prefix = next((n[: -len("insaengtem/__init__.py")] for n in names if n.endswith(c["subdir"] + "/insaengtem/__init__.py")), None)
    if prefix is None:
        raise SystemExit("받은 파일에서 프로그램 폴더를 찾지 못했습니다.")
    old_req = (ROOT / "requirements.txt").read_text(encoding="utf-8") if (ROOT / "requirements.txt").exists() else ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "backups" / stamp
    counts = {"write": 0, "add": 0, "merge": 0, "skip": 0}
    for n in names:
        if not n.startswith(prefix) or n.endswith("/"):
            continue
        rel = n[len(prefix):]
        dst = ROOT / rel
        mode = _rel_ok_to_overwrite(rel)
        if mode == "skip" or (mode == "add" and dst.exists()):
            counts["skip"] += 1
            continue
        body = zf.read(n)
        if dst.exists() and mode in ("write", "merge"):
            if dst.read_bytes() == body:
                continue
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if mode == "merge" and dst.exists():
            merged = _merge(json.loads(body.decode("utf-8")), json.loads(dst.read_text(encoding="utf-8")))
            dst.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            dst.write_bytes(body)
        counts[mode] += 1
    log(f"파일 교체 {counts['write']} · 새로 추가 {counts['add']} · 설정 합치기 {counts['merge']} · 보존 {counts['skip']}")
    if backup.exists():
        log(f"바뀐 파일 원본 백업: {backup}")
    new_req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    if new_req != old_req:
        log("구성요소 업데이트 중 (pip)…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")], cwd=ROOT)
    VERSION.parent.mkdir(parents=True, exist_ok=True)
    VERSION.write_text(json.dumps({"sha": info["_sha"], "date": info["date"], "updated_at": stamp}, ensure_ascii=False),
                       encoding="utf-8")
    try:  # 예전 데이터에 새 필드 채우기
        subprocess.run([sys.executable, "-c", "from insaengtem.catalog import migrate_catalog as m; m()"], cwd=ROOT)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("win"):
        try:  # 아이콘·바로가기 갱신
            subprocess.run([sys.executable, "-m", "insaengtem.winsetup", "shortcut"], cwd=ROOT, capture_output=True)
        except Exception:  # noqa: BLE001
            pass
    log(f"✅ 업데이트 완료 → {info['latest']}. 관리 화면을 다시 열면 적용됩니다.")
    return True


if __name__ == "__main__":
    try:
        if "--check" in sys.argv:
            i = check()
            print(("🆕 새 버전 있음 " if i["update"] else "최신 버전 ") + f"(설치 {i['current']} / 최신 {i['latest']} {i['date']})")
            for ch in i["changes"]:
                print("  •", ch)
        else:
            apply(force="--force" in sys.argv)
    except Exception as e:  # noqa: BLE001
        print(f"업데이트 실패: {e}\n인터넷 연결을 확인하고 다시 시도하세요. 프로그램 파일은 바뀌지 않았거나 backups 폴더에 원본이 있습니다.")
        sys.exit(1)
