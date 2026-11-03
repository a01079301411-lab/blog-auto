"""공고에 공개된 담당자 연락처를 기관별로 계속 쌓는다 (data/contacts.json).
영업DB.xlsx 의 '자동연락처' 시트만 매번 새로 쓴다. 다른 시트(기관리스트·접촉이력·KPI)는 건드리지 않는다."""
import json
import logging

from openpyxl import Workbook, load_workbook

from config import DATA, OUTPUT, ROOT
import rules as R

log = logging.getLogger(__name__)
STORE = DATA / "contacts.json"
COLS = ["구분", "기관유형", "기관", "지역", "담당자", "전화", "이메일", "대표자", "최근공고", "최근일", "건수", "메모"]


def _load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update(recs):
    """recs: rules.normalize 결과들. 발주기관 담당자 + 낙찰업체(원도급사·경쟁사) 연락처."""
    db = _load()
    added = 0
    for r in recs:
        org = r.get("수요기관") or r.get("공고기관")
        day = (r.get("공고일") or "")[:10]
        rows = []
        if r.get("담당전화") or r.get("담당메일"):
            rows.append(("발주기관 담당", org, r.get("담당자", ""), r.get("담당전화", ""), r.get("담당메일", ""), ""))
        if r.get("낙찰업체"):
            kind = "원도급사(낙찰)" if r.get("구분") == "공사" else "이사 낙찰업체(경쟁사)"
            rows.append((kind, r["낙찰업체"], "", r.get("낙찰업체전화", ""), "", r.get("낙찰업체대표", "")))
        for kind, name, person, tel, mail, ceo in rows:
            key = f"{kind}|{name}|{tel or mail}"
            cur = db.get(key)
            if not cur:
                added += 1
                cur = db[key] = {"구분": kind, "기관유형": R.org_type(org) if kind == "발주기관 담당" else "업체",
                                 "기관": name, "지역": r.get("지역", ""), "담당자": person, "전화": tel, "이메일": mail,
                                 "대표자": ceo, "최근공고": "", "최근일": "", "건수": 0, "메모": ""}
            cur["건수"] += 1
            if day >= cur["최근일"]:
                cur["최근일"], cur["최근공고"] = day, (r.get("제목") or "")[:80]
                cur["담당자"] = person or cur["담당자"]
    STORE.write_text(json.dumps(db, ensure_ascii=False, indent=0), encoding="utf-8")
    write_sheet(db)
    return added, len(db)


def write_sheet(db=None):
    from report import _sheet
    db = db if db is not None else _load()
    order = {"발주기관 담당": 0, "원도급사(낙찰)": 1, "이사 낙찰업체(경쟁사)": 2}
    rows = sorted(db.values(), key=lambda x: (order.get(x["구분"], 9), x["지역"] != "대구근교", x["기관"], x["최근일"]))
    # 1) 항상 output 에 따로 저장
    wb = Workbook()
    _sheet(wb.active, rows, COLS)
    wb.active.title = "자동연락처"
    wb.save(OUTPUT / "연락처모음.xlsx")
    # 2) 영업DB.xlsx 의 '자동연락처' 시트만 교체
    path = ROOT / "영업DB.xlsx"
    if not path.exists():
        return
    try:
        wb = load_workbook(path)
        if "자동연락처" in wb.sheetnames:
            del wb["자동연락처"]
        _sheet(wb.create_sheet("자동연락처", 1), rows, COLS)
        wb.save(path)
    except PermissionError:
        print("영업DB.xlsx 가 엑셀에 열려 있어서 '자동연락처' 시트는 못 고쳤어요. output\\연락처모음.xlsx 를 보세요.")
