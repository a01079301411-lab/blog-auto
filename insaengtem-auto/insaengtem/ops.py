"""운영: 주간 계획 → 승인 → 게시(API 정시 / 웹 일괄 예약) → 동기화 → 성과 수집 → 답글 확인."""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta

from . import db, qa
from .catalog import link_for, load_catalog
from .config import OUT, ROOT, fmt_when, now, parse_when, settings, tz


# ------------------------------------------------------------------ 승인용 검토 페이지
def review_html(rows: list, path) -> str:
    cards = []
    for r in rows:
        cover = f"out/{r['product']}_{r['variant']}/cover_3x4.jpg" if r["product"] else None
        issues = []
        if r["text"]:
            plat = "instagram" if r["platform"] == "instagram" else "threads_root"
            issues += qa.check_text(r["text"], where="본문", is_ad=bool(r["product"]), platform=plat)
        if r["reply"]:
            issues += qa.check_text(r["reply"], where="2번째 칸", is_ad=True, platform="threads_reply")
        if r["video"]:
            issues += qa.check_video(ROOT / r["video"]) if (ROOT / r["video"]).exists() else [
                qa.Issue("error", "VIDEO_MISSING", r["video"])]
        badge = "".join(f"<li class='{i.level}'>{html.escape(str(i))}</li>" for i in issues) or "<li class='ok'>검수 통과</li>"
        rel = cover.removeprefix("out/") if cover else ""
        img = f"<img src='../{rel}'>" if cover and (ROOT / cover).exists() else "<div class='noimg'>텍스트</div>"
        cards.append(f"""<div class='card'>{img}<div><b>#{r['id']} {r['platform']} · {r['when_kst']}</b>
<span class='st'>{r['status']}</span><div class='meta'>{r['product'] or '공감글'} {r['variant'] or ''}</div>
<pre>{html.escape(r['text'] or '')}</pre>{f"<pre class='reply'>{html.escape(r['reply'])}</pre>" if r['reply'] else ''}
<ul>{badge}</ul></div></div>""")
    doc = f"""<!doctype html><meta charset=utf-8><title>주간 검토</title>
<style>body{{font-family:system-ui,'Malgun Gothic';background:#f6f4f0;margin:0;padding:16px}}
.card{{display:flex;gap:16px;background:#fff;border-radius:12px;padding:14px;margin:12px 0;box-shadow:0 1px 3px #0002}}
img,.noimg{{width:180px;border-radius:8px;flex:none}}.noimg{{height:120px;background:#eee;display:grid;place-items:center}}
pre{{white-space:pre-wrap;background:#faf8f5;padding:8px;border-radius:6px;font-size:14px}}pre.reply{{background:#eef5ff}}
li.error{{color:#c00;font-weight:600}}li.warn{{color:#b60}}li.ok{{color:#080}}.st{{margin-left:8px;color:#666}}.meta{{color:#555}}
@media(max-width:640px){{.card{{flex-direction:column}}img{{width:100%}}}}</style>
<h1>인생템연구소 주간 검토 ({len(rows)}건)</h1><p>이상 없으면: <code>python -m insaengtem approve --week {rows[0]['week'] if rows else ''} --yes</code></p>
{''.join(cards)}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return str(path)


def approve(week: str, yes: bool) -> None:
    with db.connect() as con:
        rows = con.execute("SELECT * FROM posts WHERE week=? AND status IN ('draft','failed') ORDER BY when_kst", (week,)).fetchall()
        p = review_html(rows, OUT / "review" / f"{week}.html")
        print(f"검토 페이지: {p}")
        errs = []
        for r in rows:
            plat = "instagram" if r["platform"] == "instagram" else "threads_root"
            errs += [i for i in qa.check_text(r["text"] or "", where=f"#{r['id']}", is_ad=bool(r["product"]), platform=plat)
                     if i.level == "error"]
        if errs:
            print("\n".join(map(str, errs)))
            print(f"→ 오류 {len(errs)}건. 고친 뒤 다시 승인하세요.")
            return
        if not yes:
            print("확인 후 --yes 로 승인하면 게시 대상이 됩니다.")
            return
        con.execute("UPDATE posts SET status='approved', approved_at=? WHERE week=? AND status IN ('draft','failed')",
                    (fmt_when(now()), week))
        print(f"{len(rows)}건 승인 완료 ({week}).")


# ------------------------------------------------------------------ 게시
def _resolve_link(text: str | None, product: str | None) -> str | None:
    if text and "{link}" in text:
        return text.replace("{link}", link_for(product))
    return text


def _still_available(product: str | None) -> bool:
    if not product:
        return True
    cat = {c["key"]: c for c in load_catalog()}
    if not cat.get(product, {}).get("available", False):
        return False
    if settings().get("recheck_soldout_before_publish"):
        from .scrape_yogo import recheck_soldout
        sold = recheck_soldout(product)
        if sold:
            return False
    return True


def run_due(dry: bool = False) -> None:
    """API 모드: 게시 시각이 된 승인 건을 바로 게시. 5분마다 작업 스케줄러로 실행."""
    s = settings()
    grace = timedelta(minutes=s["publish_grace_minutes"])
    t = now()
    with db.connect() as con:
        rows = con.execute("SELECT * FROM posts WHERE status='approved' ORDER BY when_kst").fetchall()
        for r in rows:
            when = parse_when(r["when_kst"])
            if when > t:
                continue
            if t - when > grace:
                db.set_status(con, r["id"], "missed", error=f"게시 시각 {grace} 초과")
                print(f"[missed] #{r['id']} {r['when_kst']}")
                continue
            if s["publish_mode"][r["platform"]] != "api":
                continue
            if not _still_available(r["product"]):
                db.set_status(con, r["id"], "skipped", error="품절/판매중지")
                print(f"[skip] #{r['id']} {r['product']} 품절")
                continue
            if dry:
                print(f"[dry] 게시 예정 #{r['id']} {r['platform']} {r['when_kst']}")
                continue
            db.set_status(con, r["id"], "publishing")
            con.commit()
            try:
                res = publish_now(r)
                db.set_status(con, r["id"], "published", remote_id=res.get("remote_id"),
                              reply_remote_id=res.get("reply_remote_id"), permalink=res.get("permalink"),
                              published_at=fmt_when(now()), error=None)
                print(f"[ok] #{r['id']} {r['platform']} → {res.get('permalink')}")
            except Exception as e:  # noqa: BLE001
                db.set_status(con, r["id"], "failed", error=str(e)[:500])
                print(f"[fail] #{r['id']} {e}")


def publish_now(r) -> dict:
    from .publish.meta_api import Instagram, Threads, abs_video
    text = _resolve_link(r["text"], r["product"])
    reply = _resolve_link(r["reply"], r["product"])
    if r["platform"] == "instagram":
        return Instagram().publish_reel(abs_video(r["video"]), text)
    video_url = None
    if r["video"]:
        from .publish.media_host import public_url
        abs_video(r["video"])
        video_url = public_url(r["video"])
    return Threads().publish(text, video_url=video_url, reply=reply)


def schedule_web(week: str, platform: str) -> None:
    """웹 모드: 승인된 주간 묶음을 Threads/Business Suite 의 '예약' 기능으로 한 번에 걸어둔다."""
    from .publish import web
    with db.connect() as con:
        rows = con.execute("SELECT * FROM posts WHERE week=? AND platform=? AND status='approved' ORDER BY when_kst",
                           (week, platform)).fetchall()
        items = [{"id": r["id"], "when_kst": r["when_kst"], "video": r["video"],
                  "text": _resolve_link(r["text"], r["product"]), "reply": _resolve_link(r["reply"], r["product"])}
                 for r in rows if parse_when(r["when_kst"]) > now() + timedelta(minutes=20)]
        if not items:
            print("예약할 건이 없습니다.")
            return
        res = web.schedule_threads(items) if platform == "threads" else web.schedule_instagram(items)
        for x in res:
            if x["ok"]:
                db.set_status(con, x["id"], "scheduled_web")
            else:
                db.set_status(con, x["id"], "failed", error=x["error"][:500])
            print(("[ok] " if x["ok"] else "[fail] ") + f"#{x['id']} {x.get('error', '')}")


def meta_ts(s: str) -> datetime:
    """'2026-11-03T03:30:00+0000' → KST aware datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").astimezone(tz())


# ------------------------------------------------------------------ 동기화(웹/수동 예약 건의 원격 ID 채우기)
def sync() -> None:
    from .publish.meta_api import Instagram, Threads
    with db.connect() as con:
        pend = con.execute("SELECT * FROM posts WHERE remote_id IS NULL AND status IN ('external','scheduled_web','published')").fetchall()
        remote = {}
        try:
            remote["instagram"] = Instagram().recent_media(100)
        except SystemExit as e:
            print(f"[sync] 인스타 건너뜀: {e}")
        try:
            remote["threads"] = Threads().recent(100)
        except SystemExit as e:
            print(f"[sync] 스레드 건너뜀: {e}")
        n = 0
        for r in pend:
            want = parse_when(r["when_kst"])
            head = (r["text"] or "").strip().split("\n")[0][:20]
            for m in remote.get(r["platform"], []):
                ts = meta_ts(m["timestamp"])
                body = m.get("caption") or m.get("text") or ""
                if abs((ts - want).total_seconds()) <= 20 * 60 and head and head in body:
                    db.set_status(con, r["id"], "published", remote_id=m["id"], permalink=m.get("permalink"),
                                  published_at=fmt_when(ts))
                    n += 1
                    break
        print(f"[sync] {n}/{len(pend)}건 매칭")


# ------------------------------------------------------------------ 성과·답글
def insights(days: int = 14) -> None:
    from .publish.meta_api import Instagram, Threads
    since = fmt_when(now() - timedelta(days=days))
    with db.connect() as con:
        rows = con.execute("SELECT * FROM posts WHERE status='published' AND remote_id IS NOT NULL AND when_kst>=?", (since,)).fetchall()
        apis = {}
        for r in rows:
            try:
                api = apis.setdefault(r["platform"], Instagram() if r["platform"] == "instagram" else Threads())
                db.add_metrics(con, r["id"], api.insights(r["remote_id"]))
            except Exception as e:  # noqa: BLE001
                print(f"[insights] #{r['id']} 실패: {e}")
        for plat, api in apis.items():
            try:
                f = api.followers() if plat == "instagram" else api.user_insights().get("followers_count")
                con.execute("INSERT INTO account_metrics (platform, fetched_at, followers, raw) VALUES (?,?,?,?)",
                            (plat, fmt_when(now()), f, "{}"))
            except Exception as e:  # noqa: BLE001
                print(f"[insights] {plat} 팔로워 실패: {e}")
        print(f"[insights] {len(rows)}건 수집")


def inbox(hours: int = 48) -> list[dict]:
    """최근 게시물의 새 답글/댓글. 스레드는 게시 후 1시간 안에 답하는 것이 핵심."""
    from .publish.meta_api import Instagram, Threads
    since = fmt_when(now() - timedelta(hours=hours))
    new = []
    with db.connect() as con:
        rows = con.execute("SELECT * FROM posts WHERE status='published' AND remote_id IS NOT NULL AND when_kst>=?", (since,)).fetchall()
        for r in rows:
            try:
                api = Instagram() if r["platform"] == "instagram" else Threads()
                items = api.comments(r["remote_id"]) if r["platform"] == "instagram" else api.replies(r["remote_id"])
            except Exception as e:  # noqa: BLE001
                print(f"[inbox] #{r['id']} {e}")
                continue
            acct = settings()["accounts"][r["platform"]]
            for c in items:
                if c.get("username") == acct or c["id"] == r["reply_remote_id"]:
                    continue
                if con.execute("SELECT 1 FROM replies_seen WHERE reply_id=?", (c["id"],)).fetchone():
                    continue
                con.execute("INSERT INTO replies_seen (platform, reply_id, post_id, username, text, ts) VALUES (?,?,?,?,?,?)",
                            (r["platform"], c["id"], r["id"], c.get("username"), c.get("text"), c.get("timestamp")))
                new.append({"post": r["id"], "platform": r["platform"], "user": c.get("username"), "text": c.get("text"),
                            "permalink": r["permalink"]})
    for n in new:
        print(f"💬 [{n['platform']}] #{n['post']} @{n['user']}: {n['text']}  → {n['permalink']}")
    if not new:
        print("새 답글 없음")
    return new
