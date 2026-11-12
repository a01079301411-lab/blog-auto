"""data/topics.md에서 이번 글의 주제·제목 유형·구조 번호를 고른다.

- 최근 30일 안에 쓴 주제는 건너뛴다.
- 파일 안의 '비율: 실내보관이사 60% / ...' 대로 섹션을 고른다.
- 제목 유형, 도입 방식, 구조 번호는 바로 전 글과 겹치지 않게 돌려쓴다.
"""
import random
import re

import history
import season
from config import DATA_DIR, NAVER_CATEGORY

# 초사고 제목 공식 (prompts/moving_post.md 3번과 이름이 같아야 한다)
TITLE_TYPES = ["자아 자극형", "손실 경고형", "호기심 가림형", "사건 폭로형", "가격 공개형", "권위 부여형", "숫자 목록형"]
HOOK_TYPES = ["현장 장면형", "질문형", "숫자 제시형", "흔한 오해 지적형", "결론 먼저형", "고객 목소리형"]
VARIANTS = [1, 2, 3, 4]
RECENT_DAYS = 30
KEYWORD_GAP_DAYS = 5  # 같은 메인 키워드는 이 기간 안에 다시 쓰지 않는다 (다른 키워드가 있으면)


def load_topics(path=DATA_DIR / "topics.md"):
    """표 한 줄 = 주제 하나. [{'section', 'topic', 'keyword', 'question', 'category'}, ...] 와 섹션별 비율을 돌려준다."""
    text = path.read_text(encoding="utf-8")
    ratios = {name: int(pct) for name, pct in re.findall(r"(\S+)\s+(\d+)%", text)}

    topics, section = [], ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 3:
            continue
        if cells[0] == "주제" or set(cells[0]) <= set("-: "):
            continue  # 표 머리줄, 구분줄
        category = cells[3] if len(cells) > 3 else ""
        subs = [w.strip() for w in cells[4].split(",") if w.strip()] if len(cells) > 4 else []
        topics.append({
            "section": section, "topic": cells[0], "keyword": cells[1],
            "question": cells[2], "category": category or NAVER_CATEGORY, "sub_keywords": subs,
        })
    return topics, ratios


def _weight(section, ratios):
    for name, pct in ratios.items():
        if name in section:
            return pct
    return 10


def _rotate(options, last):
    return random.choice([o for o in options if o != last] or options)


def pick(forced=None):
    """이번 글 정보를 고른다. forced에 글자를 주면 그 글자가 들어간 주제를 쓴다."""
    topics, ratios = load_topics()
    records = history.load()

    if forced:
        matches = [t for t in topics if forced in t["topic"] or forced in t["keyword"]]
        if not matches:
            raise SystemExit(f"'{forced}'가 들어간 주제를 data/topics.md에서 찾지 못했어요.")
        chosen = matches[0]
    else:
        recent = {r.get("topic") for r in history.within_days(records, RECENT_DAYS)}
        # 지금 계절과 안 맞는 주제(10월의 '장마철 보관이사' 같은)는 고르지 않는다
        topics = [t for t in topics if season.topic_in_season(t)] or topics
        fresh = [t for t in topics if t["topic"] not in recent]
        # 같은 메인 키워드가 며칠 연달아 나오지 않게 (다른 키워드가 남아 있으면 그쪽부터)
        recent_kw = {r.get("keyword") for r in history.within_days(records, KEYWORD_GAP_DAYS)}
        fresh = [t for t in fresh if t["keyword"] not in recent_kw] or fresh
        if not fresh:
            # 전부 최근에 썼으면 가장 오래전에 쓴 주제부터
            last_used = {r.get("topic"): r["date"] for r in records}
            fresh = sorted(topics, key=lambda t: last_used.get(t["topic"], ""))[:3]
        sections = sorted({t["section"] for t in fresh})
        section = random.choices(sections, weights=[_weight(s, ratios) for s in sections])[0]
        chosen = random.choice([t for t in fresh if t["section"] == section])

    last = records[-1] if records else {}
    return {
        **chosen,
        "title_type": _rotate(TITLE_TYPES, last.get("title_type")),
        "hook_type": _rotate(HOOK_TYPES, last.get("hook_type")),
        "variant": _rotate(VARIANTS, last.get("variant")),
    }
