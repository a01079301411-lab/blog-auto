"""관리 대시보드(정적 HTML): out/dashboard.html — 일정·상태·성과·버전 비교·이번 주 액션."""
from __future__ import annotations

import html
import json
from collections import Counter

from . import db
from .config import OUT, now


def build() -> str:
    with db.connect() as con:
        rows = [dict(r) for r in db.latest_metrics(con)]
        unanswered = con.execute("SELECT COUNT(*) FROM replies_seen WHERE answered=0").fetchone()[0]
    st = Counter(r["status"] for r in rows)
    today = now().strftime("%Y-%m-%d")
    upcoming = [r for r in rows if r["when_kst"] >= today][:30]
    pub = [r for r in rows if r["views"] is not None]
    weekly = sorted(OUT.glob("weekly_*.json"))
    actions = json.loads(weekly[-1].read_text(encoding="utf-8"))["actions"] if weekly else ["weekly 아직 실행 안 함"]

    def tr(r, cols):
        return "<tr>" + "".join(f"<td>{html.escape(str(r.get(c) if r.get(c) is not None else '–'))}</td>" for c in cols) + "</tr>"

    up_cols = ["id", "when_kst", "platform", "product", "variant", "status", "error"]
    m_cols = ["when_kst", "platform", "product", "variant", "views", "reach", "likes", "saves", "shares", "replies", "profile_visits", "follows"]
    var = Counter()
    cnt = Counter()
    for r in pub:
        if r["variant"]:
            var[(r["platform"], r["variant"])] += r["views"] or 0
            cnt[(r["platform"], r["variant"])] += 1
    bars = ""
    mx = max([var[k] / cnt[k] for k in var] or [1]) or 1
    for k in sorted(var):
        avg = var[k] / cnt[k]
        bars += (f"<div class=bar><span>{k[0]} {k[1]}</span><i style='width:{avg / mx * 100:.0f}%'></i>"
                 f"<b>{avg:.0f}</b></div>")
    doc = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>인생템연구소 관리</title><style>
:root{{--bg:#f6f4f0;--card:#fff;--fg:#222;--sub:#666;--acc:#ff6b1a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16130f;--card:#221d18;--fg:#eee;--sub:#aaa}}}}
body{{background:var(--bg);color:var(--fg);font-family:system-ui,'Malgun Gothic';margin:0;padding:16px}}
.k{{display:flex;flex-wrap:wrap;gap:10px}}.k div{{background:var(--card);border-radius:10px;padding:10px 14px;min-width:110px}}
.k b{{font-size:22px;display:block}}section{{background:var(--card);border-radius:12px;padding:12px;margin:14px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:5px 8px;border-bottom:1px solid #8883;text-align:left;white-space:nowrap}}
.bar{{display:flex;align-items:center;gap:8px;margin:4px 0}}.bar span{{width:120px}}.bar i{{height:14px;background:var(--acc);border-radius:7px}}
</style><h1>인생템연구소 관리 · {now():%Y-%m-%d %H:%M}</h1>
<div class=k>{''.join(f'<div><span>{html.escape(k)}</span><b>{v}</b></div>' for k, v in st.items())}
<div><span>미응답 답글</span><b>{unanswered}</b></div></div>
<section><h2>이번 주 액션</h2><ul>{''.join(f'<li>{html.escape(a)}</li>' for a in actions)}</ul></section>
<section><h2>버전별 평균 조회</h2>{bars or '데이터 없음'}</section>
<section><h2>예정·진행</h2><table><tr>{''.join(f'<th>{c}</th>' for c in up_cols)}</tr>{''.join(tr(r, up_cols) for r in upcoming)}</table></section>
<section><h2>성과(최신 수집값)</h2><table><tr>{''.join(f'<th>{c}</th>' for c in m_cols)}</tr>{''.join(tr(r, m_cols) for r in pub)}</table></section>"""
    OUT.mkdir(exist_ok=True)
    p = OUT / "dashboard.html"
    p.write_text(doc, encoding="utf-8")
    return str(p)
