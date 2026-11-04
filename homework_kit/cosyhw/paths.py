"""경로·공통 설정."""
from __future__ import annotations

import json
import re
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent          # homework_kit/
SPEC = KIT / "HOMEWORK_SPEC.md"
QUESTS = KIT / "quests.json"
SUBMITTED = KIT / "submitted" / "submitted_cells.json"
TEMPLATES = KIT / "templates"
DOCS = KIT / "docs"
LEARNED = DOCS / "퀘스트_자동학습.md"                  # 새 퀘스트 가이드 분석이 누적되는 파일
OUTPUT = KIT / "output"

MODEL = "claude-opus-5-5"
USER_NAME = "성민"


def load_quests() -> dict:
    return json.loads(QUESTS.read_text(encoding="utf-8"))


def save_quests(data: dict) -> None:
    QUESTS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def norm_id(qid: str) -> str:
    """'2-1_q1', '2-1-q1', '2-1 q1', '2-1퀘스트1' → '2-1-q1'. '1-4' 그대로."""
    s = qid.strip().lower().replace("퀘스트", "q").replace(" ", "-").replace("_", "-")
    s = re.sub(r"-+", "-", s)
    s = re.sub(r"(\d)q(\d)", r"\1-q\2", s)
    return s


def find_quest(qid: str) -> dict | None:
    key = norm_id(qid)
    for q in load_quests()["quests"]:
        if norm_id(q["id"]) == key:
            return q
    return None


def forbidden_phrases() -> list[str]:
    return load_quests()["common"].get("forbidden_phrases", [])
