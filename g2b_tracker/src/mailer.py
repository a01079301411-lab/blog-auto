"""제안서 메일 자동 발송 (네이버 메일 SMTP).

1) 첫 메일: 사장님이 Claude 에게 주소를 주면 → 구글 드라이브 '나라장터추적_연락처' 폴더에 '발송=Y' →
   PC 가 30분마다 확인해서 아직 안 보낸 주소에 한 번만 발송 (docs/이메일_공통문구.md + 제안서 + 첨부 폴더).
2) 분기 소식: 첫 메일을 받은 주소에 3·6·9·11월 1~10일(평일) 한 번씩 (docs/이메일_분기소식.md + 제안서만).
   같은 주소는 최소 45일 간격, 같은 시기 1번, 수신거부 주소 영구 제외.
3) 회신이 없어도 아무 후속 조치를 하지 않는다.

기록: data/sent.json  {주소: {기관, 발송일, 이력: [{날짜, 종류}], 수신거부}}
.env: NAVER_ID, NAVER_APP_PW, (선택) MAIL_DAILY_LIMIT=150
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
FIRST = ROOT / "docs" / "이메일_공통문구.md"
QUARTER = ROOT / "docs" / "이메일_분기소식.md"
BROCHURE = ROOT / "docs" / "소개서" / "로젠이사_기관이전_제안서.pdf"
ATTACH_DIR = ROOT / "첨부"
YES = {"y", "yes", "예", "o", "보내기", "발송", "1", "true"}
NO = {"n", "no", "수신거부", "거부", "x", "취소", "0", "false"}
QUARTER_MONTHS = (3, 6, 9, 11)
WINDOW_DAYS = range(1, 11)
MIN_GAP_DAYS = 45

# 보낸메일함 확인(IMAP)
IMAP_HOST = "imap.naver.com"


# ---------- 기록 ----------
def load_sent():
    try:
        return json.loads(SENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_sent(sent):
    SENT.write_text(json.dumps(sent, ensure_ascii=False, indent=1), encoding="utf-8")


def _last_date(info):
    days = [h["날짜"] for h in info.get("이력", [])] + [info.get("발송일", "")]
    days = [d for d in days if d]
    return max(days)[:10] if days else ""


# ---------- 문구·첨부 ----------
def first_template():
    b = re.findall(r"```\n(.*?)```", FIRST.read_text(encoding="utf-8"), flags=re.S)
    if len(b) < 2:
        raise RuntimeError("docs\\이메일_공통문구.md 에서 제목·본문을 찾지 못했어요.")
    return b[0].strip(), b[1].rstrip()


def quarter_template(month):
    if not QUARTER.exists():
        return None
    text = QUARTER.read_text(encoding="utf-8")
    m = re.search(rf"^## {month}월\s*\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    if not m:
        return None
    b = re.findall(r"```\n(.*?)```", m.group(1), flags=re.S)
    return (b[0].strip(), b[1].rstrip()) if len(b) >= 2 else None


def attachments(full=True):
    files = [BROCHURE] if BROCHURE.exists() else []
    if not full or not ATTACH_DIR.is_dir():
        return files
    for p in sorted(ATTACH_DIR.iterdir()):
        if not p.is_file() or p.name.startswith(("~", ".", "여기에")):
            continue
        if p.name == BROCHURE.name:
            continue  # 제안서 중복 방지
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


# ---------- 대상 ----------
def _contacts():
    """드라이브·data 연락처 전부 (나중 파일이 이김)."""
    import calllist
    out = {}
    for f in calllist._contact_files():
        for m in calllist._read_csv(f):
            mail = (m.get("이메일") or "").strip().lower()
            if mail and "@" in mail:
                cur = out.setdefault(mail, {"기관": "", "발송": "", "수신거부": "", "발송완료": ""})
                for k in ("기관", "발송", "수신거부", "발송완료"):
                    if m.get(k):
                        cur[k] = m[k].strip()
    return out


def apply_optouts(sent, contacts):
    for mail, c in contacts.items():
        if c.get("발송완료", "").lower() in YES and not sent.get(mail, {}).get("발송일"):
            info = sent.setdefault(mail, {"기관": c.get("기관", ""), "발송일": "", "이력": []})
            info["발송일"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            info.setdefault("이력", []).append({"날짜": info["발송일"], "종류": "첫 메일(확인 처리)"})
        if c.get("발송", "").lower() in NO or c.get("수신거부", "").lower() in YES | {"수신거부"}:
            sent.setdefault(mail, {"기관": c.get("기관", ""), "발송일": "", "이력": []})["수신거부"] = True


def first_targets(sent, contacts):
    return [{"기관": c["기관"], "이메일": mail} for mail, c in contacts.items()
            if mail not in sent and c.get("발송", "").lower() in YES]


def quarter_targets(sent, today=None):
    today = today or datetime.now()
    if today.month not in QUARTER_MONTHS or today.day not in WINDOW_DAYS or today.weekday() >= 5:
        return [], None
    key = f"{today:%Y-%m}"
    out = []
    for mail, info in sent.items():
        if info.get("수신거부") or not info.get("발송일"):
            continue
        if any(h.get("종류") == f"분기 {key}" for h in info.get("이력", [])):
            continue
        last = _last_date(info)
        if last and (today - datetime.strptime(last, "%Y-%m-%d")).days < MIN_GAP_DAYS:
            continue
        out.append({"기관": info.get("기관", ""), "이메일": mail})
    return out, key


# ---------- 발송 ----------
PER_CONNECTION = 10   # 네이버는 한 연결에서 많이 보내면 452 Too many commands → 10통마다 다시 연결
GAP_SECONDS = 6


def _send(batch, on_sent):
    """batch: [(target, EmailMessage)]. 한 통 보낼 때마다 on_sent(target) 로 즉시 기록.
    네이버가 막으면(452 등) 거기서 멈추고 (보낸 목록, 남은 수, 이유) 를 돌려준다. 남은 건 다음 실행 때 보낸다."""
    uid, pw, _ = _account()
    done, i = [], 0
    while i < len(batch):
        chunk = batch[i:i + PER_CONNECTION]
        try:
            with smtplib.SMTP_SSL("smtp.naver.com", 465, timeout=60) as s:
                s.login(uid, pw)
                for t, m in chunk:
                    try:
                        s.send_message(m)
                    except smtplib.SMTPRecipientsRefused:
                        print(f"  ✕ 주소 거부(없는 주소일 수 있음): {t['이메일']}")
                        on_sent(dict(t, 종류="주소거부"))
                        i += 1
                        continue
                    done.append(t)
                    on_sent(t)
                    i += 1
                    time.sleep(GAP_SECONDS)
        except smtplib.SMTPAuthenticationError:
            raise
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPServerDisconnected,
                smtplib.SMTPResponseException, OSError) as e:
            reason = getattr(e, "smtp_error", b"")
            reason = reason.decode("utf-8", "ignore") if isinstance(reason, bytes) else str(reason or e)
            return done, len(batch) - i, reason.strip()[:120]
        time.sleep(20)  # 연결 사이 쉬기
    return done, 0, ""


def _sent_today(sent):
    day = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for i in sent.values() for h in i.get("이력", []) if h.get("날짜", "").startswith(day))


def run(test=False):
    import notifier
    uid, pw, sender = _account()
    sent = load_sent()
    contacts = _contacts()
    apply_optouts(sent, contacts)
    limit = int(os.getenv("MAIL_DAILY_LIMIT") or 150)
    room = max(0, limit - _sent_today(sent))

    jobs = []  # (target, 종류, 제목, 본문, 첨부)
    s, b = first_template()
    if test:
        jobs.append(({"기관": "(시험)", "이메일": sender}, "시험", s, b, attachments(True)))
    else:
        full = attachments(True)
        for t in first_targets(sent, contacts):
            jobs.append((t, "첫 메일", s, b, full))
        qt, key = quarter_targets(sent)
        tpl = quarter_template(datetime.now().month) if qt else None
        if tpl:
            for t in qt:
                jobs.append((t, f"분기 {key}", tpl[0], tpl[1], attachments(False)))
        if len(jobs) > room:
            print(f"오늘 발송 한도({limit}건) 때문에 {room}건만 보내고 나머지는 다음 실행 때 보냅니다.")
            jobs = jobs[:room]
    if not jobs:
        save_sent(sent)
        print("보낼 메일이 없어요.")
        return 0

    batch = [(dict(t, 종류=k), build(t["이메일"], t["기관"], s_, b_, f, sender)) for t, k, s_, b_, f in jobs]
    log_path = ROOT / "logs" / "mail_log.csv"

    def on_sent(t):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_file = not log_path.exists()
        with log_path.open("a", encoding="utf-8-sig") as fh:
            if new_file:
                fh.write("날짜,종류,기관,이메일\n")
            fh.write(f"{now},{t['종류']},{t['기관']},{t['이메일']}\n")
        if test:
            return
        info = sent.setdefault(t["이메일"], {"기관": t["기관"], "발송일": "", "이력": []})
        info.setdefault("이력", []).append({"날짜": now, "종류": t["종류"]})
        if t["종류"] == "첫 메일":
            info["발송일"], info["기관"] = now, t["기관"] or info.get("기관", "")
        save_sent(sent)  # 한 통마다 바로 저장 → 중간에 멈춰도 중복 발송 없음

    try:
        done, left, reason = _send(batch, on_sent)
    except smtplib.SMTPAuthenticationError as e:
        detail = e.smtp_error.decode("utf-8", "ignore") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        print(f"네이버 로그인 실패 (코드 {e.smtp_code}: {detail.strip()[:120]})")
        print("확인 순서: ① 네이버 메일 > 환경설정 > POP3/IMAP 설정 > POP3/SMTP 사용 '사용함' + 저장"
              " ② 2단계 인증을 쓰면 '애플리케이션 비밀번호'(12자리)"
              " ③ 아이디는 noblesse0913 처럼 @naver.com 빼고 → 7_메일설정.bat 다시 실행")
        notifier.notify("[나라장터] 메일 발송 실패: 네이버 로그인 (7_메일설정.bat 확인)")
        save_sent(sent)
        return 0
    save_sent(sent)
    firsts = [t for t in done if t["종류"] in ("첫 메일", "시험")]
    quarters = [t for t in done if t["종류"].startswith("분기")]
    lines = []
    if firsts:
        lines.append(f"[나라장터] 제안서 메일 {len(firsts)}건 발송")
        lines += [f"  · {t['기관']} {t['이메일']}" for t in firsts]
    if quarters:
        lines.append(f"[나라장터] 분기 소식 {len(quarters)}건 발송 ({quarters[0]['종류']})")
    if left:
        lines.append(f"⏸ 네이버가 잠시 막아서 {left}건은 다음 실행(30분 뒤)에 이어서 보냅니다. ({reason})")
    msg = "\n".join(lines)
    print(msg)
    notifier.notify(msg)
    return len(done)


def check_sent_box(days=3):
    """네이버 보낸메일함(IMAP)에서 최근 N일 동안 로젠이사 제안서·소식 메일을 받은 주소를 읽어
    data/sent.json 에 '보냄'으로 기록한다 (중간에 멈춰 기록이 빠진 경우 복구용). 결과는 output/보낸메일_확인.csv."""
    import email
    import imaplib
    from email.header import decode_header, make_header
    from email.utils import getaddresses
    from datetime import timedelta
    uid, pw, _ = _account()
    try:
        im = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        im.login(uid, pw)
    except Exception as e:
        print(f"보낸메일함에 접속하지 못했어요: {e}")
        print("네이버 메일 > 환경설정 > POP3/IMAP 설정 > 'IMAP/SMTP 사용' 도 '사용함' + 저장 후 다시 실행해 주세요.")
        return None
    typ, boxes = im.list()
    names = [b.decode("utf-8", "ignore") for b in boxes or []]
    sent_box = next((n.split(' "/" ')[-1].strip('"') for n in names if "Sent" in n or "&vPSwuNO4ycDVaA-" in n), "Sent Messages")
    im.select(f'"{sent_box}"', readonly=True)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = im.search(None, f'(SINCE "{since}")')
    rows = []
    for num in (data[0].split() if data and data[0] else []):
        typ, msg_data = im.fetch(num, "(BODY.PEEK[HEADER.FIELDS (TO SUBJECT DATE)])")
        msg = email.message_from_bytes(msg_data[0][1])
        subj = str(make_header(decode_header(msg.get("Subject", ""))))
        if "로젠이사" not in subj:
            continue
        for _, addr in getaddresses([msg.get("To", "")]):
            rows.append((msg.get("Date", ""), addr.lower(), subj))
    im.logout()
    sent = load_sent()
    added = 0
    for date, addr, subj in rows:
        if addr and addr != f"{uid}@naver.com" and not sent.get(addr, {}).get("발송일"):
            info = sent.setdefault(addr, {"기관": "", "발송일": "", "이력": []})
            info["발송일"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            info.setdefault("이력", []).append({"날짜": info["발송일"], "종류": "첫 메일(보낸메일함 확인)"})
            added += 1
    save_sent(sent)
    out = ROOT / "output" / "보낸메일_확인.csv"
    with out.open("w", encoding="utf-8-sig") as fh:
        fh.write("보낸시각,받는주소,제목\n")
        for date, addr, subj in rows:
            fh.write(f"\"{date}\",{addr},\"{subj}\"\n")
    others = sorted({a for _, a, _ in rows if a != f"{uid}@naver.com"})
    print(f"보낸메일함 최근 {days}일: 로젠이사 메일 {len(rows)}통, 받은 주소 {len(others)}곳 (새로 '보냄' 기록 {added}곳)")
    for a in others:
        print("  ·", a)
    print(f"전체 목록: {out}")
    return others
