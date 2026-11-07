"""성민용 학습 보고서(보고서.md) + 새 퀘스트 등록·학습 내용 누적."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from .paths import LEARNED, TEMPLATES, USER_NAME, load_quests, save_quests, norm_id
from .writer import read_cells

SUBMIT_STEPS = "COSY 앱 → 퀘스트 카드 → 업로드 탭 → 파일 첨부 → '퀘스트 제출하기' → 확인창"


def write_report(job) -> str:
    s = job.submission or {}
    rep = job.report
    lines = [f"# {job.quest_id} {s.get('quest_title', '')} — 숙제 보고서",
             f"작성일 {job.today} · 이름 {USER_NAME} · 결과 파일: `{Path(job.xlsx).name if job.xlsx else '없음'}`", ""]
    lines += ["## 0. 결론", f"- 검증: {'통과' if rep and rep.ok else '실패'} ({rep.filled}/{rep.total}칸)" if rep else "- 제출 없음",
              f"- 제출 횟수(자체 수정 포함): {job.submits}회", ""]
    lines += ["## 1. 성민이 지금 할 일"]
    for i, t in enumerate(s.get("todo_for_user", []), 1):
        lines.append(f"{i}. {t}")
    lines.append(f"{len(s.get('todo_for_user', [])) + 1}. 결과 xlsx 확인 후 제출: {SUBMIT_STEPS}")
    lines += ["", "## 2. 가이드 분석", s.get("guide_analysis", ""), ""]
    lines += ["## 3. 이번 숙제에서 배울 점"] + [f"- {p}" for p in s.get("learning_points", [])] + [""]
    if job.xlsx:
        cells = read_cells(job.xlsx, job.cm.sheet)
        lines += ["## 4. 작성 내용 (칸별)", "| 칸 | 항목 | 내용 |", "|---|---|---|"]
        import re
        for c in job.cm.fillable:
            r = int(re.sub(r"[A-Z]+", "", c))
            col = re.match(r"[A-Z]+", c).group()
            label = (job.cm.row_labels.get(r) or job.cm.row_labels.get(str(r)) or "")
            head = job.cm.headers.get(col, "")
            item = " · ".join(x for x in (label.split(" (예시")[0], head.split("\n")[0]) if x)[:40]
            v = str(cells.get(c, "")).replace("\n", "<br>").replace("|", "／")
            lines.append(f"| {c} | {item} | {v} |")
        lines.append("")
    lines += ["## 5. 출처·실측 기록", "| 항목 | 주소 | 확인 내용 |", "|---|---|---|"]
    for src in s.get("sources", []):
        lines.append(f"| {src['item']} | {src['url']} | {src['checked']} |")
    lines += ["", "## 6. 미확인·주의"] + [f"- {u}" for u in s.get("unverified", [])]
    if rep:
        lines += [f"- [검증 오류] {e}" for e in rep.errors] + [f"- [검증 주의] {w}" for w in rep.warnings]
    if getattr(job, "store", None) is not None and job.store.missing:
        lines += ["", "## 6-1. 실측 수집 필요 (추정하지 않음)",
                  f"성민 PC: `python collector/collector.py collect collector/missing_urls_{job.quest_id}.txt collector/results.json` 후 run 재실행"]
        lines += [f"- {u} — {why}" for u, why in job.store.missing.values()]
    if job.pngs:
        lines += ["", "## 7. 렌더 미리보기"] + [f"![page]({Path(p).relative_to(job.out_dir).as_posix()})" for p in job.pngs]
    out = job.out_dir / "보고서.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


def register_quest(job, template_src: str, guides: list[str]) -> None:
    """새 퀘스트면 quests.json·templates·학습 파일에 등록, 기존이면 상태만 갱신."""
    data = load_quests()
    key = norm_id(job.quest_id)
    s = job.submission or {}
    entry = next((q for q in data["quests"] if norm_id(q["id"]) == key), None)
    if entry is None:
        tpl_name = f"{job.quest_id.replace('-q', '_q')}_template.xlsx"
        dst = TEMPLATES / tpl_name
        if not dst.exists():
            shutil.copy(template_src, dst)
        cm = job.cm
        entry = {
            "id": job.quest_id, "title": s.get("quest_title", ""), "status": "done_waiting_submit",
            "template": f"templates/{tpl_name}", "sheet": cm.sheet,
            "name_cell": cm.name_cell, "date_cell": cm.date_cell,
            "data_rows": [cm.data_rows[0], cm.data_rows[-1]] if cm.data_rows else [],
            "columns": {k: v for k, v in cm.headers.items() if k not in cm.label_cols},
            "final": {"cells": cm.final_cells, "ask": cm.final_label},
            "fixed": cm.prefilled and {k: str(v) for k, v in cm.prefilled.items()} or {},
            "guides": [Path(g).name for g in guides],
            "output": Path(job.xlsx).name if job.xlsx else None,
            "learned_at": job.today,
        }
        data["quests"].append(entry)
    elif job.report and job.report.ok and entry.get("status") not in ("submitted",):
        entry["status"] = "done_waiting_submit"
        entry["output"] = Path(job.xlsx).name
    save_quests(data)

    if s.get("guide_analysis"):
        LEARNED.parent.mkdir(parents=True, exist_ok=True)
        head = "" if LEARNED.exists() else "# 퀘스트 자동 학습 기록 (숙제 프로그램이 가이드를 분석할 때마다 누적)\n"
        with open(LEARNED, "a", encoding="utf-8") as f:
            f.write(f"{head}\n## {job.quest_id} {s.get('quest_title', '')} (학습 {dt.date.today()})\n")
            f.write(s["guide_analysis"].strip() + "\n")
            if s.get("learning_points"):
                f.write("- 핵심: " + " / ".join(s["learning_points"]) + "\n")
