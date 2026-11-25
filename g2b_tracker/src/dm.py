"""우편 DM 주소록 (11_우편DM주소록.bat) · 발송 기록 (12_우편DM발송기록.bat).

대상 3묶음 (봉투에 넣을 PDF 가 다르다)
  학교  : 나이스(NEIS) 대구·경북 전체 학교 행정실        → docs/우편DM/우편DM_학교_*.pdf  (NEIS_KEY 필요)
  기관  : data/dm_institutions.csv (지자체·교육청·대학·공공기관) + data/dm_extra.csv → 우편DM_기관_*.pdf
  병원  : 심평원 병원정보 (병원급 이상, data.go.kr 같은 키)   → 우편DM_병원_*.pdf
제외: 이미 메일을 받은 곳, data/dm_exclude.csv ('우편 사절'), 이미 우편을 보낸 곳 (data/dm_sent.csv)
순서: 대구 → 대구 근교 → 경북. 300곳씩 '학교1', '병원1', '기관1' … 시트
출력: output/우편DM_주소록_날짜.xlsx → 인터넷우체국 e-그린우편 수신자 업로드에 사용
"""
import csv
import json
from datetime import datetime

from openpyxl import Workbook

from config import DATA, OUTPUT
import neis

BATCH = 300
LAST_SUMMARY = ""
NEAR = ("경산", "칠곡", "고령", "성주", "군위", "달성", "왜관", "하양", "진량")
LEVEL = {"고등학교": 0, "특수학교": 1, "중학교": 2, "초등학교": 3,
         "상급종합병원": 0, "종합병원": 1, "병원": 2, "요양병원": 3, "정신병원": 4, "치과병원": 5, "한방병원": 6,
         "지자체": 0, "교육청": 1, "공공기관": 2, "법원검찰": 3, "대학": 4}
PDF = {"학교": "우편DM_학교_간편_1장양면.pdf", "기관": "우편DM_기관_간편_1장양면.pdf", "병원": "우편DM_병원_간편_1장양면.pdf"}
COLS = ["묶음", "받는분", "우편번호", "기본주소", "상세주소", "전화번호", "지역", "구분", "동봉 PDF", "주소확인"]
UPLOAD = ["받는분", "우편번호", "기본주소", "상세주소"]  # e-그린우편 수신자: 성명 · 우편번호 · 주소 순


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


def _region(addr, hint=""):
    if addr.startswith("대구") and "군위" not in addr:
        return "대구근교" if "달성" in addr else "대구"
    return "대구근교" if any(x in addr + hint for x in NEAR) else "경북"


def build(cache_only=False):
    """주소록 행 목록. 주소가 없는 기관은 '주소필요' 묶음으로."""
    emailed = _emailed_names()
    exclude = {_name(r.get("기관")) for r in _read(DATA / "dm_exclude.csv")}
    done = {_name(r.get("받는분", "").replace(" 행정실", "")) for r in _read(DATA / "dm_sent.csv")}

    def skip(name):
        n = _name(name)
        return n in exclude or n in done or any(n.endswith(e) or e.endswith(n) for e in emailed if len(e) >= 4)

    rows = []
    for s in neis.load():
        if not s.get("주소") or skip(s["학교명"]):
            continue
        rows.append({"그룹": "학교", "받는분": f'{s["학교명"]} 행정실', "우편번호": s.get("우편번호", ""),
                     "기본주소": s["주소"], "상세주소": s.get("상세주소", ""), "전화번호": s.get("전화", ""),
                     "지역": "대구" if s["시도"] == "대구" and not any(x in s["주소"] + s["교육지원청"] for x in NEAR)
                     else _region(s["주소"], s["교육지원청"]), "구분": s["학교급"], "주소확인": "나이스"})
    import hospitals
    for h in hospitals.load(cache_only=cache_only):
        if skip(h["병원명"]):
            continue
        rows.append({"그룹": "병원", "받는분": f'{h["병원명"]} 총무과', "우편번호": h["우편번호"], "기본주소": h["주소"],
                     "상세주소": "", "전화번호": h["전화"], "지역": _region(h["주소"], h["시군구"]),
                     "구분": h["종별"], "주소확인": "심평원"})
    for r in _read(DATA / "dm_institutions.csv") + _read(DATA / "dm_extra.csv"):
        if not r.get("받는분") or skip(r["받는분"].replace(" 행정실", "")):
            continue
        has = bool((r.get("기본주소") or "").strip())
        rows.append({"그룹": "기관" if has else "주소필요", "받는분": r["받는분"], "우편번호": r.get("우편번호", ""),
                     "기본주소": r.get("기본주소", ""), "상세주소": r.get("상세주소", ""), "전화번호": r.get("전화번호", ""),
                     "지역": r.get("지역") or (_region(r["기본주소"]) if has else "기타"),
                     "구분": r.get("유형") or "기관", "주소확인": r.get("주소확인") or "직접 입력"})
    order = {"대구": 0, "대구근교": 1, "경북": 2, "기타": 3}
    rows.sort(key=lambda r: (order.get(r["지역"], 3), LEVEL.get(r["구분"], 9), r["받는분"]))
    count = {}
    for r in rows:
        g = r["그룹"]
        count[g] = count.get(g, 0) + 1
        r["묶음"] = g if g == "주소필요" else f"{g}{(count[g] - 1) // BATCH + 1}"
        r["동봉 PDF"] = PDF.get(g, "")
    return rows


def write():
    from report import _sheet
    import hospitals
    rows = build()
    wb = Workbook()
    wb.active.title = "전체"
    _sheet(wb.active, rows, COLS)
    labels = []
    for r in rows:
        if r["묶음"] not in labels:
            labels.append(r["묶음"])
    for b in labels:
        _sheet(wb.create_sheet(b), [r for r in rows if r["묶음"] == b], UPLOAD if b != "주소필요" else COLS)
    path = OUTPUT / f"우편DM_주소록_{datetime.now():%Y-%m-%d}.xlsx"
    wb.save(path)
    by = {}
    for r in rows:
        by[r["그룹"]] = by.get(r["그룹"], 0) + 1
    global LAST_SUMMARY
    LAST_SUMMARY = f"{len(rows)}곳 ({', '.join(f'{k} {v}' for k, v in by.items())})"
    print(f"우편 DM 대상 {len(rows)}곳 ({', '.join(f'{k} {v}' for k, v in by.items())}) → {path}")
    if not by.get("학교"):
        print("· 학교가 0곳: .env 에 NEIS_KEY(나이스 인증키)를 넣으면 대구·경북 학교 행정실이 자동으로 들어갑니다.")
    if not by.get("병원"):
        print("· 병원이 0곳: data.go.kr 에서 '건강보험심사평가원_병원정보서비스' 활용신청(자동승인) 후 다시 실행하세요."
              + (f" (오류: {hospitals.LAST_ERROR})" if hospitals.LAST_ERROR else ""))
    print("시트 이름(학교1, 병원1, 기관1 …)이 한 번에 보낼 묶음입니다. 각 묶음의 '동봉 PDF' 를 e-그린우편 문서로 올리세요.")
    return path


def mark_sent(label):
    """'병원1' 처럼 묶음을 보냈으면 기록 → 다음 주소록에서 빠지고, 콜리스트에 'DM 발송' 표시. 숫자만 주면 학교 묶음."""
    label = str(label).strip().replace("차", "").replace("_", "")
    if label.isdigit():
        label = f"학교{label}"
    rows = [r for r in build() if r["묶음"] == label]
    if not rows:
        print(f"'{label}' 묶음이 없어요. 주소록 시트 이름(예: 학교1, 병원1, 기관1)을 그대로 넣어 주세요.")
        return
    path = DATA / "dm_sent.csv"
    new = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["발송일", "차수", "받는분", "전화번호"])
        day = datetime.now().strftime("%Y-%m-%d")
        for r in rows:
            w.writerow([day, label, r["받는분"], r["전화번호"]])
    print(f"{label} {len(rows)}곳을 '우편 발송'으로 기록했어요. 다음 주소록부터 빠집니다.")


def upload_file(label):
    """e-그린우편에 바로 올릴 엑셀 하나 (그 묶음만, 받는분·우편번호·주소·상세주소). 반환 (경로, 동봉 PDF 이름, 곳 수)."""
    from report import _sheet
    label = str(label).strip()
    rows = [r for r in build(cache_only=True) if r["묶음"] == label]
    if not rows:
        return None, "", 0
    wb = Workbook()
    wb.active.title = label
    _sheet(wb.active, rows, UPLOAD)
    path = OUTPUT / f"e그린우편_올릴파일_{label}.xlsx"
    wb.save(path)
    return path, rows[0]["동봉 PDF"], len(rows)


def next_label():
    """아직 안 보낸 묶음 중 먼저 보낼 것: 기관 → 병원 → 학교."""
    labels = []
    for r in build(cache_only=True):
        if r["묶음"] != "주소필요" and r["묶음"] not in labels:
            labels.append(r["묶음"])
    for g in ("기관", "병원", "학교"):
        for lb in labels:
            if lb.startswith(g):
                return lb
    return ""
