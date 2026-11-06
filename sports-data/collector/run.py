"""수집 → 변화 감지 → 알림 → 사이트 생성.

사용법 (sports-data 폴더에서):
  python -m collector.run            # 한 번 실행
  python -m collector.run --watch    # 경기 상황에 맞춰 계속 실행 (상시 PC·무료 서버용)
  python -m collector.run --no-publish
"""
import argparse
import html
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from . import espn, manual, model, notify, publish

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KST = timezone(timedelta(hours=9))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def parse_utc(s):
    s = s.replace("Z", "+00:00")
    if len(s) == 22:  # 2026-11-06T20:00+00:00 (초 없음)
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s)


def needs_details(game, now):
    start = parse_utc(game["start_utc"])
    if game["state"] == "in":
        return True
    if game["state"] == "pre":
        return start - now < timedelta(hours=36)
    return now - start < timedelta(hours=12)


def collect(cfg, leagues, now, log):
    games, errors = {}, []
    today = now.astimezone(KST).date()
    dates = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(-cfg["days_back"], cfg["days_ahead"] + 1)]
    for lg in leagues:
        for d in dates:
            try:
                for g in espn.scoreboard(lg, d):
                    games[g["id"]] = g
            except Exception as e:  # 한 리그 실패가 전체를 멈추지 않게
                errors.append(f"{lg['key']} {d}: {e}")
    by_key = {lg["key"]: lg for lg in leagues}
    detail_calls = 0
    for g in games.values():
        if not needs_details(g, now):
            continue
        try:
            g.update(espn.details(by_key[g["league"]], g["espn_id"]))
            detail_calls += 1
        except Exception as e:
            errors.append(f"detail {g['id']}: {e}")
    for g in games.values():
        g["prob"] = model.probabilities(g)
    log(f"ESPN 경기 {len(games)}개, 상세 {detail_calls}개, 오류 {len(errors)}개")
    return games, errors


def diff(games, state, now_iso, ko):
    """직전 상태와 비교해 새 소식만 이벤트로 만든다."""
    events = []
    new_state = {}
    for g in games.values():
        prev = state.get(g["id"], {})
        cur = {
            "state": g["state"],
            "lineup": sorted(g.get("lineups", {}).keys()),
            "inj": sorted({f"{tid}|{i['name']}|{i['status']}" for tid, lst in g.get("injuries", {}).items() for i in lst}),
            "score": f"{g['home'].get('score')}-{g['away'].get('score')}",
        }
        new_state[g["id"]] = cur
        if not prev:
            continue  # 처음 본 경기는 기준선만 저장
        title = f"{ko(g['home']['name'])} vs {ko(g['away']['name'])}"
        base = {"ts": now_iso, "game": g["id"], "league": g["league_name"], "title": title}
        for tid in set(cur["lineup"]) - set(prev.get("lineup", [])):
            side = "home" if g["home"].get("id") == tid else "away"
            lu = g["lineups"][tid]
            names = ", ".join(p["name"] for p in lu["starters"][:11] if p["name"])
            events.append({**base, "kind": "lineup",
                           "text": f"{ko(g[side]['name'])} 선발 확정" + (f" ({lu['formation']})" if lu.get("formation") else ""),
                           "detail": names})
        for item in set(cur["inj"]) - set(prev.get("inj", [])):
            tid, name, status = item.split("|", 2)
            side = "home" if g["home"].get("id") == tid else "away"
            events.append({**base, "kind": "injury", "text": f"{ko(g[side]['name'])} {name}: {status}", "detail": ""})
        if cur["state"] == "post" and prev.get("state") != "post":
            events.append({**base, "kind": "final",
                           "text": f"경기 종료 {ko(g['home']['name'])} {g['home'].get('score')} : {g['away'].get('score')} {ko(g['away']['name'])}",
                           "detail": ""})
    return events, new_state


def telegram_text(events, cfg):
    icon = {"lineup": "📋", "injury": "🚑", "final": "🏁"}
    lines = []
    for e in events[:25]:
        lines.append(f"{icon.get(e['kind'], '•')} <b>[{html.escape(e['league'])}]</b> {html.escape(e['text'])}")
        if e.get("detail"):
            lines.append(f"   {html.escape(e['detail'][:300])}")
    lines.append(f"\n전체 데이터: {cfg['base_url']}/")
    return "\n".join(lines)


def run_once(args, log=print):
    cfg = load_json(os.path.join(ROOT, "config", "site.json"), {})
    leagues = load_json(os.path.join(ROOT, "config", "leagues.json"), [])
    names = load_json(os.path.join(ROOT, "config", "teams_ko.json"), {})
    ko = lambda n: names.get(n, n) if n else ""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    games, errors = collect(cfg, leagues, now, log)
    for g in manual.load_domestic(os.path.join(DATA, "manual", "domestic.csv")):
        games[g["id"]] = g
    proto = manual.load_proto(os.path.join(DATA, "manual", "proto.csv"))

    state = load_json(os.path.join(DATA, "state.json"), {})
    events, new_state = diff(games, state, now_iso, ko)
    feed = load_json(os.path.join(DATA, "events.json"), [])
    feed = (events + feed)[:300]

    save_json(os.path.join(DATA, "state.json"), new_state)
    save_json(os.path.join(DATA, "events.json"), feed)
    save_json(os.path.join(DATA, "games.json"), {"updated": now_iso, "errors": errors, "games": list(games.values())})
    log(f"새 소식 {len(events)}건")

    if events and not args.no_notify:
        try:
            if notify.send(telegram_text(events, cfg)):
                log("텔레그램 발송 완료")
        except Exception as e:
            log(f"텔레그램 발송 실패: {e}")

    if not args.no_publish:
        n = publish.build(cfg, list(games.values()), feed, proto, ko, now, os.path.join(ROOT, "site"))
        log(f"사이트 페이지 {n}개 생성")
    return games


def next_interval(games):
    """경기 직전·진행 중에는 짧게, 그 외에는 길게."""
    now = datetime.now(timezone.utc)
    soon = [g for g in games.values() if g.get("source") == "ESPN" and (
        g["state"] == "in" or timedelta(0) < parse_utc(g["start_utc"]) - now < timedelta(minutes=90))]
    return 30 if soon else 600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()
    if not args.watch:
        run_once(args)
        return
    while True:
        try:
            games = run_once(args)
            wait = next_interval(games)
        except Exception as e:
            print(f"실행 오류: {e}", file=sys.stderr)
            wait = 120
        print(f"{wait}초 뒤 다시 확인")
        time.sleep(wait)


if __name__ == "__main__":
    main()
