"""텔레그램 알림. .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID가 없으면 화면에만 출력한다."""
import json
import logging
import urllib.request

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)


def notify(text):
    log.info("알림: %s", text)
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=15)
    except Exception as e:  # 알림이 실패해도 프로그램은 멈추지 않는다
        log.warning("텔레그램 알림 실패: %s", e)
