"""API·네트워크 없이 돌리는 테스트: python -m pytest tests 또는 python tests/test_offline.py"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from cosyhw import template, writer, checks, agent, prompts, report, paths, collectors  # noqa: E402
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


def test_parsers():
    assert collectors.youtube_id("https://youtu.be/znj8v8XY5js") == "znj8v8XY5js"
    assert collectors.youtube_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert collectors.ig_shortcode_to_id("B") == "1"
    html = 'var ytInitialPlayerResponse = {"videoDetails":{"viewCount":"961000"}};var x'
    assert collectors._json_after(html, "ytInitialPlayerResponse")["videoDetails"]["viewCount"] == "961000"
    assert paths.norm_id("2-1_q1") == "2-1-q1" and paths.norm_id("2-4퀘스트2") == "2-4-q2"


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
        _msg([NS(type="thinking", thinking="가이드 분석"), _tool(1, "compare_vs_recent", {"target": 100000, "recent": [10000, 20000]})], "tool_use"),
        _msg([_tool(2, "submit_homework", {**meta, "cells": full[:-1]})], "tool_use"),       # 한 칸 빠짐 → 오류
        _msg([_tool(3, "submit_homework", {**meta, "cells": full})], "tool_use"),            # 통과
        _msg([NS(type="text", text="완료")], "end_turn"),
    ]
    fake = FakeClient(script)
    out = Path(tempfile.mkdtemp())
    job = agent.Job(quest_id="2-3-q1", template=tp, out_dir=out, cm=cm, today="2026-11-04")
    agent.run(job, prompts.system_prompt(), "brief", [], client=fake, verbose=False)
    assert job.submits == 2 and job.report.ok
    # 두 번째 제출 결과는 is_error=True 였어야 함
    tr = fake.calls[2]["messages"][-1]["content"][0]
    assert tr["is_error"] is True and "빈칸" in tr["content"][0]["text"]
    assert fake.calls[0]["model"] == paths.MODEL and fake.calls[0]["fallbacks"] == "default"
    assert Path(job.xlsx).name == "2-3_q1_무료소스정리표_성민.xlsx"
    rpt = Path(report.write_report(job)).read_text(encoding="utf-8")
    assert "성민이 지금 할 일" in rpt and "즐겨찾기 캡처" in rpt


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
