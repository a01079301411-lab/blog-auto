""".env 파일을 읽어서 프로그램 전체 설정을 모아 둔 곳."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name, default=""):
    return (os.getenv(name) or default).strip()


def _bool(name):
    return _get(name).lower() in ("1", "true", "yes", "y", "on")


# ── 폴더 ──
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"
SAMPLES_DIR = ROOT / "samples"
OUTPUT_DIR = ROOT / "output"  # 발행 전 미리보기
LOGS_DIR = ROOT / "logs"  # 실행 기록, 실패 화면 캡처
PROFILE_DIR = ROOT / "browser_profile"  # 네이버 로그인 상태 (절대 공유 금지)
HISTORY_FILE = DATA_DIR / "history.json"  # 발행 기록 (중복 방지)
for folder in (OUTPUT_DIR, LOGS_DIR):
    folder.mkdir(exist_ok=True)

# ── 네이버 ──
BLOG_ID = _get("BLOG_ID") or _get("NAVER_ID")
NAVER_CATEGORY = _get("NAVER_CATEGORY")

# ── AI ──
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
MODEL = _get("MODEL") or _get("ANTHROPIC_MODEL") or "claude-sonnet-5"

# ── 회사 ──
COMPANY_PHONE = _get("COMPANY_PHONE")

# ── 사진 ──
PHOTO_DIR = Path(_get("PHOTO_DIR")) if _get("PHOTO_DIR") else ROOT / "photos"

# ── 실행 ──
AUTO_PUBLISH = _bool("AUTO_PUBLISH")  # false면 임시저장까지만
DAILY_LIMIT = int(_get("DAILY_LIMIT", "2"))
PUBLISH_WINDOW_START = _get("PUBLISH_WINDOW_START", "08:30")
PUBLISH_WINDOW_END = _get("PUBLISH_WINDOW_END", "11:30")

# ── 텔레그램 알림 (선택) ──
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")
