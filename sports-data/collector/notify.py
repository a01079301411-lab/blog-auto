"""텔레그램 채널 자동 발송(무료). 토큰이 없으면 아무것도 하지 않는다.

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (예: @채널아이디)
문구는 정보 전달만 한다. 구매 권유·픽·적중 보장 표현은 넣지 않는다.
"""
import json
import os
import urllib.parse
import urllib.request


def send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    body = urllib.parse.urlencode({
        "chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("ok", False)
