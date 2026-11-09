"""네이버 메일 연결 (7_메일설정.bat): 아이디·비밀번호 저장 후 나에게 시험 메일."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def save(values):
    text = ENV.read_text(encoding="utf-8-sig") if ENV.exists() else ""
    for k, v in values.items():
        if re.search(rf"^{k}=.*$", text, flags=re.M):
            text = re.sub(rf"^{k}=.*$", lambda _: f"{k}={v}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{k}={v}\n"
    ENV.write_text(text, encoding="utf-8")


def main():
    print("네이버 메일로 제안서를 보내기 위한 설정입니다.\n")
    print("먼저 네이버 메일 > 환경설정 > POP3/IMAP 설정 > 'POP3/SMTP 사용' 을 '사용함' 으로 바꿔 주세요.")
    print("2단계 인증을 쓰면: 네이버 내정보 > 보안설정 > 애플리케이션 비밀번호 만들기 → 그 비밀번호를 쓰세요.\n")
    uid = input("네이버 아이디 (예: noblesse0913) > ").strip().replace("@naver.com", "")
    pw = input("비밀번호 (또는 애플리케이션 비밀번호) > ").strip().replace(" ", "")
    if not (uid and pw):
        print("비어 있어서 저장하지 않았어요.")
        return
    save({"NAVER_ID": uid, "NAVER_APP_PW": pw})
    print("\n저장했어요. 나에게 시험 메일을 보냅니다...")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import importlib
    import config
    importlib.reload(config)
    import os
    os.environ["NAVER_ID"], os.environ["NAVER_APP_PW"] = uid, pw
    import mailer
    if mailer.run(test=True):
        print(f"\n{uid}@naver.com 받은메일함에서 첨부파일까지 확인해 주세요. 괜찮으면 9_메일자동발송등록.bat 실행.")


if __name__ == "__main__":
    main()
