"""텔레그램 알림. 토큰이 없으면 화면에만 출력한다. 4,000자 넘으면 나눠 보낸다.
연결이 잠깐 끊겨도(WinError 10054 등) 3번까지 다시 시도한다."""
import json
import logging
import time
import urllib.request

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)


def _post(text):
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20)


def notify(text):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) or not text:
        return
    for i in range(0, len(text), 3900):
        part = text[i:i + 3900]
        for attempt in range(3):
            try:
                _post(part)
                break
            except Exception as e:  # 알림이 실패해도 프로그램은 계속
                if attempt == 2:
                    log.warning("텔레그램 알림 실패(3번 시도): %s", e)
                else:
                    time.sleep(3 * (attempt + 1))
