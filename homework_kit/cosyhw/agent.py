"""Claude 에이전트 루프: 가이드 학습 → 실측 수집 → 작성 → 제출(검증·렌더) → 재제출."""
from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from . import checks, render, writer
from .fmt import fmt_count
from .metrics import Store, norm_url
from .paths import KIT, MODEL, USER_NAME
from .template import CellMap

MAX_TOOL_TEXT = 30_000


# ---------------------------------------------------------------- 도구 정의
def _tool(name, desc, props, required):
    return {
        "name": name, "description": desc, "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
    }


TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 60},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 80},
    _tool("get_metrics", "성민 PC 수집기(collector.py)가 만든 results.json에서 링크 1개의 실측 결과를 가져온다. "
          "유튜브 영상·커뮤니티 글, 인스타 게시물·계정(소개글·링크·최근 릴스), 틱톡, 그 밖의 페이지(스레드·블로그·랜딩) 모두. "
          "없으면 오류가 나고 그 링크는 '수집 필요' 목록에 자동으로 올라간다. 수치는 반드시 이 도구 결과만 쓴다.",
          {"url": {"type": "string"}}, ["url"]),
    _tool("list_collected", "results.json에 들어 있는 링크 목록(종류·수집 시각·성공/실패)을 본다. 어떤 레퍼런스를 쓸 수 있는지 고를 때 사용.",
          {"filter": {"type": "string", "description": "링크에 포함된 글자로 거르기(선택)"}}, []),
    _tool("compare_vs_recent", "평소 대비: 대상 게시물과 그 계정 링크의 수집 결과로, 고정·대상 게시물을 빼고 최근 5~10개 평균 대비 배수를 계산한다.",
          {"target_url": {"type": "string"}, "account_url": {"type": "string"}}, ["target_url", "account_url"]),
    _tool("view_shot", "수집기가 찍은 화면 캡처(영상 0.5초 후킹 프레임, 카드뉴스 표지, 글·랜딩 페이지)를 본다. 없으면 '캡처 필요'.",
          {"url": {"type": "string"}}, ["url"]),
    _tool("request_collection", "실측이 필요한데 results.json에 없는 링크를 '수집 필요' 목록에 올린다(새 레퍼런스 후보, 랜딩 페이지, 계정 링크 등).",
          {"urls": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}, ["urls", "reason"]),
    _tool("format_counts", "정수들을 표기 규칙(1만 이상 '3.4만', 미만 '9,627')으로 바꾼다.",
          {"numbers": {"type": "array", "items": {"type": "integer"}}}, ["numbers"]),
    _tool("read_kit_file", "homework_kit 안의 자료 파일(docs/…, quests.json 등)을 읽는다.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("submit_homework",
          "완성한 숙제를 제출한다. 프로그램이 양식에 써서 검증·렌더하고 결과(오류 목록·렌더 이미지)를 돌려준다. "
          "오류가 있으면 고쳐서 cells 전체를 다시 제출한다.",
          {
              "quest_title": {"type": "string"},
              "file_topic": {"type": "string", "description": "파일명용 짧은 내용(예: 플랫폼레퍼런스)"},
              "cells": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "properties": {"cell": {"type": "string", "description": "예: D12 (다른 시트면 '시트명!B4')"},
                                 "value": {"type": "string"}},
                  "required": ["cell", "value"]}},
              "guide_analysis": {"type": "string", "description": "가이드 분석 보고: 목적·칸별 작성법·통과/반려 예·금지 표현·제출물·자주 하는 실수"},
              "sources": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "properties": {"item": {"type": "string"}, "url": {"type": "string"},
                                 "checked": {"type": "string", "description": "확인한 값·확인 시각"}},
                  "required": ["item", "url", "checked"]}},
              "learning_points": {"type": "array", "items": {"type": "string"},
                                  "description": "성민이 이 숙제에서 배워야 할 핵심(왜 이렇게 썼는지)"},
              "unverified": {"type": "array", "items": {"type": "string"}},
              "todo_for_user": {"type": "array", "items": {"type": "string"},
                                "description": "성민이 직접 할 일(업로드·앱 화면 확인·캡처·COSY 제출) 순서대로"},
          },
          ["quest_title", "file_topic", "cells", "guide_analysis", "sources", "learning_points", "unverified", "todo_for_user"]),
]
PLAN_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 80},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 60},
    _tool("read_kit_file", "homework_kit 안의 자료 파일(docs/…, quests.json 등)을 읽는다.",
          {"path": {"type": "string"}}, ["path"]),
    _tool("save_url_plan",
          "가이드에 맞는 레퍼런스 후보와 수집할 링크 목록을 저장한다(성민 PC 수집기 입력 파일). 분류마다 필요한 개수보다 넉넉히(1.5~2배) 고른다.",
          {"items": {"type": "array", "items": {
              "type": "object", "additionalProperties": False,
              "properties": {"category": {"type": "string"}, "url": {"type": "string"},
                             "why": {"type": "string", "description": "고른 이유(최신성·반응·랜딩 근거)"}},
              "required": ["category", "url", "why"]}},
           "accounts": {"type": "array", "items": {"type": "string"},
                        "description": "평소 대비·프로필 링크(랜딩) 확인용 계정 링크"},
           "extra_pages": {"type": "array", "items": {"type": "string"},
                           "description": "랜딩 확인용 페이지(링크트리·상품 페이지 등)"},
           "notes": {"type": "string"}},
          ["items", "accounts", "extra_pages", "notes"]),
]
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS + PLAN_TOOLS if "input_schema" in t}


def _validate(name: str, args) -> str | None:
    """eager_input_streaming이면 SDK가 입력을 검증하지 않으므로 직접 확인."""
    sch = _SCHEMAS.get(name)
    if sch is None:
        return f"알 수 없는 도구: {name}"
    if not isinstance(args, dict):
        return "입력이 JSON 객체가 아님(잘렸을 수 있음) — 다시 호출"
    for k in sch["required"]:
        if k not in args:
            return f"필수 입력 '{k}' 누락(입력이 잘렸을 수 있음) — 다시 호출"
    tmap = {"string": str, "integer": int, "number": (int, float), "array": list, "object": dict}
    for k, v in args.items():
        p = sch["properties"].get(k)
        if p is None:
            return f"정의되지 않은 입력 '{k}'"
        if not isinstance(v, tmap[p["type"]]):
            return f"입력 '{k}' 형식 오류({p['type']} 필요)"
    return None


def _img_block(path: str) -> dict:
    mt = mimetypes.guess_type(path)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": mt,
                                         "data": base64.standard_b64encode(Path(path).read_bytes()).decode()}}


def _jtext(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    return s if len(s) <= MAX_TOOL_TEXT else s[:MAX_TOOL_TEXT] + "\n...(생략)"


# ---------------------------------------------------------------- 실행 상태
@dataclass
class Job:
    quest_id: str
    template: str
    out_dir: Path
    cm: CellMap
    today: str
    fixed: dict = field(default_factory=dict)
    submission: dict | None = None
    xlsx: str | None = None
    report: checks.Report | None = None
    pngs: list = field(default_factory=list)
    submits: int = 0
    log: list = field(default_factory=list)
    store: Store | None = None
    url_plan: dict | None = None
    plan_path: Path | None = None

    def logf(self, kind: str, data) -> None:
        rec = {"t": time.strftime("%H:%M:%S"), "kind": kind, "data": data}
        self.log.append(rec)
        with open(self.out_dir / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str)[:20000] + "\n")


def _safe_name(s: str) -> str:
    return "".join(ch for ch in s if ch not in '\\/:*?"<>|').strip().replace(" ", "")


def do_submit(job: Job, args: dict) -> list:
    job.submits += 1
    cells = {c["cell"].strip().upper(): c["value"] for c in args["cells"]}
    if job.cm.name_cell:
        cells[job.cm.name_cell] = USER_NAME
    if job.cm.date_cell:
        cells[job.cm.date_cell] = job.today
    cells.update(job.fixed)
    qid = job.quest_id.replace("-q", "_q")
    out = job.out_dir / f"{qid}_{_safe_name(args['file_topic'])}_{USER_NAME}.xlsx"
    warns = writer.fill(job.template, str(out), cells, sheet=job.cm.sheet, keep_prefilled=job.cm.prefilled)
    rep = checks.check(str(out), job.cm, fixed=job.fixed, store=job.store)
    rep.warnings = warns + rep.warnings
    pdf, pngs, note = render.render(str(out), str(job.out_dir / "render"))
    job.submission, job.xlsx, job.report, job.pngs = args, str(out), rep, pngs
    job.logf("submit", {"n": job.submits, "ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings})
    msg = [rep.text()]
    if note:
        msg.append(note)
    if rep.ok:
        msg.append("검증 통과. 아래 렌더 이미지에서 글자 잘림·칸 넘침·어색한 문장을 확인하고, 고칠 게 있으면 cells 전체를 다시 제출, "
                   "없으면 한두 문장으로 마무리해.")
    else:
        msg.append("오류를 모두 고쳐서 cells 전체를 다시 submit_homework로 제출해.")
    blocks: list = [{"type": "text", "text": "\n".join(msg)}]
    for p in pngs[:3]:
        blocks.append(_img_block(p))
    return blocks


def run_tool(job: Job, name: str, args: dict) -> tuple[list | str, bool]:
    """(tool_result content, is_error)."""
    err = _validate(name, args)
    if err:
        return err, True
    try:
        if name == "get_metrics":
            st = job.store
            r = st.get(args["url"])
            if r is None:
                why = st.error_of(args["url"])
                st.need(args["url"], "레퍼런스 실측" + (f" (지난 수집 실패: {why})" if why else ""))
                return (f"results.json에 실측 없음{' (수집 실패: ' + why + ')' if why else ''} → '수집 필요' 목록에 올림. "
                        "이 링크의 수치는 추정하지 말고, 다른 수집된 레퍼런스를 쓰거나 PC 재수집 후 진행"), True
            return _jtext(r), False
        if name == "list_collected":
            f = (args.get("filter") or "").lower()
            rows = [{"url": k, "platform": v.get("platform"), "kind": v.get("kind"),
                     "collected_at": v.get("collected_at"), "ok": "err" not in v,
                     "hint": (v.get("title") or v.get("caption") or v.get("text") or v.get("desc") or v.get("err") or "")[:60]}
                    for k, v in job.store.data.items() if f in k.lower()]
            return _jtext({"count": len(rows), "items": rows}), False
        if name == "compare_vs_recent":
            res = job.store.baseline(args["target_url"], args["account_url"])
            return _jtext(res), "error" in res
        if name == "view_shot":
            p = job.store.shot(args["url"])
            if not p:
                return "캡처 필요 — shots/에 이 링크의 캡처가 없음(PC에서 collect 시 자동 저장). 화면 문구는 캡션·본문 텍스트로만 인용", True
            return [{"type": "text", "text": f"캡처: {p.name}"}, _img_block(str(p))], False
        if name == "request_collection":
            for u in args["urls"]:
                job.store.need(u, args["reason"])
            return f"{len(args['urls'])}개를 '수집 필요' 목록에 올림(이미 수집된 것은 제외)", False
        if name == "save_url_plan":
            job.url_plan = args
            return "저장함. 짧게 요약하고 마무리해.", False
        if name == "format_counts":
            return _jtext({str(n): fmt_count(n) for n in args["numbers"]}), False
        if name == "read_kit_file":
            p = (KIT / args["path"]).resolve()
            if KIT not in p.parents and p != KIT:
                return "homework_kit 밖 파일은 읽을 수 없음", True
            return p.read_text(encoding="utf-8")[:MAX_TOOL_TEXT], False
        if name == "submit_homework":
            blocks = do_submit(job, args)
            return blocks, not job.report.ok
    except Exception as e:  # 도구 실패는 모델에게 알려 다른 방법을 찾게 한다
        return f"{type(e).__name__}: {e}", True
    return f"알 수 없는 도구: {name}", True


# ---------------------------------------------------------------- 루프
def _guide_blocks(paths: list[str]) -> list:
    blocks = []
    for p in paths:
        ext = Path(p).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            blocks.append({"type": "text", "text": f"[가이드 이미지] {Path(p).name}"})
            blocks.append(_img_block(p))
        elif ext == ".pdf":
            blocks.append({"type": "document", "title": Path(p).name, "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.standard_b64encode(Path(p).read_bytes()).decode()}})
        else:
            blocks.append({"type": "text", "text": f"[가이드 문서] {Path(p).name}\n" + Path(p).read_text(encoding="utf-8")})
    return blocks


def run(job: Job, system: str, briefing: str, guides: list[str], effort: str = "high",
        max_turns: int = 80, client: anthropic.Anthropic | None = None, verbose: bool = True,
        mode: str = "run") -> Job:
    """mode='plan': 레퍼런스 후보·수집 목록만 만든다(수치 없음). mode='run': results.json으로 숙제를 완성한다."""
    client = client or anthropic.Anthropic()
    content = _guide_blocks(guides) + [{"type": "text", "text": briefing}]
    messages: list = [{"role": "user", "content": content}]
    nudged = 0
    usage = {"in": 0, "out": 0, "cache_read": 0}

    for turn in range(1, max_turns + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=system,
            messages=messages,
            tools=PLAN_TOOLS if mode == "plan" else TOOLS,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            resp = stream.get_final_message()
        u = resp.usage
        usage["in"] += u.input_tokens or 0
        usage["out"] += u.output_tokens or 0
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if resp.stop_reason == "refusal":
            job.logf("refusal", str(getattr(resp, "stop_details", "")))
            print("[중단] 모델이 요청을 거절했습니다:", getattr(resp, "stop_details", ""))
            break

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "thinking" and verbose and b.thinking:
                print(f"  · 생각: {b.thinking.strip().splitlines()[0][:120]}")
            elif b.type == "text" and b.text.strip() and verbose:
                print(f"[Claude] {b.text.strip()[:800]}")
            elif b.type == "server_tool_use" and verbose:
                print(f"  → {b.name}: {json.dumps(b.input, ensure_ascii=False)[:120]}")
            elif b.type == "tool_use":
                args = b.input if isinstance(b.input, dict) else {}
                if verbose:
                    shown = {k: v for k, v in args.items() if k != "cells"} if b.name == "submit_homework" else args
                    print(f"  → {b.name}: {json.dumps(shown, ensure_ascii=False)[:160]}")
                if resp.stop_reason == "max_tokens":
                    out, is_err = "응답이 max_tokens에서 잘려 도구 입력이 불완전함 — 다시 호출", True
                else:
                    out, is_err = run_tool(job, b.name, args)
                job.logf("tool", {"name": b.name, "input": args if b.name != "submit_homework" else "(cells)",
                                  "error": is_err, "result": out if isinstance(out, str) else "(blocks)"})
                if verbose and is_err:
                    print(f"    ! {str(out if isinstance(out, str) else out[0]['text'])[:300]}")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})

        if results:
            messages.append({"role": "user", "content": results})
            continue
        if resp.stop_reason in ("pause_turn",):
            continue
        if resp.stop_reason == "max_tokens":
            messages.append({"role": "user", "content": "잘렸어. 이어서 진행해."})
            continue
        # end_turn
        if mode == "plan":
            if job.url_plan is None and nudged < 2:
                nudged += 1
                messages.append({"role": "user", "content": "save_url_plan으로 후보·계정·랜딩 페이지 목록을 저장해."})
                continue
            break
        if (job.report is None or not job.report.ok) and job.store is not None and job.store.missing and nudged >= 1:
            print("[보류] 실측이 없는 링크가 있어 완성하지 못했습니다(추정 금지) → 수집 필요 목록을 만듭니다.")
            break
        if job.report is None or not job.report.ok:
            if nudged >= 2:
                print("[중단] 검증을 통과한 제출 없이 끝났습니다.")
                break
            nudged += 1
            messages.append({"role": "user", "content":
                             "아직 검증을 통과한 제출이 없어. results.json에 수집된 레퍼런스로 빈칸 없이 모든 칸을 채워 submit_homework로 제출해. "
                             "수집된 레퍼런스가 모자라면 request_collection으로 필요한 링크를 올리고 마무리해(수치 추정 금지)."})
            continue
        break

    job.logf("usage", usage)
    if verbose:
        print(f"[토큰] 입력 {usage['in']:,} (캐시 읽기 {usage['cache_read']:,}) / 출력 {usage['out']:,}")
    return job
