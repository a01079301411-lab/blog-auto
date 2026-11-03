"""텔레그램 알림. 토큰이 없으면 화면에만 출력한다. 4,000자 넘으면 나눠 보낸다."""
import json
import logging
import urllib.request

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)


def notify(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    for i in range(0, len(text), 3900):
        data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text[i:i + 3900]}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                     data=data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:  # 알림이 실패해도 프로그램은 계속
            log.warning("텔레그램 알림 실패: %s", e)
