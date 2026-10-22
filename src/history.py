"""발행 기록(data/history.json) 읽기·쓰기. 중복 주제·비슷한 제목·하루 개수 제한에 쓴다."""
import json
from datetime import datetime, timedelta

from config import HISTORY_FILE


def load():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def add(entry):
    records = load()
    records.append({"date": datetime.now().strftime("%Y-%m-%d %H:%M"), **entry})
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _when(record):
    return datetime.strptime(record["date"], "%Y-%m-%d %H:%M")


def within_days(records, days):
    since = datetime.now() - timedelta(days=days)
    return [r for r in records if _when(r) >= since]


def count_today(records):
    today = datetime.now().date()
    return sum(1 for r in records if _when(r).date() == today)
