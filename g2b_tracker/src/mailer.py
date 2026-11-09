"""제안서 메일 자동 발송 (네이버 메일 SMTP).

흐름: 사장님이 Claude 에게 "덕화중 abc@korea.kr 보내" → Claude 가 구글 드라이브 '나라장터추적_연락처' 폴더에
'발송=Y' 로 적음 → PC 동기화 → 이 프로그램이 30분마다 확인해서 아직 안 보낸 주소에만 발송 → 텔레그램 알림.

- 문구: docs/이메일_공통문구.md 의 첫 번째 코드블록(제목)과 두 번째 코드블록(본문). '○○' 자리에 기관 이름.
- 첨부: docs/소개서/로젠이사_기관이전_제안서.pdf + '첨부' 폴더 안의 모든 파일 (확인서·사업자등록증·허가증).
- 같은 주소에는 두 번 보내지 않는다 (data/sent.json).
- .env: NAVER_ID (아이디만), NAVER_APP_PW (네이버 '애플리케이션 비밀번호' 또는 메일 비밀번호)
"""
import json
import mimetypes
import os
import re
import smtplib
import time
from datetime import datetime
from email.header import Header
from email.message import EmailMessage
from email.utils import formataddr

from config import DATA, ROOT

SENT = DATA / "sent.json"
TEMPLATE = ROOT / "docs" / "이메일_공통문구.md"
BROCHURE = ROOT / "docs" / "소개서" / "로젠이사_기관이전_제안서.pdf"
ATTACH_DIR = ROOT / "첨부"
YES = {"y", "yes", "예", "o", "보내기", "발송", "1", "true"}


def load_sent():
    try:
        return json.loads(SENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def template():
    text = TEMPLATE.read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)```", text, flags=re.S)
    if len(blocks) < 2:
        raise RuntimeError("docs\\이메일_공통문구.md 에서 제목·본문 코드블록을 찾지 못했어요.")
    return blocks[0].strip(), blocks[1].rstrip()


def attachments():
    files = []
    if BROCHURE.exists():
        files.append(BROCHURE)
    if ATTACH_DIR.is_dir():
        for p in sorted(ATTACH_DIR.iterdir()):
            if not p.is_file() or p.name.startswith(("~", ".", "여기에")):
                continue
            if p.name == BROCHURE.name and BROCHURE.exists():
                continue  # 제안서는 이미 붙음 (중복 방지)
            if "통장" in p.name:
                print(f"  ※ {p.name} 은(는) 첨부하지 않아요 (통장 사본은 계약 단계에서만 제출)")
                continue
            files.append(p)
    return files


def build(to, org, subject, body, files, sender):
    msg = EmailMessage()
    msg["Subject"] = subject.replace("○○", org)
    msg["From"] = formataddr((str(Header("로젠이사 서성민", "utf-8")), sender))
    msg["To"] = to
    msg.set_content(body.replace("○○", org))
    for f in files:
        ctype, _ = mimetypes.guess_type(f.name)
        main, sub = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(f.read_bytes(), maintype=main, subtype=sub, filename=f.name)
    return msg


def _account():
    uid = (os.getenv("NAVER_ID") or "").strip().replace("@naver.com", "")
    pw = (os.getenv("NAVER_APP_PW") or "").strip()
    if not (uid and pw):
        raise RuntimeError("NAVER_ID / NAVER_APP_PW 가 비어 있어요. 7_메일설정.bat 을 먼저 실행해 주세요.")
    return uid, pw, f"{uid}@naver.com"


def send_all(messages):
    uid, pw, _ = _account()
    with smtplib.SMTP_SSL("smtp.naver.com", 465, timeout=60) as s:
        s.login(uid, pw)
        for m in messages:
            s.send_message(m)
            time.sleep(3)


def pending():
    """드라이브·data 연락처 중 '발송'이 Y 이고 아직 안 보낸 것."""
    import calllist
    sent = load_sent()
    out, seen = [], set()
    for f in calllist._contact_files():
        for m in calllist._read_csv(f):
            mail = (m.get("이메일") or "").strip().lower()
            if not mail or "@" not in mail or mail in sent or mail in seen:
                continue
            if (m.get("발송") or "").strip().lower() in YES:
                out.append({"기관": m.get("기관", "").strip(), "이메일": mail})
                seen.add(mail)
    return out


def run(test=False):
    import notifier
    subject, body = template()
    files = attachments()
    uid, pw, sender = _account()
    if test:
        targets = [{"기관": "(시험) 덕화중학교", "이메일": sender}]
    else:
        targets = pending()
    if not targets:
        print("보낼 메일이 없어요.")
        return 0
    names = ", ".join(f.name for f in files)
    print(f"첨부 {len(files)}개: {names}")
    if len(files) < 2:
        print("⚠ '첨부' 폴더가 비어 있어요. 확인서·사업자등록증·허가증을 넣어 주세요.")
    msgs = [build(t["이메일"], t["기관"], subject, body, files, sender) for t in targets]
    try:
        send_all(msgs)
    except smtplib.SMTPAuthenticationError as e:
        detail = e.smtp_error.decode("utf-8", "ignore") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        print(f"네이버 로그인 실패 (코드 {e.smtp_code}: {detail.strip()[:120]})")
        print("확인 순서: ① 네이버 메일 > 환경설정 > POP3/IMAP 설정 > POP3/SMTP 사용 '사용함' + 저장"
              " ② 2단계 인증을 쓰면 '애플리케이션 비밀번호'(12자리, 띄어쓰기 없이)"
              " ③ 아이디는 로그인 아이디(noblesse0913)만, @naver.com 빼고"
              " → 7_메일설정.bat 다시 실행")
        notifier.notify("[나라장터] 메일 발송 실패: 네이버 로그인 (7_메일설정.bat 확인)")
        return 0
    if not test:
        sent = load_sent()
        day = datetime.now().strftime("%Y-%m-%d %H:%M")
        for t in targets:
            sent[t["이메일"]] = {"기관": t["기관"], "발송일": day}
        SENT.write_text(json.dumps(sent, ensure_ascii=False, indent=1), encoding="utf-8")
    line = "\n".join(f"  · {t['기관']} {t['이메일']}" for t in targets)
    msg = f"[나라장터] 제안서 메일 {len(targets)}건 발송 (첨부 {len(files)}개)\n{line}\n→ 이틀 뒤 확인 전화"
    print(msg)
    notifier.notify(msg)
    return len(targets)
