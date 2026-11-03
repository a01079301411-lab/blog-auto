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


def write_history(recs, day):
    """과거 이사·이전 공고 → 기관별로 묶은 '이사 발주 기관 리스트'."""
    by = defaultdict(list)
    for r in recs:
        by[r["수요기관"] or r["공고기관"]].append(r)
    summary = []
    for org, rows in by.items():
        rows.sort(key=lambda r: r["공고일"], reverse=True)
        latest = rows[0]
        phone = next((r["담당전화"] for r in rows if r["담당전화"]), "")
        officer = next((r["담당자"] for r in rows if r["담당자"]), "")
        summary.append({
            "기관": org, "지역": latest["지역"], "건수": len(rows), "최근공고일": latest["공고일"][:10],
            "최근공고명": latest["제목"], "최근금액": latest["금액"], "합계금액": sum(r["금액"] for r in rows),
            "계약방법": latest["계약방법"], "담당자(최근)": officer, "담당전화(최근)": phone,
            "공고기관": latest["공고기관"], "영업메모": "",
        })
    summary.sort(key=lambda x: (-x["건수"], x["최근공고일"]), reverse=False)
    summary.sort(key=lambda x: (x["지역"] != "대구근교", -x["건수"]))
    wb = Workbook()
    ws = wb.active
    ws.title = "이사발주기관"
    cols = list(summary[0].keys()) if summary else ["기관"]
    _sheet(ws, summary, cols)
    raw_cols = ["지역", "공고일", "제목", "수요기관", "공고기관", "금액", "계약방법", "담당자", "담당전화", "담당메일", "번호", "링크"]
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
