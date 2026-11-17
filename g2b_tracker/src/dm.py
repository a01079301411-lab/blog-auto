"""우편 DM 주소록 (11_우편DM주소록.bat) · 발송 기록 (12_우편DM발송기록.bat).

대상: 나이스(NEIS) 대구·경북 전체 학교 행정실 + data/dm_extra.csv (직접 추가한 기관 주소)
제외: 이미 메일을 받은 곳, data/dm_exclude.csv ('우편 사절'), 이미 우편을 보낸 곳 (data/dm_sent.csv)
순서: 대구 → 대구 근교(경산·칠곡·고령·성주·군위·달성) → 경북 나머지, 같은 지역은 고등 → 특수 → 중 → 초
출력: output/우편DM_주소록_날짜.xlsx  (300곳씩 '차수' 시트 + 전체)  → 인터넷우체국 e-그린우편 수신자 업로드에 사용
"""
import csv
import json
from datetime import datetime

from openpyxl import Workbook

from config import DATA, OUTPUT
import neis

BATCH = 300
NEAR = ("경산", "칠곡", "고령", "성주", "군위", "달성", "왜관", "하양", "진량")
LEVEL = {"고등학교": 0, "특수학교": 1, "중학교": 2, "초등학교": 3}
COLS = ["차수", "받는분", "우편번호", "기본주소", "상세주소", "전화번호", "지역", "학교급", "설립", "교육지원청"]


def _read(path):
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(path.read_text(encoding=enc).splitlines()))
        except UnicodeDecodeError:
            continue
    return []


def _name(n):
    return "".join((n or "").split())


def _emailed_names():
    """메일을 이미 받은 기관 이름 (드라이브 연락처 + 보낸 기록)."""
    import calllist
    try:
        sent = json.loads((DATA / "sent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = {}
    names = set()
    _, groups, _, _ = calllist._mine()
    for key, g in groups.items():
        if any(m in sent and sent[m].get("발송일") for m in g["이메일"]):
            names.add(_name(key))
    return names


def build():
    schools = neis.load()
    if not schools:
        print("학교 목록이 없어요. .env 에 NEIS_KEY(나이스 인증키)를 넣고 다시 실행해 주세요. (0_처음설치.bat 마지막 질문)")
        return None
    emailed = _emailed_names()
    exclude = {_name(r.get("기관")) for r in _read(DATA / "dm_exclude.csv")}
    done = {_name(r.get("받는분", "").replace(" 행정실", "")) for r in _read(DATA / "dm_sent.csv")}
    rows = []
    for s in schools:
        n = _name(s["학교명"])
        if not s.get("주소") or any(n.endswith(e) or e.endswith(n) for e in emailed if len(e) >= 4):
            continue
        if n in exclude or n in done:
            continue
        region = "대구" if s["시도"] == "대구" else ("대구근교" if any(x in (s["주소"] + s["교육지원청"]) for x in NEAR) else "경북")
        rows.append({"받는분": f'{s["학교명"]} 행정실', "우편번호": s.get("우편번호", ""), "기본주소": s["주소"],
                     "상세주소": s.get("상세주소", ""), "전화번호": s.get("전화", ""), "지역": region,
                     "학교급": s["학교급"], "설립": s.get("설립", ""), "교육지원청": s["교육지원청"]})
    for r in _read(DATA / "dm_extra.csv"):  # 학교가 아닌 기관 직접 추가 (열: 받는분, 우편번호, 기본주소, 상세주소, 전화번호)
        if r.get("받는분") and r.get("기본주소") and _name(r["받는분"].replace(" 행정실", "")) not in done:
            rows.append({**{c: r.get(c, "") for c in COLS}, "지역": r.get("지역") or "기타", "학교급": "기관"})
    order = {"대구": 0, "대구근교": 1, "경북": 2, "기타": 3}
    rows.sort(key=lambda r: (order.get(r["지역"], 3), LEVEL.get(r["학교급"], 4), r["받는분"]))
    for i, r in enumerate(rows):
        r["차수"] = f"{i // BATCH + 1}차"
    return rows


def write():
    from report import _sheet
    rows = build()
    if rows is None:
        return None
    wb = Workbook()
    wb.active.title = "전체"
    _sheet(wb.active, rows, COLS)
    for b in sorted({r["차수"] for r in rows}, key=lambda x: int(x[:-1])):
        _sheet(wb.create_sheet(b), [r for r in rows if r["차수"] == b], COLS[1:6])
    path = OUTPUT / f"우편DM_주소록_{datetime.now():%Y-%m-%d}.xlsx"
    wb.save(path)
    by = {}
    for r in rows:
        by[r["지역"]] = by.get(r["지역"], 0) + 1
    print(f"우편 DM 대상 {len(rows)}곳 ({', '.join(f'{k} {v}' for k, v in by.items())}) → {path}")
    print("인터넷우체국 e-그린우편 → 수신자 엑셀 올리기에 '1차' 시트(300곳)부터 쓰세요.")
    return path


def mark_sent(batch):
    """'1차' 를 보냈으면 기록 → 다음 주소록에서 빠지고, 콜리스트에 'DM 발송' 표시."""
    rows = [r for r in (build() or []) if r["차수"] == f"{batch}차"]
    if not rows:
        print(f"{batch}차 대상이 없어요.")
        return
    path = DATA / "dm_sent.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["발송일", "차수", "받는분", "전화번호"])
        day = datetime.now().strftime("%Y-%m-%d")
        for r in rows:
            w.writerow([day, f"{batch}차", r["받는분"], r["전화번호"]])
    print(f"{batch}차 {len(rows)}곳을 '우편 발송'으로 기록했어요. 다음 주소록부터 빠집니다.")
