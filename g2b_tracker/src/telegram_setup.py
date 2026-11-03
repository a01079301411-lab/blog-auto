"""텔레그램 알림 연결 (5_텔레그램연결.bat).

1) 블로그 프로그램 .env 에 텔레그램 설정이 있으면 그대로 가져온다 (같은 봇·같은 대화방으로 알림, 앞에 [나라장터] 표시).
2) 없으면 봇 토큰을 붙여 넣고 봇에게 메시지를 보내면 대화방 번호를 알아낸다.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def call(token, method, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def read(path):
    return path.read_text(encoding="utf-8-sig", errors="ignore") if path.exists() else ""


def get(text, key):
    m = re.search(rf"^{key}=(.*)$", text, flags=re.M)
    return m.group(1).strip() if m else ""


def save(values):
    text = read(ENV)
    for k, v in values.items():
        if re.search(rf"^{k}=.*$", text, flags=re.M):
            text = re.sub(rf"^{k}=.*$", lambda _: f"{k}={v}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{k}={v}\n"
    ENV.write_text(text, encoding="utf-8")


def find_blog_env():
    """블로그 프로그램 폴더의 .env 찾기 (바탕화면·문서·다운로드·C:\\ 아래 3단계까지)."""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    roots = [ROOT.parent, ROOT.parent.parent, home / "Desktop", home / "바탕 화면", home / "Documents",
             home / "Downloads", home / "OneDrive" / "바탕 화면", home / "OneDrive" / "Desktop", Path("C:/")]
    seen = set()
    for base in roots:
        if not base.exists():
            continue
        for depth in range(0, 4):
            for env in base.glob("/".join(["*"] * depth + [".env"])) if depth else [base / ".env"]:
                try:
                    env = env.resolve()
                except OSError:
                    continue
                if env in seen or env == ENV.resolve() or not env.is_file():
                    continue
                seen.add(env)
                text = read(env)
                if get(text, "TELEGRAM_BOT_TOKEN") and get(text, "TELEGRAM_CHAT_ID"):
                    return env, get(text, "TELEGRAM_BOT_TOKEN"), get(text, "TELEGRAM_CHAT_ID")
    return None


def main():
    if not ENV.exists():
        print(".env 파일이 없어요. 0_처음설치.bat 을 먼저 실행해 주세요.")
        return
    token, chat = get(read(ENV), "TELEGRAM_BOT_TOKEN"), get(read(ENV), "TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("블로그 프로그램의 텔레그램 설정을 찾는 중...")
        found = find_blog_env()
        if found:
            env, token, chat = found
            print(f"찾았어요: {env}\n같은 봇으로 알림을 보냅니다. (메시지 앞에 [나라장터] 가 붙어서 구분돼요)")
        else:
            print("블로그 설정을 못 찾았어요. 새로 연결합니다.")
            print("텔레그램에서 @BotFather → /newbot → 이름 입력 → 받은 토큰을 아래에 붙여 넣기")
            print("(블로그용 봇 토큰이 있으면 그걸 붙여 넣어도 됩니다)")
            token = input("봇 토큰 (마우스 오른쪽 클릭 = 붙여넣기)\n> ").strip()
            chat = ""
    try:
        bot = call(token, "getMe")["result"]
    except Exception:
        print("\n토큰이 맞지 않아요. 토큰을 처음부터 끝까지 다시 복사해 주세요.")
        return
    print(f"봇 확인: @{bot['username']}")
    if not chat:
        for _ in range(3):
            input(f"\n텔레그램에서 @{bot['username']} 에게 아무 메시지(예: 안녕)를 보낸 뒤 여기서 엔터")
            ups = call(token, "getUpdates").get("result", [])
            ids = [u["message"]["chat"]["id"] for u in ups if "message" in u]
            if ids:
                chat = str(ids[-1])
                break
            print("아직 메시지가 안 보여요. 다시 보내고 엔터.")
        if not chat:
            print("대화방을 찾지 못했어요. 잠시 뒤 다시 실행해 주세요.")
            return
    save({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat})
    call(token, "sendMessage", {"chat_id": chat, "text": "[나라장터] 알림 연결 완료. 매일 아침 대구·경북 이사·이전·보관 공고 중 새로 뜬 것만 보내드려요."})
    print("\n연결 끝! 텔레그램에 시험 메시지가 왔는지 확인하세요.")


if __name__ == "__main__":
    main()
