"""주간 일정 생성·검증.

규칙(config/settings.json)
- 스레드 4시간 간격 08·12·16·20·24시(자정 슬롯은 무광고 공감글), 인스타 12:30·18:30·21:30
- 같은 제품은 플랫폼별 하루 1회
- 같은 (제품, 버전) 영상은 같은 플랫폼에서 14일 내 재사용 금지 (원본성)
- 버전·제품 가중치는 data/state/weights.json (weekly.py 가 갱신)
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .catalog import available
from .config import OUT, PRODUCTS, SCHEDULES, STATE, settings, tz
from .qa import Issue

WEIGHTS = STATE / "weights.json"
REUSE_DAYS = 14


def load_weights() -> dict:
    if WEIGHTS.exists():
        return json.loads(WEIGHTS.read_text(encoding="utf-8"))
    return {"variant": {}, "product": {}}


def video_path(key: str, v: str) -> str:
    return f"out/{key}_{v}/insaengtem_{key}_{v}.mp4"


def _slot_dt(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    d = datetime(day.year, day.month, day.day, tzinfo=tz())
    if h == 0 and m == 0:          # '00:00' = 그날의 24시 → 다음날 0시
        d += timedelta(days=1)
    return d.replace(hour=h, minute=m)


def _posts_file(key: str) -> dict:
    p = PRODUCTS / f"{key}.posts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def recent_usage(history: list[dict], platform: str, ref: datetime) -> set[tuple[str, str]]:
    out = set()
    for h in history:
        if h["platform"] != platform or not h.get("product"):
            continue
        t = datetime.strptime(h["when_kst"], "%Y-%m-%d %H:%M").replace(tzinfo=tz())
        if ref - timedelta(days=REUSE_DAYS) <= t < ref:
            out.add((h["product"], h["variant"]))
    return out


def build_week(start: date, days: int = 7, products: list[str] | None = None, history: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    s = settings()
    w = load_weights()
    keys = products or [c["key"] for c in available()]
    history = history or []
    variants = s["variants"]
    start_dt = datetime(start.year, start.month, start.day, tzinfo=tz())
    plan: list[dict] = []
    notes: list[str] = []
    week = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
    empathy_pool: list[str] = []
    for k in keys:
        empathy_pool += _posts_file(k).get("empathy", [])
    from .generate import EMPATHY_FALLBACK
    used_texts = {h.get("text") for h in history}
    empathy_pool = [e for e in dict.fromkeys(empathy_pool + EMPATHY_FALLBACK) if e not in used_texts]

    for platform in ("instagram", "threads"):
        cfg = s[platform]
        used = recent_usage(history, platform, start_dt)
        pool = [(k, v) for k in keys for v in variants if (k, v) not in used]
        per_product = Counter()
        shortage = 0
        for i in range(days):
            day = start + timedelta(days=i)
            today = set()
            for slot in cfg["slots"]:
                when = _slot_dt(day, slot)
                if platform == "threads" and slot in cfg.get("text_only_slots", []):
                    if empathy_pool:
                        plan.append({"platform": "threads", "when_kst": when.strftime("%Y-%m-%d %H:%M"), "kind": "text",
                                     "product": None, "variant": None, "video": None, "text": empathy_pool.pop(0),
                                     "reply": None, "status": "draft", "source": "schedule", "week": week})
                    else:
                        notes.append(f"{when:%m/%d %H:%M} 스레드 공감글 소진 → generate 로 empathy 추가 필요")
                    continue
                cands = [(k, v) for (k, v) in pool if k not in today]
                if not cands:
                    shortage += 1
                    continue

                def score(kv):
                    k, v = kv
                    return (w["variant"].get(v, 1.0) * w["product"].get(k, 1.0) / (1 + per_product[k]),
                            -variants.index(v))
                k, v = max(cands, key=score)
                pool.remove((k, v))
                today.add(k)
                per_product[k] += 1
                pf = _posts_file(k)
                item = {"platform": platform, "when_kst": when.strftime("%Y-%m-%d %H:%M"), "kind": "video",
                        "product": k, "variant": v, "video": video_path(k, v), "status": "draft",
                        "source": "schedule", "week": week}
                if platform == "instagram":
                    item["text"] = pf.get("instagram", {}).get(v)
                    item["reply"] = None
                else:
                    t = pf.get("threads", {}).get(v, {})
                    item["text"], item["reply"] = t.get("text"), t.get("reply")
                if not item["text"]:
                    notes.append(f"{k} {v}: posts.json 원고 없음 → `generate {k}` 먼저")
                plan.append(item)
        if shortage:
            notes.append(f"{platform}: 빈 슬롯 {shortage}개 — 영상 부족(제품 {len(keys)}개×{len(variants)}버전, 14일 재사용 금지). "
                         f"제품 추가 또는 v4/v5 제작 필요")
    plan.sort(key=lambda p: (p["when_kst"], p["platform"]))
    return plan, notes


def validate(plan: list[dict], history: list[dict] | None = None) -> list[Issue]:
    s = settings()
    out: list[Issue] = []
    per_day = defaultdict(Counter)
    seen = defaultdict(list)
    for p in plan:
        if not p.get("product"):
            continue
        d = p["when_kst"][:10]
        per_day[(p["platform"], d)][p["product"]] += 1
        seen[(p["platform"], p["product"], p.get("variant"))].append(p["when_kst"])
        hh = p["when_kst"][11:]
        if hh not in s[p["platform"]]["slots"]:
            out.append(Issue("warn", "SLOT", f"규칙 외 시간 {hh}", f"{p['platform']} {p['when_kst']}"))
        if p.get("video") and not (OUT.parent / p["video"]).exists():
            out.append(Issue("warn", "VIDEO_NOT_RENDERED", p["video"], f"{p['platform']} {p['when_kst']}"))
    mx = s["max_same_product_per_platform_per_day"]
    for (pl, d), c in per_day.items():
        for k, n in c.items():
            if n > mx:
                out.append(Issue("error", "SAME_PRODUCT_DAY", f"{k} 하루 {n}회 (규칙 {mx}회)", f"{pl} {d}"))
    for (pl, k, v), whens in seen.items():
        if len(whens) > 1:
            out.append(Issue("error", "REUPLOAD", f"{k} {v} 같은 영상 {len(whens)}회: {', '.join(whens)}", pl))
    return out


def load_week1() -> list[dict]:
    out = []
    for platform, fn in (("threads", "threads_week1.json"), ("instagram", "instagram_week1.json")):
        for p in json.loads((SCHEDULES / fn).read_text(encoding="utf-8")):
            out.append({"platform": platform, "when_kst": p["when"], "product": p.get("product"), "variant": p.get("variant"),
                        "kind": "video" if p.get("video") else "text", "video": p.get("video"),
                        "text": p.get("text") or p.get("caption"), "reply": p.get("reply"),
                        "status": "external", "source": "week1(수동 예약)", "week": "2026-W45"})
    return out


def save_plan_json(plan: list[dict], name: str) -> str:
    SCHEDULES.mkdir(parents=True, exist_ok=True)
    p = SCHEDULES / name
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


def select_week_products(history: list[dict] | None = None, n: int | None = None) -> list[str]:
    """이번 주 영상으로 만들 제품 n개 선택: 판매중·링크 있음·facts 있음.
    우선순위 = 고정(pinned) > 최근 14일 영상 없음 > 성과 가중치 > 신규 등록순."""
    from .catalog import facts_path, load_catalog, load_links
    n = n or settings().get("shop", {}).get("video_products_per_week", 7)
    links = load_links()
    w = load_weights()["product"]
    recent = {h["product"] for h in (history or []) if h.get("product")
              and h["when_kst"] >= (datetime.now(tz()) - timedelta(days=14)).strftime("%Y-%m-%d")}
    cands = [c for c in load_catalog() if c.get("available") and not c.get("hidden") and c["key"] in links
             and facts_path(c["key"]).exists()]
    cands.sort(key=lambda c: (not c.get("pinned"), c["key"] in recent, -w.get(c["key"], 1.0), -(c.get("no") or 0)))
    return [c["key"] for c in cands[:n]]
