"""설정·경로·비밀값 로딩. 외부 의존성 없이 .env 를 직접 읽는다."""
from __future__ import annotations

import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRODUCTS = DATA / "products"
SCHEDULES = DATA / "schedules"
TRENDS = DATA / "trends"
STATE = DATA / "state"
OUT = ROOT / "out"
SECRETS = ROOT / "secrets"
VIDEO = ROOT / "video"


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
# 설치 스크립트가 찾은 ffmpeg 폴더를 PATH 앞에 (바탕화면 아이콘 실행 시 PATH 미갱신 대비)
if os.environ.get("FFMPEG_DIR"):
    os.environ["PATH"] = os.environ["FFMPEG_DIR"] + os.pathsep + os.environ.get("PATH", "")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


@lru_cache(maxsize=1)
def settings() -> dict:
    return json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"환경변수 {name} 가 비어 있습니다. .env 를 확인하세요 (.env.example 참고).")
    return v


def tz() -> ZoneInfo:
    return ZoneInfo(settings()["timezone"])


def now() -> datetime:
    return datetime.now(tz())


def parse_when(s: str) -> datetime:
    """'2026-11-04 12:00' (KST) → aware datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz())


def fmt_when(d: datetime) -> str:
    return d.astimezone(tz()).strftime("%Y-%m-%d %H:%M")


def set_env_values(values: dict) -> None:
    """.env 파일의 키를 갱신(없으면 추가). 다른 줄·주석은 보존."""
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    done = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in values:
            lines[i] = f"{k}={values[k]}"
            done.add(k)
    for k, v in values.items():
        if k not in done:
            lines.append(f"{k}={v}")
        os.environ[k] = str(v)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
