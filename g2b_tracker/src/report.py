"""엑셀·브리핑 파일 만들기."""
import csv
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import DATA, OUTPUT, ROOT

COLS = ["신규", "등급", "점수", "출처", "구분", "지역", "제목", "수요기관", "공고기관", "공고일", "마감일", "금액",
        "계약방법", "담당자", "담당전화", "담당메일", "낙찰업체", "낙찰업체전화", "낙찰업체대표", "이유", "다음행동", "번호", "링크"]
WIDTH = {"제목": 48, "수요기관": 24, "공고기관": 20, "이유": 40, "다음행동": 60, "링크": 30, "낙찰업체": 18}
FILL = {"즉시": PatternFill("solid", fgColor="FFD6D6"), "추적": PatternFill("solid", fgColor="FFF3C4"),
        "마감": PatternFill("solid", fgColor="E6E6E6")}


def _sheet(ws, rows, cols):
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F4F6F")
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
        fill = FILL.get(r.get("등급"))
        if fill:
            for c in ws[ws.max_row]:
                c.fill = fill
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTH.get(c, 12)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def write_daily(recs, errors, day):
    wb = Workbook()
    ws = wb.active
    ws.title = "오늘의영업"
    main = [r for r in recs if r["출처"] == "입찰공고" and r["등급"] != "마감"]
    _sheet(ws, main, COLS)
    _sheet(wb.create_sheet("원도급사(낙찰)"), [r for r in recs if r["출처"].startswith("낙찰")], COLS)
    _sheet(wb.create_sheet("사전규격·발주계획"), [r for r in recs if r["출처"] in ("사전규격", "발주계획")], COLS)
    _sheet(wb.create_sheet("마감(원도급사로)"), [r for r in recs if r["등급"] == "마감"], COLS)
    _sheet(wb.create_sheet("전체"), recs, COLS)
    if errors:
        e = wb.create_sheet("오류")
        e.append(["실패한 조회 (1_연결점검.bat 으로 확인)"])
        for x in errors:
            e.append([x])
    path = OUTPUT / f"나라장터_{day}.xlsx"
    wb.save(path)
    return path


def write_brief(recs, errors, day, new_keys):
    hot = [r for r in recs if r["등급"] == "즉시"]
    # (마감 공고는 즉시·추적에 넣지 않음)
    track = [r for r in recs if r["등급"] == "추적"]
    lines = [f"# 나라장터 영업 브리핑 {day}", "",
             f"- 즉시 연락 **{len(hot)}건** · 추적 **{len(track)}건** · 오늘 새로 뜬 것 **{len(new_keys)}건**", ""]

    def block(title, rows):
        if not rows:
            return
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| 점수 | 출처 | 제목 | 기관 | 마감 | 담당 | 다음 행동 |")
        lines.append("|---:|---|---|---|---|---|---|")
        for r in rows[:30]:
            new = "🆕 " if r["_key"] in new_keys else ""
            who = " ".join(x for x in (r["담당자"], r["담당전화"]) if x) or (r["낙찰업체"] + " " + r["낙찰업체전화"]).strip()
            lines.append(f"| {r['점수']} | {r['출처']} | {new}{r['제목']} | {r['수요기관'] or r['공고기관']} | "
                         f"{r['마감일'] or '-'} | {who or '-'} | {r['다음행동']} |")
        lines.append("")

    block("즉시 연락 (60점 이상)", hot)
    block("추적 (40~59점)", track)
    closed = [r for r in recs if r["등급"] == "마감"]
    if closed:
        lines += [f"## 마감된 공고 {len(closed)}건", "", "엑셀 '마감(원도급사로)' 시트. 낙찰되면 '원도급사' 시트와 알림으로 다시 뜹니다.", ""]
    if errors:
        lines += ["## 조회 실패", "", *[f"- {e}" for e in errors], "",
                  "→ 1_연결점검.bat 을 실행해서 어느 서비스 활용신청이 빠졌는지 확인하세요.", ""]
    path = OUTPUT / f"브리핑_{day}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _won(v):
    return f"{round(v / 10000):,}만원" if v else "-"


def _stats(vals):
    vals = sorted(v for v in vals if v > 0)
    if not vals:
        return {"건수": 0, "평균": "-", "중앙값": "-", "최소": "-", "최대": "-"}
    mid = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) // 2
    return {"건수": len(vals), "평균": _won(sum(vals) // len(vals)), "중앙값": _won(mid), "최소": _won(vals[0]), "최대": _won(vals[-1])}


BANDS = [(0, 5_000_000, "500만원 이하"), (5_000_000, 20_000_000, "500만~2천만원"), (20_000_000, 50_000_000, "2천만~5천만원"),
         (50_000_000, 100_000_000, "5천만~1억원"), (100_000_000, 10**13, "1억원 초과")]


def write_history(recs, day):
    """과거 이사·이전 공고 → 기관별 리스트 + 금액대 분석 + 경쟁사(낙찰업체)."""
    from rules import org_type
    for r in recs:
        r["기관유형"] = org_type(r["수요기관"] or r["공고기관"])
        r["계약금액(기준)"] = r.get("낙찰금액") or r["금액"]
        r["금액기준"] = "낙찰금액" if r.get("낙찰금액") else ("추정가격" if r["금액"] else "")
    by = defaultdict(list)
    for r in recs:
        by[r["수요기관"] or r["공고기관"]].append(r)
    summary = []
    for org, rows in by.items():
        rows.sort(key=lambda r: r["공고일"], reverse=True)
        latest = rows[0]
        phone = next((r["담당전화"] for r in rows if r["담당전화"]), "")
        officer = next((r["담당자"] for r in rows if r["담당자"]), "")
        amts = [r["계약금액(기준)"] for r in rows if r["계약금액(기준)"]]
        winners = [r["낙찰업체"] for r in rows if r.get("낙찰업체")]
        summary.append({
            "기관": org, "기관유형": latest["기관유형"], "지역": latest["지역"], "건수": len(rows),
            "최근공고일": latest["공고일"][:10], "최근공고명": latest["제목"],
            "평균금액": _won(sum(amts) // len(amts)) if amts else "-", "최근금액": _won(latest["계약금액(기준)"]),
            "최근낙찰업체": winners[0] if winners else "", "계약방법": latest["계약방법"],
            "담당자(최근)": officer, "담당전화(최근)": phone, "공고기관": latest["공고기관"], "영업메모": "",
        })
    summary.sort(key=lambda x: (x["지역"] != "대구근교", -x["건수"]))
    wb = Workbook()
    ws = wb.active
    ws.title = "이사발주기관"
    _sheet(ws, summary, list(summary[0].keys()) if summary else ["기관"])

    # 금액대 분석
    vals = [r["계약금액(기준)"] for r in recs]
    real = [r["낙찰금액"] for r in recs if r.get("낙찰금액")]
    rows = [{"구분": "전체 (낙찰금액 우선, 없으면 추정가격)", **_stats(vals)},
            {"구분": "실제 낙찰금액만", **_stats(real)}]
    for t in sorted({r["기관유형"] for r in recs}):
        rows.append({"구분": f"기관유형: {t}", **_stats([r["계약금액(기준)"] for r in recs if r["기관유형"] == t])})
    for reg in ("대구근교", "경북", "대구경북(주소)"):
        sub = [r["계약금액(기준)"] for r in recs if r["지역"] == reg]
        if sub:
            rows.append({"구분": f"지역: {reg}", **_stats(sub)})
    rates = [float(r["낙찰률"]) for r in recs if str(r.get("낙찰률") or "").replace(".", "", 1).isdigit()]
    cnts = [int(r["참가업체수"]) for r in recs if str(r.get("참가업체수") or "").isdigit()]
    rows.append({"구분": "평균 낙찰률(%) / 평균 참가업체 수",
                 "건수": len(rates), "평균": f"{sum(rates) / len(rates):.1f}%" if rates else "-",
                 "중앙값": f"{sum(cnts) / len(cnts):.1f}곳" if cnts else "-", "최소": "", "최대": ""})
    band = wb.create_sheet("금액대")
    _sheet(band, rows, ["구분", "건수", "평균", "중앙값", "최소", "최대"])
    band.append([])
    band.append(["금액 구간", "건수", "비율", "의미"])
    meaning = {"500만원 이하": "소규모 부서 이동", "500만~2천만원": "일반 수의계약 범위",
               "2천만~5천만원": "여성·장애인기업 수의 범위로 알려진 구간 [업데이트 필요]",
               "5천만~1억원": "견적·입찰", "1억원 초과": "입찰"}
    n = len([v for v in vals if v]) or 1
    for lo, hi, name in BANDS:
        c = sum(1 for v in vals if v and lo < v <= hi)
        band.append([name, c, f"{c * 100 // n}%", meaning[name]])

    # 경쟁사 (이사 용역 낙찰업체)
    comp = defaultdict(lambda: {"건수": 0, "합계": 0, "기관": set(), "전화": ""})
    for r in recs:
        if r.get("낙찰업체"):
            c = comp[r["낙찰업체"]]
            c["건수"] += 1
            c["합계"] += r.get("낙찰금액") or 0
            c["기관"].add(r["수요기관"] or r["공고기관"])
            c["전화"] = c["전화"] or r.get("낙찰업체전화", "")
    crow = [{"업체": k, "낙찰건수": v["건수"], "낙찰합계": _won(v["합계"]), "평균": _won(v["합계"] // v["건수"]) if v["합계"] else "-",
             "주요기관": ", ".join(sorted(v["기관"]))[:120], "전화": v["전화"]}
            for k, v in sorted(comp.items(), key=lambda kv: -kv[1]["건수"])]
    _sheet(wb.create_sheet("경쟁사(낙찰업체)"), crow, ["업체", "낙찰건수", "낙찰합계", "평균", "주요기관", "전화"])

    raw_cols = ["지역", "기관유형", "공고일", "제목", "수요기관", "공고기관", "금액", "낙찰금액", "금액기준", "낙찰률", "참가업체수",
                "낙찰업체", "계약방법", "담당자", "담당전화", "담당메일", "번호", "링크"]
    _sheet(wb.create_sheet("공고원본"), sorted(recs, key=lambda r: r["공고일"], reverse=True), raw_cols)
    path = OUTPUT / f"이사발주기관_{day}.xlsx"
    wb.save(path)
    return path, summary


def ensure_sales_db():
    """영업DB.xlsx 가 없으면 data/targets.csv 로 처음 한 번 만든다. 있으면 절대 건드리지 않는다."""
    path = ROOT / "영업DB.xlsx"
    if path.exists():
        return None
    src = DATA / "targets.csv"
    rows = list(csv.DictReader(src.open(encoding="utf-8-sig"))) if src.exists() else []
    extra = ["담당부서", "담당자", "직통전화", "이메일", "확인출처", "확인일", "경로유형", "상태",
             "최초접촉일", "최근접촉일", "다음연락일", "통화내용", "다음행동"]
    cols = (list(rows[0].keys()) if rows else ["기관"]) + [c for c in extra if not rows or c not in rows[0]]
    wb = Workbook()
    ws = wb.active
    ws.title = "기관리스트"
    _sheet(ws, rows, cols)
    log = wb.create_sheet("접촉이력")
    _sheet(log, [], ["날짜", "기관", "담당자", "방법(전화/메일/방문/공문)", "내용", "결과", "다음연락일", "다음행동"])
    kpi = wb.create_sheet("주간KPI")
    _sheet(kpi, [], ["주(월요일)", "신호 검토(목표15)", "고적합(3~5)", "담당자 연결(5)", "소개서 발송(3)", "실사(1)", "견적", "수주", "수주금액", "메모"])
    wb.save(path)
    return path
