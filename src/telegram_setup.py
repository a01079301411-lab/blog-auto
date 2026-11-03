"""텔레그램 알림 연결: 4_텔레그램연결.bat 을 더블클릭하면 실행된다.

봇 토큰을 붙여 넣고, 텔레그램에서 봇에게 메시지를 한 번 보내면
대화방 번호(CHAT_ID)를 알아내서 .env에 저장하고 시험 메시지를 보낸다.
"""
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def call(token, method, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload else None
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def read_env():
    return ENV_FILE.read_text(encoding="utf-8-sig") if ENV_FILE.exists() else ""


def save_env(values):
    """.env에서 해당 줄만 바꾼다. 없으면 맨 아래에 붙인다. 다른 줄은 건드리지 않는다."""
    text = read_env()
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def current(key):
    match = re.search(rf"^{key}=(.*)$", read_env(), flags=re.M)
    return match.group(1).strip() if match else ""


def main():
    if not ENV_FILE.exists():
        print(".env 파일이 없어요. 0_처음설치.bat 을 먼저 실행해 주세요.")
        return

    token = current("TELEGRAM_BOT_TOKEN")
    if token:
        print("이미 저장된 봇 토큰을 씁니다. (바꾸려면 .env 에서 TELEGRAM_BOT_TOKEN 줄을 지우고 다시 실행)")
    else:
        token = input("BotFather 가 준 봇 토큰을 붙여 넣고 엔터 (마우스 오른쪽 클릭 = 붙여넣기):\n> ").strip()
    try:
        bot = call(token, "getMe")["result"]
    except Exception:
        print("\n토큰이 맞지 않아요. BotFather 메시지의 토큰을 처음부터 끝까지 다시 복사해 주세요.")
        return
    print(f"\n봇 확인: @{bot['username']}")

    chat_id = None
    for _ in range(3):
        input(f"\n텔레그램에서 @{bot['username']} 를 찾아 [시작] 을 누르고, 아무 메시지(예: 안녕)를 보낸 뒤 여기서 엔터")
        try:
            updates = call(token, "getUpdates")["result"]
        except Exception as e:
            print(f"텔레그램에 연결하지 못했어요: {e}")
            continue
        chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
        if chats:
            chat_id = chats[-1]
            break
        print("아직 메시지가 안 보여요. 봇에게 메시지를 보냈는지 확인하고 다시 엔터를 눌러 주세요.")
    if chat_id is None:
        print("\n대화방을 찾지 못했어요. 잠시 뒤 다시 실행해 주세요.")
        return

    save_env({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": str(chat_id)})
    call(token, "sendMessage", {"chat_id": chat_id,
                                "text": "[블로그 자동화] 알림 연결 완료. 앞으로 글이 저장되거나 문제가 생기면 여기로 알려드려요."})
    print("\n연결 끝! 텔레그램에 시험 메시지가 왔는지 확인해 주세요.")


if __name__ == "__main__":
    main()
