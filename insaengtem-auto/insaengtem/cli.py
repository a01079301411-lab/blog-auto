"""python -m insaengtem <명령>  — 전체 명령 목록은 README.md 참고."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from . import db, qa
from .config import env as env_get, fmt_when, now


def _keys(args_keys):
    from .catalog import available
    return args_keys or [c["key"] for c in available()]


def cmd_links(a):
    from .catalog import import_links, load_links, set_link
    if a.action == "import":
        print(f"{import_links(a.arg1)}개 링크를 secrets/affiliate_links.json 으로 옮김")
    elif a.action == "set":
        set_link(a.arg1, a.arg2)
        print("저장됨")
    else:
        for k, v in load_links().items():
            print(f"{k}: {v[:60]}…sl=****")


def cmd_scrape(a):
    from .scrape_yogo import scrape
    scrape(a.keys or None, headless=a.headless)


def cmd_generate(a):
    from .generate import generate
    for k in _keys(a.keys):
        _, posts, issues = generate(k, use_llm=not a.no_llm, keep_existing_cfg=not a.force_video_json)
        e, w = qa.summarize(issues)
        print(f"[{k}] 생성: {posts.get('generator')} · 오류 {e} · 경고 {w}")
        for i in issues:
            print("   ", i)


def cmd_check(a):
    from .catalog import load_facts, load_product_cfg, usp_of
    from .schedule import load_week1, validate
    from .usp import allowed_amounts
    total = []
    for k in _keys(a.keys):
        try:
            f = load_facts(k)
            u = usp_of(f)
            allowed = allowed_amounts(u, [f.get("list_price") or 0, f.get("sale_price") or 0])
        except SystemExit:
            f, allowed = None, None
        total += qa.check_product_cfg(load_product_cfg(k), f, allowed, k)
    if a.week1:
        w1 = load_week1()
        total += [i for i in validate(w1) if i.code != "VIDEO_NOT_RENDERED"]
        for p in w1:
            plat = "instagram" if p["platform"] == "instagram" else "threads_root"
            total += qa.check_text(p["text"], where=f"{p['platform']} {p['when_kst']}", is_ad=bool(p["product"]), platform=plat)
    for i in total:
        print(i)
    e, w = qa.summarize(total)
    print(f"\n오류 {e} · 경고 {w}")


def cmd_render(a):
    from .render import render_many
    from .config import settings
    variants = a.variants.split(",") if a.variants else settings()["variants"]
    render_many(_keys(a.keys), variants, stills=a.stills, jobs=a.jobs)


def cmd_plan(a):
    from .schedule import build_week, save_plan_json, validate
    start = date.fromisoformat(a.start) if a.start else (now().date() + timedelta(days=(7 - now().weekday()) % 7 or 7))
    with db.connect() as con:
        hist = [dict(r) for r in con.execute("SELECT * FROM posts").fetchall()]
    plan, notes = build_week(start, a.days, a.keys or None, history=hist)
    issues = validate(plan, hist)
    for p in plan:
        print(f"{p['when_kst']} {p['platform']:9s} {p['product'] or '공감글':10s} {p['variant'] or ''}")
    for n in notes:
        print("⚠️", n)
    for i in issues:
        print(i)
    if a.save:
        with db.connect() as con:
            for p in plan:
                db.upsert_post(con, p)
        wk = plan[0]["week"] if plan else str(start)
        print(f"저장: {save_plan_json(plan, f'plan_{wk}.json')} + DB {len(plan)}건 (draft)")


def cmd_import_week1(a):
    from .schedule import load_week1
    with db.connect() as con:
        for p in load_week1():
            db.upsert_post(con, p)
    print("1주차 수동 예약분을 원장에 'external' 로 등록 (sync 로 원격 ID 매칭 → insights 수집 가능)")


def cmd_approve(a):
    from .ops import approve
    approve(a.week, a.yes)


def cmd_run_due(a):
    from .ops import run_due
    run_due(dry=a.dry)


def cmd_schedule_web(a):
    from .ops import schedule_web
    schedule_web(a.week, a.platform)


def cmd_simple(fn_path):
    def f(a):
        mod, fn = fn_path.rsplit(".", 1)
        r = getattr(__import__(f"insaengtem.{mod}", fromlist=[fn]), fn)()
        if isinstance(r, (dict, str)):
            print(json.dumps(r, ensure_ascii=False, indent=1) if isinstance(r, dict) else r)
    return f


def cmd_publish_now(a):
    from .ops import publish_now
    with db.connect() as con:
        r = con.execute("SELECT * FROM posts WHERE id=?", (a.id,)).fetchone()
        if not r:
            raise SystemExit("해당 게시물 없음")
        try:
            res = publish_now(r)
            db.set_status(con, r["id"], "published", remote_id=res.get("remote_id"), reply_remote_id=res.get("reply_remote_id"),
                          permalink=res.get("permalink"), published_at=fmt_when(now()), error=None)
            print(f"게시 완료 → {res.get('permalink')}")
        except Exception as e:  # noqa: BLE001
            db.set_status(con, r["id"], "failed", error=str(e)[:500])
            raise SystemExit(f"게시 실패: {e}")


def cmd_profile_links(a):
    from .profile_links import mark_applied, plan, text_for_app
    p = plan()
    if a.done:
        mark_applied([i["key"] for i in p["items"]])
        print("등록 완료로 기록")
    else:
        print(text_for_app(p))
        print("\n상태:", "변경 필요 ❗" if p["changed"] else "최신 ✅")


def cmd_products(a):
    from .catalog import add_links_bulk, load_catalog, load_links
    if a.action == "add":
        import sys
        text = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
        r = add_links_bulk(text)
        print(f"신규 {len(r['added'])} · 갱신 {len(r['updated'])} · 제외(sl 없음) {len(r['skipped'])}")
        if r["added"]:
            print("→ 다음: python -m insaengtem scrape " + " ".join(r["added"]))
    else:
        links = load_links()
        for c in sorted(load_catalog(), key=lambda c: c.get("no") or 0):
            print(f"{c.get('no', ''):>4} {c['key']:<12} {('판매중' if c.get('available') else '제외'):4} "
                  f"{'링크✓' if c['key'] in links else '링크✗'} {c.get('category', ''):<8} {c.get('name') or ''}")


def cmd_shop(a):
    from .shop import build, deploy, export_inpock
    if a.action == "build":
        build()
    elif a.action == "deploy":
        build()
        deploy()
    else:
        print(export_inpock())


def cmd_trends(a):
    from .trends import add_manual, run
    if a.action == "add":
        add_manual(a.url, a.platform, a.text, a.views, a.note or "")
        print("추가 → data/trends/latest.json, report 갱신")
    else:
        run()


def cmd_weekly(a):
    from .weekly import evaluate
    r = evaluate(a.days)
    print(json.dumps(r, ensure_ascii=False, indent=1))


def cmd_auto(a):
    """일요일 밤 일괄: 품절 재확인 → 원고 → 렌더 → 다음 주 계획 → 검토 페이지. 승인은 사람이 1회."""
    from .dashboard import build
    from .ops import approve
    steps = []
    try:
        from .scrape_yogo import scrape
        scrape(None, headless=True, only_stale=True)
        steps.append("scrape")
    except SystemExit as e:
        print(f"[auto] scrape 건너뜀: {e}")
    try:
        from .ops import insights, sync
        sync(); insights()
        steps.append("insights")
    except SystemExit as e:
        print(f"[auto] insights 건너뜀: {e}")
    from .weekly import evaluate
    evaluate()
    try:
        from .trends import run
        run()
    except SystemExit as e:
        print(f"[auto] trends 건너뜀: {e}")
    from .schedule import select_week_products
    with db.connect() as con:
        hist = [dict(r) for r in con.execute("SELECT * FROM posts").fetchall()]
    keys = select_week_products(hist)
    print(f"[auto] 이번 주 영상 제품 {len(keys)}개: {', '.join(keys)}")
    cmd_generate(argparse.Namespace(keys=keys, no_llm=False, force_video_json=False))
    cmd_render(argparse.Namespace(keys=keys, variants="", stills=False, jobs=3))
    start = now().date() + timedelta(days=(7 - now().weekday()) % 7 or 7)
    cmd_plan(argparse.Namespace(start=start.isoformat(), days=7, keys=keys, save=True))
    try:
        from .shop import build, deploy
        build()
        if env_get("S3_BUCKET"):
            deploy()
    except SystemExit as e:
        print(f"[auto] 링크샵 배포 건너뜀: {e}")
    week = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
    approve(week, yes=False)
    print(build())
    print(f"[auto] 완료 → 검토 후: python -m insaengtem approve --week {week} --yes")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="insaengtem", description="인생템연구소 인스타·스레드 자동 운영")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("links", help="제휴 링크(비공개) 관리"); p.add_argument("action", choices=["import", "set", "list"])
    p.add_argument("arg1", nargs="?"); p.add_argument("arg2", nargs="?"); p.set_defaults(f=cmd_links)
    p = sp.add_parser("login", help="전용 크롬 프로필에 1회 로그인"); p.set_defaults(f=lambda a: __import__("insaengtem.publish.web", fromlist=["login"]).login())
    p = sp.add_parser("scrape", help="YOGO 상세페이지 수집(PC)"); p.add_argument("keys", nargs="*"); p.add_argument("--headless", action="store_true"); p.set_defaults(f=cmd_scrape)
    p = sp.add_parser("generate", help="원고 생성(Claude→실패 시 템플릿)"); p.add_argument("keys", nargs="*")
    p.add_argument("--no-llm", action="store_true"); p.add_argument("--force-video-json", action="store_true", help="기존 제품 영상 JSON 도 덮어씀"); p.set_defaults(f=cmd_generate)
    p = sp.add_parser("check", help="검수"); p.add_argument("keys", nargs="*"); p.add_argument("--week1", action="store_true"); p.set_defaults(f=cmd_check)
    p = sp.add_parser("render", help="영상 렌더"); p.add_argument("keys", nargs="*"); p.add_argument("--variants", default="", help="예: v1,v2 (기본: 설정의 전체 버전)")
    p.add_argument("--stills", action="store_true"); p.add_argument("--jobs", type=int, default=3); p.set_defaults(f=cmd_render)
    p = sp.add_parser("plan", help="주간 일정 생성"); p.add_argument("--start"); p.add_argument("--days", type=int, default=7)
    p.add_argument("keys", nargs="*"); p.add_argument("--save", action="store_true"); p.set_defaults(f=cmd_plan)
    p = sp.add_parser("import-week1", help="1주차 수동 예약분 원장 등록"); p.set_defaults(f=cmd_import_week1)
    p = sp.add_parser("approve", help="주간 묶음 승인"); p.add_argument("--week", required=True); p.add_argument("--yes", action="store_true"); p.set_defaults(f=cmd_approve)
    p = sp.add_parser("run-due", help="[API] 시각 된 승인 건 게시 (5분마다)"); p.add_argument("--dry", action="store_true"); p.set_defaults(f=cmd_run_due)
    p = sp.add_parser("schedule-web", help="[웹] 승인 묶음을 예약 기능으로 일괄 예약"); p.add_argument("--week", required=True)
    p.add_argument("--platform", choices=["threads", "instagram"], required=True); p.set_defaults(f=cmd_schedule_web)
    p = sp.add_parser("publish-now", help="한 건 즉시 게시"); p.add_argument("id", type=int); p.set_defaults(f=cmd_publish_now)
    sp.add_parser("refresh-token", help="스레드 장기 토큰 갱신").set_defaults(
        f=lambda a: print(f"갱신 완료, 남은 {__import__('insaengtem.publish.meta_api', fromlist=['Threads']).Threads().refresh_token() // 86400}일"))
    p = sp.add_parser("profile-links", help="인스타 프로필에 걸 링크 5개(앱에서 직접 등록)"); p.add_argument("--done", action="store_true")
    p.set_defaults(f=cmd_profile_links)
    p = sp.add_parser("products", help="제품 목록 / 제휴 링크 대량 등록"); p.add_argument("action", nargs="?", choices=["list", "add"], default="list")
    p.add_argument("--file", help="링크가 들어있는 텍스트 파일(없으면 붙여넣기 입력)"); p.set_defaults(f=cmd_products)
    p = sp.add_parser("shop", help="링크샵 만들기/배포/인포크 내보내기"); p.add_argument("action", choices=["build", "deploy", "inpock"])
    p.set_defaults(f=cmd_shop)
    sp.add_parser("sync", help="게시물 원격 ID 매칭").set_defaults(f=cmd_simple("ops.sync"))
    sp.add_parser("insights", help="성과 수집").set_defaults(f=cmd_simple("ops.insights"))
    sp.add_parser("inbox", help="새 답글·댓글").set_defaults(f=cmd_simple("ops.inbox"))
    p = sp.add_parser("trends", help="잘 터진 콘텐츠 수집·분석"); p.add_argument("action", nargs="?", choices=["fetch", "add"], default="fetch")
    p.add_argument("--url"); p.add_argument("--platform", default="instagram"); p.add_argument("--text", default="")
    p.add_argument("--views", type=int); p.add_argument("--note"); p.set_defaults(f=cmd_trends)
    p = sp.add_parser("weekly", help="주간 성과→다음 주 가중치"); p.add_argument("--days", type=int, default=7); p.set_defaults(f=cmd_weekly)
    sp.add_parser("dashboard", help="관리 대시보드 HTML").set_defaults(f=cmd_simple("dashboard.build"))
    sp.add_parser("auto", help="일요일 밤 일괄 실행").set_defaults(f=cmd_auto)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
