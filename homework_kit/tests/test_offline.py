"""API·네트워크 없이 돌리는 테스트: python -m pytest tests 또는 python tests/test_offline.py"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from cosyhw import template, writer, checks, agent, prompts, report, paths, metrics  # noqa: E402
from cosyhw.fmt import fmt_count, parse_count, vs_recent  # noqa: E402

SUB = json.loads(paths.SUBMITTED.read_text(encoding="utf-8"))
QUESTS = ["1-4", "2-1_q1", "2-1_q2", "2-2_q1", "2-3_q1"]


def test_fmt():
    assert fmt_count(34000) == "3.4만" and fmt_count(9627) == "9,627" and fmt_count(961000) == "96.1만"
    assert parse_count("3.4만") == 34000 and parse_count("조회수 1.2천회") == 1200 and parse_count("12K") == 12000
    assert vs_recent(540000, [50000, 60000, 52000])["multiple_vs_avg"] == 10.0


def test_submitted_pass_checks():
    """통과된 제출본을 원본 양식에 다시 채우면 셀 맵 기준 빈칸 0·오류 0이어야 한다."""
    tmp = Path(tempfile.mkdtemp())
    for k in QUESTS:
        tp = str(KIT / "templates" / f"{k}_template.xlsx")
        cm = template.analyze(tp)
        out = str(tmp / f"{k}.xlsx")
        writer.fill(tp, out, {c: v for c, v in SUB[k]["cells"].items() if c in cm.fillable}, keep_prefilled=cm.prefilled)
        rep = checks.check(out, cm)
        assert rep.ok, (k, rep.errors)
        assert rep.filled == rep.total


def test_checks_catch_bad():
    tp = str(KIT / "templates" / "2-3_q1_template.xlsx")
    cm = template.analyze(tp)
    out = str(Path(tempfile.mkdtemp()) / "bad.xlsx")
    writer.fill(tp, out, {"B4": "성민", "D4": "11/4", "B8": "없음", "C8": "무료임"})
    errs = " ".join(checks.check(out, cm).errors)
    assert "B8 칸을" in errs and "무료임" in errs and "D8 빈칸" in errs and "YYYY-MM-DD" in errs


def test_dropdown_check():
    tp = str(KIT / "templates" / "2-2_q1_template.xlsx")
    cm = template.analyze(tp)
    out = str(Path(tempfile.mkdtemp()) / "dd.xlsx")
    writer.fill(tp, out, {"C12": "쇼츠"})
    assert any("드롭다운" in e for e in checks.check(out, cm).errors)


def test_norm_url():
    n = metrics.norm_url
    assert n("youtube.com/watch?v=014MXDS1CB0") == n("https://www.youtube.com/watch?v=014MXDS1CB0&t=3") == "yt:014MXDS1CB0"
    assert n("https://youtu.be/014MXDS1CB0") == "yt:014MXDS1CB0" == n("https://www.youtube.com/shorts/014MXDS1CB0")
    assert n("instagram.com/nobrain._.girl/reel/DcTS-BPpbNh\n") == n("https://www.instagram.com/reel/DcTS-BPpbNh/") == "ig:DcTS-BPpbNh"
    assert n("https://www.youtube.com/post/Ugkx_1") == "ytpost:Ugkx_1"
    assert n("https://www.tiktok.com/@a.b/photo/123") == "tt:123" and n("https://www.tiktok.com/@A.b") == "tt:@a.b"
    assert paths.norm_id("2-1_q1") == "2-1-q1" and paths.norm_id("2-4퀘스트2") == "2-4-q2"


def _store(tmp, now="2026-11-07 10:00", old="2026-11-01 10:00"):
    data = {
        "https://www.instagram.com/reel/AAA/": {"platform": "instagram", "kind": "post", "views": 100000, "likes": 3000,
                                                "comments": 40, "collected_at": now},
        "https://www.instagram.com/acct/": {"platform": "instagram", "kind": "account", "collected_at": now,
            "recent_reels": [{"href": "/acct/reel/P1/", "views": "900만"}, {"href": "/acct/reel/P2/", "views": "800만"},
                             {"href": "/acct/reel/P3/", "views": "700만"}, {"href": "/acct/reel/AAA/", "views": "10만"}]
                            + [{"href": f"/acct/reel/R{i}/", "views": "1만"} for i in range(6)]},
        "https://www.youtube.com/watch?v=014MXDS1CB0": {"platform": "youtube", "views": 18813, "collected_at": old},
        "https://www.instagram.com/p/BAD/": {"err": "timeout", "collected_at": now},
    }
    p = Path(tmp) / "results.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return metrics.Store.load(p)


def test_store_and_baseline():
    st = _store(tempfile.mkdtemp())
    assert st.has("instagram.com/reel/AAA") and not st.has("https://www.instagram.com/p/BAD/")
    assert st.error_of("https://www.instagram.com/p/BAD/") == "timeout"
    b = st.baseline("https://www.instagram.com/reel/AAA/", "instagram.com/acct")
    assert b["n"] == 6 and b["avg"] == "1만" and b["multiple"] == 10.0, b      # 고정 3개·대상 제외
    assert "error" in st.baseline("https://www.instagram.com/reel/AAA/", "instagram.com/none")
    assert any("014MXDS1CB0" in o for o in st.stale())                           # 3일 경과 경고
    miss = st.write_missing(Path(tempfile.mkdtemp()) / "m.txt")
    assert miss and "instagram.com/none" in miss.read_text(encoding="utf-8")


def test_check_requires_results():
    tp = str(KIT / "templates" / "3-1-1_template.xlsx")
    cm = template.analyze(tp)
    st = _store(tempfile.mkdtemp())
    cells = {c: "문장으로 채운 내용" for c in cm.fillable}
    cells.update({cm.name_cell: "성민", cm.date_cell: "2026-11-07", "C13": "https://www.instagram.com/reel/AAA/",
                  "C14": "https://www.instagram.com/p/NOTCOLLECTED/"})
    out = str(Path(tempfile.mkdtemp()) / "x.xlsx")
    writer.fill(tp, out, cells, keep_prefilled=cm.prefilled)
    errs = " ".join(checks.check(out, cm, store=st).errors)
    assert "NOTCOLLECTED" in errs and "AAA" not in errs and "DdBfondCQsX" in errs   # 지정 링크도 미수집이면 오류
    assert checks.check(out, cm).ok                                               # store 없이는 형식 검사만


# ---------------------------------------------------------- 가짜 Claude로 에이전트 루프 검증
class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return FakeStream(self.script.pop(0))


def _msg(blocks, stop):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


def _tool(i, name, inp):
    return NS(type="tool_use", id=f"t{i}", name=name, input=inp)


def test_agent_loop():
    k = "2-3_q1"
    tp = str(KIT / "templates" / f"{k}_template.xlsx")
    cm = template.analyze(tp)
    full = [{"cell": c, "value": str(v)} for c, v in SUB[k]["cells"].items() if c in cm.fillable and c not in (cm.name_cell, cm.date_cell)]
    meta = dict(quest_title="무료 소스 10곳", file_topic="무료소스정리표", guide_analysis="목적: 안전한 소스 창고",
                sources=[{"item": "Pexels", "url": "https://www.pexels.com/license/", "checked": "2026-11-04"}],
                learning_points=["상업적 이용과 출처 표기 두 가지만 본다"], unverified=[], todo_for_user=["즐겨찾기 캡처"])
    script = [
        _msg([NS(type="thinking", thinking="가이드 분석"), _tool(1, "get_metrics", {"url": "https://www.instagram.com/p/NOPE/"})], "tool_use"),
        _msg([_tool(2, "submit_homework", {**meta, "cells": full[:-1]})], "tool_use"),       # 한 칸 빠짐 → 오류
        _msg([_tool(3, "submit_homework", {**meta, "cells": full})], "tool_use"),            # 통과
        _msg([NS(type="text", text="완료")], "end_turn"),
    ]
    fake = FakeClient(script)
    out = Path(tempfile.mkdtemp())
    job = agent.Job(quest_id="2-3-q1", template=tp, out_dir=out, cm=cm, today="2026-11-04", store=_store(tempfile.mkdtemp()))
    agent.run(job, prompts.system_prompt(), "brief", [], client=fake, verbose=False)
    assert job.submits == 2 and job.report.ok
    first = fake.calls[1]["messages"][-1]["content"][0]
    assert first["is_error"] and "results.json에 실측 없음" in first["content"] and job.store.missing   # 추정 대신 수집 요청
    assert {t.get("name") for t in fake.calls[0]["tools"]} >= {"get_metrics", "compare_vs_recent", "submit_homework"}
    assert not {"collect_url", "instagram_account_recent"} & {t.get("name") for t in fake.calls[0]["tools"]}
    # 두 번째 제출 결과는 is_error=True 였어야 함
    tr = fake.calls[2]["messages"][-1]["content"][0]
    assert tr["is_error"] is True and "빈칸" in tr["content"][0]["text"]
    assert fake.calls[0]["model"] == paths.MODEL and fake.calls[0]["fallbacks"] == "default"
    assert Path(job.xlsx).name == "2-3_q1_무료소스정리표_성민.xlsx"
    rpt = Path(report.write_report(job)).read_text(encoding="utf-8")
    assert "성민이 지금 할 일" in rpt and "즐겨찾기 캡처" in rpt


def test_plan_mode():
    tp = str(KIT / "templates" / "3-1-1_template.xlsx")
    cm = template.analyze(tp)
    plan = {"items": [{"category": "카드뉴스", "url": "https://www.instagram.com/p/X1/", "why": "최근·랜딩 있음"}],
            "accounts": ["https://www.instagram.com/acct/"], "extra_pages": ["https://linktr.ee/acct"], "notes": ""}
    fake = FakeClient([_msg([_tool(1, "save_url_plan", plan)], "tool_use"), _msg([NS(type="text", text="저장")], "end_turn")])
    job = agent.Job(quest_id="3-1-1", template=tp, out_dir=Path(tempfile.mkdtemp()), cm=cm, today="2026-11-07",
                    store=metrics.Store.load(Path(tempfile.mkdtemp()) / "none.json"))
    agent.run(job, prompts.PLAN_ROLE, "brief", [], client=fake, verbose=False, mode="plan")
    assert job.url_plan == plan
    names = {t.get("name") for t in fake.calls[0]["tools"]}
    assert "save_url_plan" in names and "submit_homework" not in names


def test_collector_js_parses():
    import re, shutil, subprocess
    if not shutil.which("node"):
        return
    src = (KIT / "collector" / "collector.py").read_text(encoding="utf-8")
    for name, body in re.findall(r'(JS_[A-Z_]+) = r"""(.*?)"""', src, re.S):
        r = subprocess.run(["node", "-e", f"const f = ({body}); if (typeof f !== 'function') throw 1;"], capture_output=True)
        assert r.returncode == 0, name


def test_register_new_quest():
    """새 퀘스트 등록이 quests.json·학습 파일에 반영되는지 (원본은 복구)."""
    bak_q = paths.QUESTS.read_text(encoding="utf-8")
    learned_existed = paths.LEARNED.exists()
    bak_l = paths.LEARNED.read_text(encoding="utf-8") if learned_existed else None
    tp = str(KIT / "templates" / "2-3_q1_template.xlsx")
    try:
        cm = template.analyze(tp)
        job = agent.Job(quest_id="9-9-q1", template=tp, out_dir=Path(tempfile.mkdtemp()), cm=cm, today="2026-11-04")
        job.submission = {"quest_title": "테스트", "guide_analysis": "목적: 테스트", "learning_points": ["a"]}
        report.register_quest(job, tp, ["g.png"])
        assert paths.find_quest("9-9-q1")["title"] == "테스트"
        assert "9-9-q1" in paths.LEARNED.read_text(encoding="utf-8")
    finally:
        paths.QUESTS.write_text(bak_q, encoding="utf-8")
        if learned_existed:
            paths.LEARNED.write_text(bak_l, encoding="utf-8")
        elif paths.LEARNED.exists():
            paths.LEARNED.unlink()
        p = KIT / "templates" / "9-9_q1_template.xlsx"
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
