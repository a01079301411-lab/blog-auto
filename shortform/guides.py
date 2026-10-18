"""숏폼 '영상 종류' 가이드: 영상마다 좋은 숏폼이 되는 장면과 제목 말투가 다르다.

- 강의·인터뷰(꼴통사장 등): 강한 주장, 숫자, 반전 있는 한마디
- 내 채널 브이로그(여친 있는 유부남): 웃기거나 뭉클한 순간, 딸들 반응, 공감되는 아빠 일상
- 이사 현장: 꿀팁, 정리·포장 과정, 전후 비교, 현장 사람만 아는 이야기
- 코시 제품(커머스): 불편 → 제품 사용 → 달라진 모습, 실사용 장면
- 직접 입력: 영상 설명 칸에 적은 대로

guides.json 파일을 프로그램 폴더에 두면 같은 모양으로 가이드를 더 넣을 수 있다.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_FILE = os.path.join(ROOT, "guides.json")

BUILTIN: dict[str, dict] = {
    "lecture": {
        "name": "강의·인터뷰 (꼴통사장 등)",
        "context": "꼴통사장 권기준 대표의 사업 강의. 창업, 매출, 사장 마인드, 크리에이터로 돈 버는 법",
        "speaker": "권기준 / 꼴통사장 대표",
        "focus": (
            "This is a talk, lecture or interview. Pick moments with a provocative claim, a blunt "
            "opinion, a specific number (money, revenue, years), a common mistake, or a story "
            "with a turn, that end in a clear lesson or punchline."),
        "title": "도발적인 주장이나 숫자로 시작하는 헤드라인. 예: 사장님 속터지는\\n{진상 직원}의 한마디",
    },
    "vlog": {
        "name": "내 채널 브이로그 (여친 있는 유부남)",
        "context": ("'여친 있는 유부남' 채널. 여친은 딸 셋, 본처는 아내. 5인 가족 아빠의 딸 데이트, "
                    "아내와 데이트, 크로스핏 등 취미, 이사업체 사장 일상 브이로그"),
        "speaker": "",
        "focus": (
            "This is a family / daily-life vlog, not a lecture. Do NOT look for business lessons "
            "or numbers. Pick moments viewers would rewatch and share: something funny (a kid's "
            "unexpected line, a dad joke landing or failing), something heart-warming (a hug, a "
            "sincere sentence from a daughter or wife), a relatable parenting or marriage moment, "
            "or a small win in the dad's hobby or work. The first 2 seconds must already show the "
            "situation or the reaction. Keep the channel concept: the daughters are the "
            "'girlfriends' and the wife is the 'main wife'. Never pick moments that expose a "
            "child's school, address or anything embarrassing for the child."),
        "title": ("세계관을 살린 위트 있는 반말 제목. 예: 여친이 셋인 유부남의\\n{현실 데이트}, "
                  "첫째 여친의\\n{팩트 폭행}"),
    },
    "moving": {
        "name": "이사 현장 (사장님 일상)",
        "context": "대구 이사업체 사장님의 현장 영상. 포장이사, 보관이사, 정리 과정과 현장 꿀팁",
        "speaker": "이사업체 사장님",
        "focus": (
            "This is footage from a moving company at work. Pick satisfying process moments "
            "(packing, protecting furniture, a tight staircase, loading a truck perfectly), "
            "practical tips a customer can use, before/after contrasts, and lines only a "
            "professional mover would say. Avoid moments that show a customer's face, address "
            "or private belongings in detail."),
        "title": "꿀팁·반전 제목. 예: 이사할 때 {이것} 모르면\\n돈 두 번 냅니다",
    },
    "commerce": {
        "name": "코시 제품 (커머스)",
        "context": "코시(COSY) 제품을 실제로 써 보는 영상. 유료광고 포함",
        "speaker": "",
        "focus": (
            "This video promotes a product (paid advertisement). Pick moments that follow "
            "problem -> using the product -> visible change, real usage scenes, honest reactions, "
            "and clear before/after. Do not exaggerate effects beyond what is shown. The caption "
            "must start with '#광고' and mention it is a paid partnership."),
        "title": "문제 → 해결이 보이는 제목. 예: 매일 아프던 손목\\n{이걸로} 끝냈습니다",
    },
    "custom": {
        "name": "직접 입력 (영상 설명대로)",
        "context": "",
        "speaker": "",
        "focus": "",
        "title": "",
    },
}


def load() -> dict[str, dict]:
    """기본 가이드 + guides.json에 사용자가 넣은 가이드."""
    guides = {k: dict(v) for k, v in BUILTIN.items()}
    try:
        with open(USER_FILE, encoding="utf-8-sig") as f:
            for key, g in json.load(f).items():
                guides[key] = {**guides.get(key, BUILTIN["custom"]), **g}
    except (OSError, ValueError):
        pass
    return guides


def get(key: str | None) -> dict:
    guides = load()
    return guides.get(key or "lecture", guides["lecture"])


def brief(key: str | None) -> str:
    """Claude에게 줄 가이드 글 (하이라이트 고르기·검증·제목 쓰기에 쓴다)."""
    g = get(key)
    lines = [f"Video type: {g['name']}"]
    if g.get("focus"):
        lines.append(g["focus"])
    if g.get("title"):
        lines.append(f"Title style for this video type (Korean): {g['title']}")
    return "\n".join(lines)
