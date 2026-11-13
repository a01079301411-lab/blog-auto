"""설정 읽기. 값은 모두 .env 에서 온다."""
import os
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # 처음설치 전이라도 --selftest 는 돌게
    pass


def _key():
    key = (os.getenv("DATA_GO_KR_KEY") or "").strip()
    # Encoding 키(%2B, %3D 가 들어간 것)를 붙여 넣어도 Decoding 키로 바꿔 쓴다
    return unquote(key) if "%" in key else key


DATA_GO_KR_KEY = _key()
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS") or 3)
ALERT_MIN_SCORE = int(os.getenv("ALERT_MIN_SCORE") or 40)
# 입찰공고 참가자격 업종 필터: 이 코드(업종)가 있는 공고만 추적. 비우면 업종 필터 끔.
LICENSE_CODE = (os.getenv("LICENSE_CODE") if os.getenv("LICENSE_CODE") is not None else "7605").strip()
LICENSE_NAME = os.getenv("LICENSE_NAME") or "화물자동차운송주선사업"

# 조달청 나라장터 OpenAPI 주소 (2025년 차세대 나라장터 기준). 바뀌면 .env 에서 덮어쓸 수 있다.
BASES = {
    "bid": os.getenv("BID_BASE") or "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
    "pre": os.getenv("PRE_BASE") or "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService",
    "plan": os.getenv("PLAN_BASE") or "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService",
    "award": os.getenv("AWARD_BASE") or "https://apis.data.go.kr/1230000/as/ScsbidInfoService",
    "contract": os.getenv("CONTRACT_BASE") or "https://apis.data.go.kr/1230000/ao/CntrctInfoService",
}

for d in (OUTPUT, LOGS, ROOT / "첨부"):
    d.mkdir(exist_ok=True)
