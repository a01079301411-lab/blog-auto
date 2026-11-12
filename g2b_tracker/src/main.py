"""나라장터 추적 실행.

  python src/main.py              매일 추적 (입찰공고·사전규격·낙찰·발주계획) → 엑셀·브리핑·텔레그램
  python src/main.py --check      키·활용신청 점검
  python src/main.py --history 36 지난 36개월 이사·이전 공고를 낸 기관 리스트 만들기
  python src/main.py --selftest   인터넷 없이 점수 규칙만 시험
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import contacts  # noqa: E402
import calllist  # noqa: E402
import g2b  # noqa: E402
import notifier  # noqa: E402
import report  # noqa: E402
import rules as R  # noqa: E402

SEEN = config.DATA / "seen.json"


QUIET = False


def setup_log(quiet):
    handlers = [logging.FileHandler(config.LOGS / "tracker.log", encoding="utf-8")]
    if not quiet:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=handlers)


def load_seen():
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def run_daily():
    rules = R.load_rules()
    seen = load_seen()
    first_run = not seen
    days = 30 if first_run else config.LOOKBACK_DAYS
    print(f"나라장터 최근 {days}일치를 훑는 중... (처음엔 몇 분 걸려요)")
    items, errors = g2b.collect_daily(days)
    recs = R.evaluate(items, rules)
    moves = []
    try:
        from datetime import datetime, timedelta
        citems, cerr = g2b.collect_contracts(datetime.now() - timedelta(days=days), datetime.now())
        errors += cerr
        for it in citems:
            c = R.normalize(it)
            c["지역"] = c["_region"] = R.region_of(c, rules)
            if c["_region"] and R.is_history_hit(c, rules) and c["_key"] not in {m["_key"] for m in moves}:
                c["출처"] = "계약"
                moves.append(c)
    except g2b.ApiError as e:
        errors.append(f"계약정보: {e}")
    new_keys = {r["_key"] for r in recs if not (set(r.get("_dupkeys", [])) & seen)} - seen
    for r in recs:
        r["신규"] = "NEW" if r["_key"] in new_keys else ""
    day = R.today()
    xlsx = report.write_daily(recs, errors, day, moves)
    md = report.write_brief(recs, errors, day, new_keys)
    page = report.write_html(recs, errors, day, new_keys, moves)
    db = report.ensure_sales_db()
    added, total = contacts.update([r for r in recs if r["등급"] != "마감"])
    a2, total = contacts.update(moves, move_contract=True)
    added += a2
    try:
        import mailer
        if os.getenv("NAVER_APP_PW"):
            mailer.run()
    except Exception as e:  # 메일이 실패해도 추적은 계속
        logging.warning("메일 발송 건너뜀: %s", e)
    cpath, cn = calllist.write()
    all_keys = {r["_key"] for r in recs} | {k for r in recs for k in r.get("_dupkeys", [])}
    SEEN.write_text(json.dumps(sorted(seen | all_keys), ensure_ascii=False), encoding="utf-8")

    hot = [r for r in recs if r["_key"] in new_keys and r["등급"] != "마감" and r["점수"] >= config.ALERT_MIN_SCORE]
    closed = sum(1 for r in recs if r["등급"] == "마감")
    msg = [f"[나라장터 {day}] 받은 공고 {len(items)}건 → 우리 일감 {len(recs)}건 (새로 뜬 것 {len(new_keys)}건, 마감 {closed}건은 원도급사 추적으로)"]
    for r in hot[:12]:
        who = r["담당전화"] or r["낙찰업체전화"] or ""
        msg.append(f"\n■ {r['등급']} {r['점수']}점 [{r['출처']}] {r['제목']}\n  {r['수요기관'] or r['공고기관']}"
                   f"{' · 마감 ' + r['마감일'] if r['마감일'] else ''}{' · ☎ ' + who if who else ''}\n  → {r['다음행동']}"
                   + (f"\n  🔗 {r['링크']}" if r.get("링크") else ""))
    new_moves = [m for m in moves if m["_key"] not in seen]
    if new_moves:
        msg.append(f"\n📋 이사·이전 계약 체결 {len(new_moves)}건 (다른 업체가 따감 → 다음엔 우리 차례):")
        for m in new_moves[:5]:
            amt = f"{round((m['낙찰금액'] or m['금액']) / 10000):,}만원" if (m['낙찰금액'] or m['금액']) else ""
            msg.append(f"  · {m['수요기관'] or m['공고기관']} {m['제목'][:30]} {amt} {m['계약방법']}"
                       f"{' ☎ ' + m['담당부서'] + ' ' + m['담당전화'] if m['담당전화'] else ''}"
                       + (f" 🔗 {m['링크']}" if m.get("링크") else ""))
    seen |= {m["_key"] for m in moves}
    if errors:
        msg.append(f"\n⚠ 조회 실패 {len(errors)}건 → 1_연결점검.bat 실행")
    if first_run:
        msg.append("\n(첫 실행이라 최근 30일치 전체를 '새로 뜬 것'으로 셌어요. 내일부터는 진짜 새 공고만 와요.)")
    SEEN.write_text(json.dumps(sorted(seen | all_keys), ensure_ascii=False), encoding="utf-8")
    notifier.notify("\n".join(msg))
    print("\n".join(msg))
    if not QUIET:  # 직접 실행하면 브라우저로 바로 열기
        import webbrowser
        webbrowser.open(page.resolve().as_uri())
    print(f"\n저장: {xlsx}\n      {page}  ← 브라우저로 열림, 제목 누르면 나라장터\n      {md}" + (f"\n      {db} (영업DB 새로 만듦)" if db else ""))
    print(f"      관공서 담당자 새로 {added}명 (누적 {total}명) → 영업DB '관공서담당자' 시트")


def run_history(months):
    rules = R.load_rules()
    kws = ["이사", "이전", "이삿짐", "운반", "보관", "재배치", "문서고", "이송"]
    print(f"지난 {months}개월 동안 '{', '.join(kws)}' 공고와 낙찰 결과를 찾는 중... (20~40분 걸릴 수 있어요)")
    items, errors = g2b.collect_history(months, kws)
    awards, err2 = g2b.collect_awards(months, kws)
    errors += err2
    from datetime import datetime, timedelta
    try:
        cons, err3 = g2b.collect_contracts(datetime.now() - timedelta(days=30 * months), datetime.now(), kws)
    except g2b.ApiError as e:
        cons, err3 = [], [f"계약정보: {e}"]
    errors += err3
    recs = {}
    for it in items:
        rec = R.normalize(it)
        rec["지역"] = rec["_region"] = R.region_of(rec, rules)
        if rec["_region"] and R.is_history_hit(rec, rules):
            recs[rec["_key"]] = rec
    by_no = {}
    for r in recs.values():
        by_no.setdefault(r["공고번호"], []).append(r)
    matched = set()
    for it in awards:
        a = R.normalize(it)
        a["지역"] = a["_region"] = R.region_of(a, rules)
        targets = by_no.get(a["공고번호"])
        if targets:
            for r in targets:
                for k in ("낙찰금액", "낙찰률", "참가업체수", "낙찰업체", "낙찰업체전화", "낙찰업체대표"):
                    r[k] = a[k] or r.get(k, "")
            matched.add(a["공고번호"])
        elif a["_region"] and R.is_history_hit(a, rules):
            a["출처"] = "낙찰(공고 못 찾음)"
            recs[a["_key"]] = a
    ncon = 0
    for it in cons:
        c = R.normalize(it)
        c["지역"] = c["_region"] = R.region_of(c, rules)
        if c["_region"] and R.is_history_hit(c, rules):
            c["출처"] = "계약"
            recs[c["_key"]] = c
            ncon += 1
    path, summary = report.write_history(list(recs.values()), R.today())
    added, total = contacts.update([r for r in recs.values() if r["출처"] != "계약"])
    a2, total = contacts.update([r for r in recs.values() if r["출처"] == "계약"], move_contract=True)
    added += a2
    cpath, cn = calllist.write()
    print(f"영업 콜리스트 {cn}곳 (우선순위 순) → 영업DB 맨 앞 '콜리스트' 시트, {cpath}")
    print(f"\n이사·이전 공고 {len(recs)}건 (낙찰금액 붙은 것 {len(matched)}건), 기관 {len(summary)}곳 → {path}")
    print(f"관공서 담당자 새로 {added}명 (누적 {total}명) → 영업DB '관공서담당자' 시트")
    for s in summary[:15]:
        print(f"  {s['건수']:>2}건  {s['기관']}  (최근 {s['최근공고일']} {s['최근공고명'][:30]})")
    if errors:
        print(f"\n조회 실패 {len(errors)}건 (하루 호출 한도일 수 있어요. 내일 다시 실행하면 됩니다):")
        for e in errors[:5]:
            print("  -", e)
    notifier.notify(f"[이사 발주 기관 리스트] {len(summary)}곳 · 공고 {len(recs)}건 · 금액대 분석 포함. 파일: {path.name}")


def run_check():
    print("공공데이터포털 서비스별 연결 점검\n")
    ok_all = True
    for name, ok, msg, fields in g2b.check():
        ok_all &= ok
        print(f"  {'O' if ok else 'X'}  {name:<22} {msg}")
        if fields:
            logging.getLogger(__name__).info("%s 필드: %s", name, ", ".join(fields))
    print()
    if ok_all:
        print("모두 정상입니다. 2_지금추적.bat 을 실행하세요.")
    else:
        print("X 표시된 서비스는 data.go.kr 에서 '활용신청'을 해 주세요. (README 2단계)\n"
              "신청 직후 1~2시간은 'SERVICE_KEY_IS_NOT_REGISTERED' 가 뜰 수 있어요. 잠시 후 다시 점검하세요.")


def run_selftest():
    rules = R.load_rules()
    sample = [
        {"_src": "bid", "_kind": "용역", "bidNtceNm": "2026년 북구청 청사 이전 이사용역", "dminsttNm": "대구광역시 북구",
         "ntceInsttNm": "대구광역시 북구", "bidNtceNo": "R26BK0001", "bidNtceOrd": "000", "presmptPrce": "45000000",
         "cntrctCnclsMthdNm": "수의계약(소액) 여성기업", "ntceInsttOfclNm": "홍길동", "ntceInsttOfclTelNo": "053-000-0000"},
        {"_src": "award", "_kind": "공사", "bidNtceNm": "중대범죄수사청 대구청 사무환경 조성 건축공사",
         "dminsttNm": "중대범죄수사청", "ntceInsttNm": "조달청 대구지방조달청", "bidwinnrNm": "(주)예시건설",
         "bidwinnrTelNo": "053-111-1111", "bidNtceNo": "R26BK0002"},
        {"_src": "pre", "_kind": "공사", "prdctClsfcNoNm": "구미 인동생활문화센터 리모델링 공사",
         "rlDminsttNm": "경상북도 구미시", "bfSpecRgstNo": "123456"},
        {"_src": "bid", "_kind": "공사", "bidNtceNm": "달서구 도로 포장공사", "dminsttNm": "대구광역시 달서구"},
        {"_src": "bid", "_kind": "용역", "bidNtceNm": "서울시청 사무실 이전 용역", "dminsttNm": "서울특별시"},
        {"_src": "bid", "_kind": "용역", "bidNtceNm": "안동시립박물관 소장품 이전", "dminsttNm": "경상북도 안동시"},
    ]
    recs = R.evaluate(sample, rules)
    for r in recs:
        print(f"{r['점수']:>3} {r['등급']} [{r['출처']}] {r['제목']} / {r['지역']} / {r['이유']}")
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--history", type=int)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--calllist", action="store_true")
    ap.add_argument("--mail", action="store_true")
    ap.add_argument("--mailtest", action="store_true")
    ap.add_argument("--sentcheck", action="store_true")
    ap.add_argument("--dm", action="store_true")
    ap.add_argument("--dmdone", type=int)
    a = ap.parse_args()
    setup_log(a.quiet)
    global QUIET
    QUIET = a.quiet
    try:
        if a.selftest:
            run_selftest()
        elif a.dm:
            import dm
            dm.write()
        elif a.dmdone:
            import dm
            dm.mark_sent(a.dmdone)
            calllist.write()
        elif a.sentcheck:
            import mailer
            mailer.check_sent_box(days=7)
            calllist.write()
        elif a.mail or a.mailtest:
            import mailer
            n = mailer.run(test=a.mailtest)
            if n and not a.mailtest:
                calllist.write()
        elif a.calllist:
            import neis
            neis.load(force=True)
            p, n = calllist.write()
            print(f"영업 콜리스트 {n}곳 → 영업DB 맨 앞 '콜리스트' 시트\n{p}")
        elif a.check:
            run_check()
        elif a.history:
            run_history(a.history)
        else:
            run_daily()
    except Exception as e:  # 자동실행 중 멈추면 알림
        logging.exception("실행 실패")
        notifier.notify(f"[나라장터 추적] 실행 실패: {e}")
        raise


if __name__ == "__main__":
    main()
