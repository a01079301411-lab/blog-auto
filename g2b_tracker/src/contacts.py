"""우리 회사를 영업할 '관공서 담당자' 연락처를 기관별로 계속 쌓는다 (data/contacts.json).

모으는 곳 (모두 나라장터에 공개된 업무 연락처)
- 계약정보: 이사·이전·운반·보관 계약을 실제로 처리한 기관 계약 담당자 (수의계약 포함) ← 가장 중요
- 입찰공고·사전규격·발주계획: 우리 일감 공고의 기관 담당자
원도급사·경쟁 이사업체는 넣지 않는다 (원도급사는 매일 엑셀 '원도급사' 시트에만).
영업DB.xlsx 의 '관공서담당자' 시트만 매번 새로 쓴다. 다른 시트는 건드리지 않는다.
"""
import json
import logging

from openpyxl import Workbook, load_workbook

from config import DATA, OUTPUT, ROOT
import rules as R

log = logging.getLogger(__name__)
STORE = DATA / "contacts.json"
SHEET = "관공서담당자"
COLS = ["우선", "기관", "기관유형", "지역", "담당부서", "담당자", "전화", "이메일",
        "이사계약 이력", "이사계약 금액(최근)", "최근 건", "최근일", "출처", "메모"]


def _load():
    try:
        db = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # 예전 버전이 모은 업체 연락처는 버린다
    return {k: v for k, v in db.items() if v.get("구분", "기관") in ("기관", "발주기관 담당")}


def update(recs, move_contract=False):
    """recs: rules.normalize 결과. move_contract=True 면 '이사 계약을 실제로 한 기관' 기록."""
    db = _load()
    added = 0
    for r in recs:
        tel, mail = r.get("담당전화", ""), r.get("담당메일", "")
        if not (tel or mail):
            continue
        if r.get("출처", "").startswith("낙찰"):
            continue  # 낙찰 쪽 연락처는 업체 것일 수 있어 제외
        org = r.get("수요기관") or r.get("공고기관")
        key = f"{org}|{tel or mail}"
        cur = db.get(key)
        if not cur:
            added += 1
            cur = db[key] = {"구분": "기관", "기관": org, "기관유형": R.org_type(org), "지역": r.get("지역", ""),
                             "담당부서": "", "담당자": "", "전화": tel, "이메일": mail, "이사계약 이력": 0,
                             "이사계약 금액(최근)": "", "최근 건": "", "최근일": "", "출처": "", "메모": "", "_keys": []}
        if r["_key"] in cur.setdefault("_keys", []):
            continue
        cur["_keys"].append(r["_key"])
        cur["담당부서"] = r.get("담당부서") or cur["담당부서"]
        cur["담당자"] = r.get("담당자") or cur["담당자"]
        cur["이메일"] = mail or cur["이메일"]
        day = (r.get("공고일") or "")[:10]
        if move_contract:
            cur["이사계약 이력"] += 1
            amt = r.get("낙찰금액") or r.get("금액") or 0
            if amt and day >= (cur.get("_amt_day") or ""):
                cur["이사계약 금액(최근)"], cur["_amt_day"] = f"{round(amt / 10000):,}만원", day
        if day >= cur["최근일"]:
            cur["최근일"], cur["최근 건"] = day, (r.get("제목") or "")[:80]
        src = "계약" if move_contract or r.get("출처") == "계약" else r.get("출처", "")
        if src and src not in cur["출처"]:
            cur["출처"] = ",".join(x for x in (cur["출처"], src) if x)
    STORE.write_text(json.dumps(db, ensure_ascii=False, indent=0), encoding="utf-8")
    write_sheet(db)
    return added, len(db)


def _priority(x):
    if x["이사계약 이력"] and x["지역"] == "대구근교":
        return "A"
    if x["이사계약 이력"] or x["지역"] == "대구근교":
        return "B"
    return "C"


def write_sheet(db=None):
    from report import _sheet
    db = db if db is not None else _load()
    rows = []
    for v in db.values():
        row = {k: v.get(k, "") for k in COLS}
        row["우선"] = _priority(v)
        rows.append(row)
    rows.sort(key=lambda x: (x["우선"], -int(x["이사계약 이력"] or 0), x["기관"]))
    wb = Workbook()
    wb.active.title = SHEET
    _sheet(wb.active, rows, COLS)
    wb.save(OUTPUT / "관공서담당자.xlsx")
    path = ROOT / "영업DB.xlsx"
    if not path.exists():
        return
    try:
        wb = load_workbook(path)
        for old in (SHEET, "자동연락처"):
            if old in wb.sheetnames:
                del wb[old]
        _sheet(wb.create_sheet(SHEET, 1), rows, COLS)
        wb.save(path)
    except PermissionError:
        print("영업DB.xlsx 가 엑셀에 열려 있어서 '관공서담당자' 시트는 못 고쳤어요. output\\관공서담당자.xlsx 를 보세요.")
