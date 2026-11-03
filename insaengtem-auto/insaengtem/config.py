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
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


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
