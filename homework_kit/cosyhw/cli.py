"""명령줄 진입점.

  [1단계] python hw.py plan --quest 3-1-1 --guide 가이드.md        → collector/urls_3-1-1.txt (레퍼런스 후보·계정·랜딩)
  [2단계·성민 PC] python collector/collector.py collect collector/urls_3-1-1.txt collector/results.json
  [3단계] python hw.py run --quest 3-1-1 --guide 가이드.md         → results.json 실측으로 숙제 완성
          (실측이 빠진 링크는 collector/missing_urls_3-1-1.txt로 출력 → 2단계 재실행)
  python hw.py results [--quest 3-1-1]   results.json 요약·오래된 수치·지정 레퍼런스 수집 여부
  python hw.py inspect 양식.xlsx
  python hw.py check 결과.xlsx --template 양식.xlsx
  python hw.py render 결과.xlsx
  python hw.py fill --template 양식.xlsx --cells cells.json --out 결과.xlsx
  python hw.py list
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

from . import checks
from . import template as tpl
from .metrics import COLLECTOR_DIR, Store
from .paths import KIT, OUTPUT, find_quest, load_quests, norm_id


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _expand(paths: list[str]) -> list[str]:
    out = []
    for p in paths or []:
        hits = sorted(glob.glob(p))
        if not hits and Path(p).is_dir():
            hits = sorted(str(x) for x in Path(p).iterdir() if x.is_file())
        out += hits or [p]
    for p in out:
        if not Path(p).exists():
            sys.exit(f"파일 없음: {p}")
    return out


def _resolve_template(args) -> tuple[str, dict | None]:
    known = find_quest(args.quest) if getattr(args, "quest", None) else None
    t = args.template or (known and known.get("template") and str(KIT / known["template"]))
    if not t or not Path(t).exists():
        sys.exit("양식 xlsx를 --template로 지정하세요 (quests.json에 등록된 퀘스트면 생략 가능)")
    return t, known


def cmd_run(args):
    from . import agent, prompts, report
    template, known = _resolve_template(args)
    guides = _expand(args.guide)
    sheet = args.sheet or (known or {}).get("sheet")
    cm = tpl.analyze(template, sheet)
    if not cm.fillable:
        sys.exit("양식에서 채울 칸을 찾지 못했습니다. `python hw.py inspect 양식.xlsx`로 구조를 확인하세요.")
    qid = norm_id(args.quest)
    today = args.date or dt.date.today().isoformat()
    out_dir = Path(args.out or OUTPUT / f"{qid}_{dt.datetime.now():%Y%m%d-%H%M}")
    out_dir.mkdir(parents=True, exist_ok=True)
    fixed = {k: str(v) for k, v in ((known or {}).get("fixed") or {}).items()}
    note = args.note or ""
    if args.note_file:
        note += "\n" + Path(args.note_file).read_text(encoding="utf-8")
    store = Store.load(args.results)
    print(store.summary())
    old = store.stale()
    if old:
        print(f"[경고] 수집 후 3일 넘은 수치 {len(old)}건 — 최신 수치가 필요하면 PC에서 다시 collect 하세요 (예: {old[0]})")
    missing_fixed = [u for u in fixed.values() if checks.REF_URL.search(u) and not store.has(u)]
    if missing_fixed:
        print(f"[경고] 양식 지정 레퍼런스 {len(missing_fixed)}개가 results.json에 없음 → 해당 행은 완성 불가: {missing_fixed}")
    note += ("\n\n[results.json 상태] " + store.summary() +
             "\n- 수치는 get_metrics로 이 파일에서만 가져온다. 목록은 list_collected로 확인.")
    brief = prompts.briefing(qid, today, known, tpl.describe(cm), tpl.dump(template, cm.sheet), note)
    job = agent.Job(quest_id=qid, template=template, out_dir=out_dir, cm=cm, today=today, fixed=fixed, store=store)
    (out_dir / "briefing.txt").write_text(brief, encoding="utf-8")
    if args.dry_run:
        print(brief)
        print(f"\n[dry-run] 가이드 {len(guides)}개, 채울 칸 {len(cm.fillable)}개. API 호출 없이 종료. 브리핑: {out_dir / 'briefing.txt'}")
        return
    print(f"[시작] {qid} · 채울 칸 {len(cm.fillable)}개 · 가이드 {len(guides)}개 · 결과 폴더 {out_dir}")
    agent.run(job, prompts.system_prompt(), brief, guides, effort=args.effort, max_turns=args.max_turns)
    for u in missing_fixed:
        store.need(u, "양식 지정 레퍼런스")
    miss = store.write_missing(COLLECTOR_DIR / f"missing_urls_{qid}.txt")
    rpt = report.write_report(job)
    if job.submission and job.report and job.report.ok:
        report.register_quest(job, template, guides)
    print("\n========== 완료 ==========" if job.report and job.report.ok else "\n========== 미완성 ==========")
    if job.report:
        print(job.report.text())
    print(f"결과 xlsx : {job.xlsx}")
    print(f"보고서    : {rpt}")
    for i, t in enumerate((job.submission or {}).get("todo_for_user", []), 1):
        print(f"  성민 할 일 {i}. {t}")
    if miss:
        print(f"\n[수집 필요] {len(store.missing)}개 링크의 실측이 없습니다(추정하지 않음). 성민 PC에서:")
        print(f"  python collector/collector.py collect {miss.relative_to(KIT).as_posix()} collector/results.json")
        print("  → 끝나면 같은 run 명령을 다시 실행")
    sys.exit(0 if job.report and job.report.ok else 1)


def cmd_plan(args):
    """1단계: 가이드 기준으로 레퍼런스 후보·계정·랜딩 페이지를 골라 수집기 입력 파일(urls_*.txt)을 만든다."""
    from . import agent, prompts
    template, known = _resolve_template(args)
    guides = _expand(args.guide)
    cm = tpl.analyze(template, args.sheet or (known or {}).get("sheet"))
    qid = norm_id(args.quest)
    today = dt.date.today().isoformat()
    out_dir = Path(args.out or OUTPUT / f"{qid}_plan_{dt.datetime.now():%Y%m%d-%H%M}")
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Store.load(args.results)
    brief = prompts.briefing(qid, today, known, tpl.describe(cm), tpl.dump(template, cm.sheet), args.note or "")
    brief += "\n\n[지금 할 일] 1단계: 레퍼런스 후보를 골라 save_url_plan으로 저장(수치 확인·작성은 하지 않음)."
    if store.data:
        brief += "\n이미 수집된 링크(중복 제외용): " + ", ".join(list(store.data)[:80])
    job = agent.Job(quest_id=qid, template=template, out_dir=out_dir, cm=cm, today=today, store=store)
    if args.dry_run:
        print(brief); return
    agent.run(job, prompts.PLAN_ROLE, brief, guides, effort=args.effort, max_turns=args.max_turns, mode="plan")
    if not job.url_plan:
        sys.exit("후보 목록을 만들지 못했습니다. log.jsonl을 확인하세요.")
    fixed = [str(v).strip() for v in ((known or {}).get("fixed") or {}).values() if checks.REF_URL.search(str(v))]
    lines = [f"# {qid} 수집 목록 ({today}) — 성민 PC: python collector/collector.py collect collector/urls_{qid}.txt collector/results.json",
             "# [양식 지정 레퍼런스]"] + [u if u.startswith("http") else "https://" + u for u in fixed]
    by = {}
    for it in job.url_plan["items"]:
        by.setdefault(it["category"], []).append(it)
    for cat, its in by.items():
        lines.append(f"# [{cat}]")
        for it in its:
            lines.append(f"# {it['why'][:100]}")
            lines.append(it["url"])
    lines.append("# [계정: 평소 대비·프로필 링크]")
    lines += job.url_plan["accounts"]
    lines.append("# [랜딩 페이지]")
    lines += job.url_plan["extra_pages"]
    seen, out = set(), []
    for l in lines:
        if l.startswith("#") or l.strip() not in seen:
            out.append(l)
            seen.add(l.strip())
    path = COLLECTOR_DIR / f"urls_{qid}.txt"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    (out_dir / "url_plan.json").write_text(json.dumps(job.url_plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[완료] 후보 {len(job.url_plan['items'])}개 + 계정 {len(job.url_plan['accounts'])}개 + 랜딩 {len(job.url_plan['extra_pages'])}개 → {path}")
    print(f"성민 PC에서: python collector/collector.py collect {path.relative_to(KIT).as_posix()} collector/results.json")


def cmd_results(args):
    st = Store.load(args.results)
    print(st.summary())
    for o in st.stale()[:5]:
        print("  [3일 경과]", o)
    errs = [(k, v["err"]) for k, v in st.data.items() if "err" in v]
    for k, e in errs[:20]:
        print("  [실패]", k, "→", e[:80])
    if args.quest:
        known = find_quest(args.quest) or {}
        for c, u in (known.get("fixed") or {}).items():
            if checks.REF_URL.search(str(u)):
                print(f"  지정 {c}: {'수집됨' if st.has(str(u)) else '없음 → 수집 필요'}  {u}")


def cmd_inspect(args):
    cm = tpl.analyze(args.template, args.sheet)
    print(tpl.describe(cm))
    if args.json:
        print(json.dumps(cm.to_dict(), ensure_ascii=False, indent=1, default=str))
    if args.dump:
        print("\n" + tpl.dump(args.template, args.sheet))


def cmd_check(args):
    from . import checks
    template = args.template
    if not template and args.quest:
        template, _ = _resolve_template(args)
    if not template:
        sys.exit("--template 또는 --quest 필요 (빈칸 기준이 되는 원본 양식)")
    cm = tpl.analyze(template, args.sheet)
    rep = checks.check(args.xlsx, cm, store=Store.load(args.results))
    print(rep.text())
    sys.exit(0 if rep.ok else 1)


def cmd_render(args):
    from . import render
    pdf, pngs, note = render.render(args.xlsx, args.out or str(Path(args.xlsx).parent / "render"))
    print(pdf, *pngs, note, sep="\n")


def cmd_fill(args):
    from . import checks, writer
    cm = tpl.analyze(args.template, args.sheet)
    cells = json.loads(Path(args.cells).read_text(encoding="utf-8"))
    if isinstance(cells, dict) and "cells" in cells:
        cells = cells["cells"]
    warns = writer.fill(args.template, args.out, cells, sheet=cm.sheet, keep_prefilled=cm.prefilled)
    rep = checks.check(args.out, cm)
    print(*warns, rep.text(), sep="\n")


def cmd_list(args):
    for q in load_quests()["quests"]:
        print(f"{q['id']:8} {q.get('status', ''):20} {q.get('title', '')}")


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(prog="hw", description="COSY 숙제 프로그램")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="가이드+양식 → 숙제 완성 (Claude API)")
    r.add_argument("--quest", required=True, help="퀘스트 번호 (예: 2-4-q1, 3-1)")
    r.add_argument("--template", help="COSY 양식 xlsx (등록된 퀘스트면 생략 가능)")
    r.add_argument("--guide", nargs="*", default=[], help="가이드 스크린샷/문서 (여러 개, 폴더·와일드카드 가능)")
    r.add_argument("--sheet")
    r.add_argument("--note", help="추가 지시 (예: '인스타 위주로')")
    r.add_argument("--note-file")
    r.add_argument("--date", help="작성일 (기본 오늘)")
    r.add_argument("--out", help="결과 폴더")
    r.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--max-turns", type=int, default=80)
    r.add_argument("--dry-run", action="store_true", help="API 호출 없이 브리핑만 출력")
    r.add_argument("--results", help="실측 파일 (기본 collector/results.json)")
    r.set_defaults(func=cmd_run)

    pl = sub.add_parser("plan", help="1단계: 가이드 기준 레퍼런스 후보 → collector/urls_퀘스트.txt")
    pl.add_argument("--quest", required=True); pl.add_argument("--template"); pl.add_argument("--sheet")
    pl.add_argument("--guide", nargs="*", default=[]); pl.add_argument("--note"); pl.add_argument("--out")
    pl.add_argument("--results"); pl.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    pl.add_argument("--max-turns", type=int, default=60); pl.add_argument("--dry-run", action="store_true")
    pl.set_defaults(func=cmd_plan)

    rs = sub.add_parser("results", help="results.json 요약·오래된 수치·지정 레퍼런스 수집 여부")
    rs.add_argument("--results"); rs.add_argument("--quest"); rs.set_defaults(func=cmd_results)

    i = sub.add_parser("inspect", help="양식 구조·채울 칸 분석")
    i.add_argument("template"); i.add_argument("--sheet"); i.add_argument("--json", action="store_true")
    i.add_argument("--dump", action="store_true")
    i.set_defaults(func=cmd_inspect)


    k = sub.add_parser("check", help="결과 xlsx 검증")
    k.add_argument("xlsx"); k.add_argument("--template"); k.add_argument("--quest"); k.add_argument("--sheet")
    k.add_argument("--results")
    k.set_defaults(func=cmd_check)

    d = sub.add_parser("render", help="xlsx → PDF/PNG")
    d.add_argument("xlsx"); d.add_argument("--out"); d.set_defaults(func=cmd_render)

    f = sub.add_parser("fill", help="cells.json으로 양식 채우기 (AI 없이)")
    f.add_argument("--template", required=True); f.add_argument("--cells", required=True)
    f.add_argument("--out", required=True); f.add_argument("--sheet")
    f.set_defaults(func=cmd_fill)

    sub.add_parser("list", help="퀘스트 목록").set_defaults(func=cmd_list)
    args = ap.parse_args(argv)
    args.func(args)
