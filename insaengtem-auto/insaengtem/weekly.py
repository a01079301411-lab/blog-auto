"""주간 성과 → 다음 주 반영 규칙(docs/DESIGN.md 5-8)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from . import db
from .config import OUT, fmt_when, now, settings
from .schedule import WEIGHTS


def evaluate(days: int = 7) -> dict:
    r = settings()["weekly_rules"]
    since = fmt_when(now() - timedelta(days=days))
    with db.connect() as con:
        rows = [dict(x) for x in db.latest_metrics(con) if x["when_kst"] >= since and x["status"] in ("published", "external")]
        fol = {p: con.execute("SELECT followers FROM account_metrics WHERE platform=? ORDER BY id DESC LIMIT 1", (p,)).fetchone()
               for p in ("instagram", "threads")}
    by_var = defaultdict(list)
    by_prod = defaultdict(list)
    for x in rows:
        if x["variant"] and x["views"] is not None:
            by_var[(x["platform"], x["variant"])].append(x["views"])
            by_prod[x["product"]].append(x["views"])
    var_avg = {f"{p}:{v}": round(mean(vs), 1) for (p, v), vs in by_var.items()}
    actions = []
    weights = {"variant": {}, "product": {}}
    ig = {v: mean(vs) for (p, v), vs in by_var.items() if p == "instagram"}
    if ig:
        win = max(ig, key=ig.get)
        weights["variant"] = {v: (r["winner_weight"] if v == win else 1.0) for v in settings()["variants"]}
        actions.append(f"인스타 승자 버전 {win} (평균 조회 {ig[win]:.0f}) → 다음 주 비중 {r['winner_weight']}배")
    if by_prod:
        top = max(mean(v) for v in by_prod.values()) or 1
        weights["product"] = {k: round(0.5 + mean(v) / top, 2) for k, v in by_prod.items()}
    for x in rows:
        if x["platform"] == "instagram" and x["views"] is not None:
            if (x["saves"] or 0) + (x["shares"] or 0) < r["min_saves_shares_per_reel"]:
                actions.append(f"#{x['id']} {x['product']} {x['variant']}: 저장·공유 0 → 훅(커버 big/hook) 교체")
    pv = sum((x["profile_visits"] or 0) for x in rows if x["platform"] == "instagram")
    if rows and pv < r["profile_visits_per_week"]:
        actions.append(f"프로필 방문 주 {pv}회 < {r['profile_visits_per_week']} → 커버 문구 교체(질문형/숫자형 교차)")
    f_ig = fol["instagram"]["followers"] if fol["instagram"] else None
    if f_ig is not None and f_ig < r["followers_14d"]:
        actions.append(f"인스타 팔로워 {f_ig} < 14일 목표 {r['followers_14d']} → 14일차 도달 시 B안(주 1회 30분 손 촬영) 재검토")
    if not rows:
        actions.append("성과 데이터 없음 → `sync` 후 `insights` 실행 필요")
    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    if weights["variant"] or weights["product"]:
        WEIGHTS.write_text(json.dumps(weights, ensure_ascii=False, indent=1), encoding="utf-8")
    res = {"period_from": since, "posts": len(rows), "variant_avg_views": var_avg, "weights": weights, "actions": actions,
           "followers": {p: (f["followers"] if f else None) for p, f in fol.items()}}
    OUT.mkdir(exist_ok=True)
    (OUT / f"weekly_{now():%Y-%m-%d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
