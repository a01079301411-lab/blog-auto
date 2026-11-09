"""전화 영업 콜리스트: 대구·경북에서 전화할 곳 전부를 우선순위(탑다운) 한 장으로.

S  이사·집기이전을 실제로 계약한 기관 + 그 계약 담당자 직통 (나라장터 계약정보)
A  지금 진행 중인 공사·공고의 기관 담당자 (매일 추적)
B  대구·경북 전체 학교 행정실 대표전화 (나이스) — 학교가 이사 수의계약의 60%
C  기본 영업 리스트 78곳 중 위에 없는 기관 (대표번호로 총무·재무과 연결)
→ output/영업콜리스트_날짜.xlsx + 영업DB.xlsx 맨 앞 '콜리스트' 시트 (통화결과 칸은 기존 값 유지)
"""
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

from config import DATA, OUTPUT, ROOT
import neis

SHEET = "콜리스트"
COLS = ["순위", "등급", "기관", "기관유형", "지역", "연락할 곳", "전화", "이메일", "근거", "최근 이사계약",
        "이사계약 횟수", "대본", "영업 타이밍", "통화결과", "다음연락일", "메모"]
NEAR = ("대구", "경산", "칠곡", "고령", "성주", "군위", "달성", "왜관", "하양", "진량")


def _near(*texts):
    t = " ".join(x or "" for x in texts)
    return any(n in t for n in NEAR)


def _norm(name):
    """기관 이름 맞추기용: '대구광역시교육청 경상여자고등학교' → '경상여자고등학교'."""
    n = re.sub(r"\(.*?\)|\s", "", name or "")
    m = re.search(r"([가-힣A-Za-z0-9]+(초등학교|중학교|고등학교|학교))$", n)
    return m.group(1) if m else n


def _script(org, kind):
    if any(w in org for w in ("학교", "초등", "중학", "고등")):
        return "4-4 학교 행정실"
    if kind == "공사":
        return "4-2 시설부서"
    return "4-1 계약부서"


def _timing(org, last):
    if any(w in org for w in ("학교", "초등", "중학", "고등")):
        return "지금(11월): 12~2월 겨울방학 공사 견적 명단 / 5~6월: 여름방학"
    if "조직개편" in (last or "") or "부서이동" in (last or ""):
        return "12월·6월: 1월·7월 조직개편 이사 전에"
    return "리모델링·이전 계획 확인"


def build():
    rows, seen_org = [], set()
    contacts = {}
    try:
        contacts = json.loads((DATA / "contacts_v2.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    now_year = datetime.now().year
    # S, A: 나라장터에서 모은 관공서 담당자
    for c in contacts.values():
        if c.get("구분") not in ("기관", None) or not c.get("전화"):
            continue
        org = c["기관"]
        n = int(c.get("이사계약 이력") or 0)
        day = c.get("최근일") or ""
        score = 0
        if n:
            grade = "S"
            score = 100 + min(n, 5) * 10 + (20 if day[:4] >= str(now_year - 1) else 0)
        else:
            grade = "A"
            score = 60 + (10 if day[:7] >= datetime.now().strftime("%Y-%m") else 0)
        near = c.get("지역") == "대구근교" or _near(org)
        score += 25 if near else 0
        rows.append({"등급": grade, "_score": score, "기관": org, "기관유형": c.get("기관유형", ""),
                     "지역": "대구근교" if near else "경북", "연락할 곳": f'{c.get("담당부서", "")} {c.get("담당자", "")}'.strip(),
                     "전화": c["전화"], "이메일": c.get("이메일", ""),
                     "근거": f'이사계약 {n}회' + (f' · 지금 거래업체 {c.get("최근 수행업체")}' if c.get("최근 수행업체") else "") if n else f'진행 중 공고: {c.get("최근 건", "")[:40]}',
                     "최근 이사계약": f'{day} {c.get("최근 건", "")[:50]} {c.get("이사계약 금액(최근)", "")}'.strip() if n else "",
                     "이사계약 횟수": n, "대본": _script(org, ""), "영업 타이밍": _timing(org, c.get("최근 건"))})
        seen_org.add(_norm(org))
    # B: 학교 전체
    for s in neis.load():
        if _norm(s["학교명"]) in seen_org or not s.get("전화"):
            continue
        near = s["시도"] == "대구" or _near(s["주소"], s["교육지원청"])
        lvl = {"고등학교": 15, "중학교": 10, "초등학교": 8, "특수학교": 12}.get(s["학교급"], 3)
        rows.append({"등급": "B", "_score": 30 + lvl + (25 if near else 0), "기관": s["학교명"], "기관유형": f'{s["학교급"]}({s["설립"]})',
                     "지역": "대구근교" if near else "경북", "연락할 곳": "행정실", "전화": s["전화"], "이메일": "",
                     "근거": f'{s["교육지원청"]} · 학교가 이사 수의계약의 60%', "최근 이사계약": "", "이사계약 횟수": 0,
                     "대본": "4-4 학교 행정실", "영업 타이밍": _timing(s["학교명"], "")})
        seen_org.add(_norm(s["학교명"]))
    # C: 기본 리스트
    src = DATA / "targets.csv"
    if src.exists():
        for t in csv.DictReader(src.open(encoding="utf-8-sig")):
            if _norm(t["기관"]) in seen_org or t["우선순위"] == "C":
                continue
            near = t.get("권역") == "대구근교"
            rows.append({"등급": "C", "_score": 10 + (15 if t["우선순위"] == "A" else 0) + (10 if near else 0),
                         "기관": t["기관"], "기관유형": t["유형"], "지역": t.get("권역", ""), "연락할 곳": t["1차 접촉부서"],
                         "전화": t.get("알려진 연락처(재확인 필요)", "") or "대표번호 검색", "이메일": "",
                         "근거": t["영업 포인트"], "최근 이사계약": "", "이사계약 횟수": 0, "대본": "4-1 계약부서",
                         "영업 타이밍": "상시"})
    _merge_mine(rows)
    _mark_sent(rows)
    rows.sort(key=lambda r: -r["_score"])
    for i, r in enumerate(rows, 1):
        r["순위"] = i
    return rows


def _contact_files():
    """내 연락처 파일 전부: data\\my_contacts.csv + 구글 드라이브 '나라장터추적_연락처' 폴더의 모든 csv.
    드라이브 폴더는 Claude 가 메일 주소를 받을 때마다 새 csv 를 추가한다 (PC 구글 드라이브 동기화로 내려옴)."""
    import os
    import string
    files = [p for p in (DATA / "my_contacts.csv", ROOT / "my_contacts.csv") if p.exists()]
    dirs = []
    if os.getenv("MY_CONTACTS_DIR"):
        dirs.append(Path(os.getenv("MY_CONTACTS_DIR")))
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    roots = [Path(f"{d}:/") for d in string.ascii_uppercase[3:]] + [home, home / "Google Drive"]
    for r in roots:
        for sub in ("내 드라이브", "My Drive", ""):
            dirs.append(r / sub / "나라장터추적_연락처")
    seen = set()
    for d in dirs:
        try:
            if d.is_dir() and d.resolve() not in seen:
                seen.add(d.resolve())
                files += sorted(d.glob("*.csv"))
        except OSError:
            continue
    return files


def _read_csv(path):
    for enc in ("utf-8-sig", "cp949", "euc-kr"):  # 엑셀에서 저장하면 cp949
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, OSError):
            text = None
    if not text:
        return []
    lines = [l for l in text.splitlines() if l.strip()]
    delim = "\t" if lines and "\t" in lines[0] and "," not in lines[0] else ","
    return [{(k or "").strip(): (v or "").strip() for k, v in m.items()} for m in csv.DictReader(lines, delimiter=delim)]


def _merge_mine(rows):
    """통화로 받은 메일·담당자 (열: 기관, 이메일, 담당자, 전화, 메모). 같은 기관은 나중 파일이 이김."""
    files = _contact_files()
    if not files:
        print("내 연락처 파일이 없어요 (data\\my_contacts.csv 또는 구글 드라이브 '나라장터추적_연락처' 폴더).")
        return
    mine = {}
    for f in files:
        for m in _read_csv(f):
            key = m.get("기관", "")
            if key:
                cur = mine.setdefault(key, {})
                cur.update({k: v for k, v in m.items() if v})
    done = 0
    for key, m in mine.items():
        hits = [r for r in rows if key in r["기관"] or key in _norm(r["기관"])]
        if not hits:
            hits = [{"등급": "S", "_score": 0, "기관": key, "기관유형": "", "지역": "", "연락할 곳": "", "전화": "",
                     "이메일": "", "근거": "직접 확보한 연락처", "최근 이사계약": "", "이사계약 횟수": 0,
                     "대본": _script(key, ""), "영업 타이밍": _timing(key, "")}]
            rows.append(hits[0])
        r = hits[0]
        r["이메일"] = m.get("이메일") or r.get("이메일", "")
        if m.get("담당자"):
            r["연락할 곳"] = m["담당자"]
        if m.get("전화"):
            r["전화"] = m["전화"]
        if m.get("메모") and m["메모"] not in (r.get("메모") or ""):
            r["메모"] = " · ".join(x for x in (r.get("메모", ""), m["메모"]) if x)
        r["_score"] += 1000  # 직접 통화해서 메일까지 받은 곳은 맨 위로
        r["등급"] = "★" + r["등급"].lstrip("★")
        done += 1
    print(f"내 연락처 {done}곳 반영 (파일 {len(files)}개: {', '.join(f.name for f in files[:3])}{' …' if len(files) > 3 else ''})")


def _mark_sent(rows):
    """메일을 보낸 곳: 통화결과 'C 메일발송', 다음연락일 = 발송 이틀 뒤 (평일 기준)."""
    from datetime import timedelta
    try:
        sent = json.loads((DATA / "sent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for r in rows:
        info = sent.get((r.get("이메일") or "").lower())
        if not info:
            continue
        d = datetime.strptime(info["발송일"][:10], "%Y-%m-%d")
        nxt, added = d, 0
        while added < 2:
            nxt += timedelta(days=1)
            if nxt.weekday() < 5:
                added += 1
        r["통화결과"] = f"C 메일발송 {d:%m/%d}"
        r["다음연락일"] = f"{nxt:%Y-%m-%d}"


def write():
    from report import _sheet
    rows = build()
    if not rows:
        return None, 0
    day = datetime.now().strftime("%Y-%m-%d")
    path = OUTPUT / f"영업콜리스트_{day}.xlsx"
    wb = Workbook()
    wb.active.title = SHEET
    _sheet(wb.active, rows, COLS)
    wb.save(path)
    db = ROOT / "영업DB.xlsx"
    if db.exists():
        try:
            wb = load_workbook(db)
            keep, keep_by_org = {}, {}
            if SHEET in wb.sheetnames:  # 사장님이 적은 통화결과·다음연락일·메모는 살린다
                ws = wb[SHEET]
                hdr = [c.value for c in ws[1]]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    d = dict(zip(hdr, row))
                    if any(d.get(k) for k in ("통화결과", "다음연락일", "메모", "이메일")):
                        keep[(d.get("기관"), str(d.get("전화")))] = d
                del wb[SHEET]
            keep_by_org = {k[0]: v for k, v in keep.items() if not v.get("전화")}  # 전화 없는 줄만 이름으로 맞춤
            for r in rows:
                old = keep.get((r["기관"], str(r["전화"]))) or keep_by_org.get(r["기관"])
                if old:
                    if old.get("이메일") and not r.get("이메일"):  # 엑셀에 직접 적은 이메일은 지우지 않는다
                        r["이메일"] = old["이메일"]
                    for k in ("통화결과", "다음연락일"):
                        if old.get(k) and not str(r.get(k, "")).startswith("C 메일발송"):
                            r[k] = old.get(k)
                        elif old.get(k) and str(old.get(k)).startswith(("A", "B")):  # 견적요청·명단등록이 더 앞선 단계
                            r[k] = old.get(k)
                    if old.get("메모") and old["메모"] not in (r.get("메모") or ""):
                        r["메모"] = " · ".join(x for x in (r.get("메모", ""), old["메모"]) if x)
            _sheet(wb.create_sheet(SHEET, 0), rows, COLS)
            wb.active = 0
            wb.save(db)
        except PermissionError:
            print("영업DB.xlsx 가 열려 있어서 '콜리스트' 시트는 못 고쳤어요. output 폴더의 영업콜리스트 파일을 보세요.")
    return path, len(rows)
