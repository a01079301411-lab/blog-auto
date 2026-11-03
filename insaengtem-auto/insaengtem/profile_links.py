"""인스타 프로필 링크(최대 5개) 관리.

인스타 프로필 링크는 API·웹으로 수정할 수 없고 **모바일 앱에서만** 바꿀 수 있다.
→ 프로그램은 '이번 주에 걸어야 할 링크 5개(제목·주소·순서)'를 계산해 보여주고,
  바뀌면 알림을 보내며, 사용자가 앱에서 붙여넣고 [등록 완료]를 누르면 기록한다.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import db
from .catalog import load_facts, load_links, usp_of
from .config import STATE, fmt_when, now, settings

APPLIED = STATE / "profile_links.json"


def title_for(key: str) -> str:
    from .generate import short_name
    try:
        f = load_facts(key)
        if f.get("link_title"):
            return f["link_title"][:30]
        return f"{short_name(f)} {usp_of(f).best.text}"[:30]
    except SystemExit:
        return key


def plan(days: int = 7) -> dict:
    """앞으로 N일 인스타 게시 순서대로 제품을 모아 최대 5개. 이미 게시된 최근 3일치도 포함(링크 유지)."""
    mx = settings()["instagram"]["profile_link_max"]
    start = fmt_when(now() - timedelta(days=3))
    end = fmt_when(now() + timedelta(days=days))
    with db.connect() as con:
        rows = con.execute(
            "SELECT product, MIN(when_kst) AS first FROM posts WHERE platform='instagram' AND product IS NOT NULL "
            "AND when_kst BETWEEN ? AND ? AND status NOT IN ('skipped') GROUP BY product ORDER BY first", (start, end)).fetchall()
    keys = [r["product"] for r in rows]
    links = load_links()
    items = [{"key": k, "title": title_for(k), "url": links.get(k), "first": r["first"]}
             for k, r in zip(keys, rows)]
    over = items[mx:]
    items = items[:mx]
    applied = json.loads(APPLIED.read_text(encoding="utf-8")) if APPLIED.exists() else {"keys": []}
    changed = [i["key"] for i in items] != applied.get("keys", [])
    notes = []
    if over:
        notes.append(f"이번 주 인스타 제품 {len(items) + len(over)}개 > 프로필 링크 {mx}개: "
                     f"{', '.join(o['key'] for o in over)} 는 링크가 안 걸림 → 링크 모음 페이지 필요")
    missing = [i["key"] for i in items if not i["url"]]
    if missing:
        notes.append(f"제휴 링크 미등록: {', '.join(missing)}")
    return {"items": items, "changed": changed, "applied_at": applied.get("at"), "notes": notes}


def mark_applied(keys: list[str]) -> None:
    APPLIED.parent.mkdir(parents=True, exist_ok=True)
    APPLIED.write_text(json.dumps({"keys": keys, "at": fmt_when(now())}, ensure_ascii=False), encoding="utf-8")


def text_for_app(p: dict) -> str:
    out = ["[인스타 앱 → 프로필 편집 → 링크 → 외부 링크 추가] 아래 순서대로", ""]
    for i, it in enumerate(p["items"], 1):
        out += [f"{i}. 제목: {it['title']}", f"   URL: {it['url'] or '(제휴 링크 미등록)'}"]
    out += [""] + [f"⚠️ {n}" for n in p["notes"]]
    return "\n".join(out)
