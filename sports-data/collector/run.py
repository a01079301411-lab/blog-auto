"""수집 → 시즌 기록 → 분석 → 변화 감지 → 알림 → 사이트 생성.

사용법 (sports-data 폴더에서):
  python -m collector.run            # 한 번 실행
  python -m collector.run --watch    # 경기 상황에 맞춰 계속 실행 (상시 PC·무료 서버용)
  python -m collector.run --no-publish --no-notify
"""
import argparse
import html
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import analysis, apisports, espn, history, manual, model, notify, publish

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
    if len(s) == 22:
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s)


def make_ko():
    names = load_json(os.path.join(ROOT, "config", "teams_ko.json"), {})
    keywords = load_json(os.path.join(ROOT, "config", "teams_ko_keywords.json"), [])

    def ko(n):
        if not n:
            return ""
        if n in names:
            return names[n]
        low = n.lower()
        for kw, k in keywords:
            if kw.lower() in low:
                return k
        return n
    return ko


def needs_details(game, now):
    start = parse_utc(game["start_utc"])
    if game["state"] == "in":
        return True
    if game["state"] == "pre":
        return start - now < timedelta(hours=36)
    return now - start < timedelta(hours=12)


def collect_espn(cfg, leagues, now, log):
    games, errors = {}, []
    today = now.astimezone(KST).date()
    dates = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(-cfg["days_back"], cfg["days_ahead"] + 1)]
    for lg in leagues:
        for d in dates:
            try:
                for g in espn.scoreboard(lg, d):
                    games[g["id"]] = g
            except Exception as e:
                errors.append(f"{lg['key']} {d}: {e}")
    by_key = {lg["key"]: lg for lg in leagues}
    calls = 0
    for g in games.values():
        if not needs_details(g, now):
            continue
        try:
            g.update(espn.details(by_key[g["league"]], g["espn_id"]))
            calls += 1
        except Exception as e:
            errors.append(f"detail {g['id']}: {e}")
    log(f"ESPN 경기 {len(games)}개, 상세 {calls}개")
    return games, errors


def collect_domestic(cfg, now, log):
    client = apisports.Client(ROOT, log)
    games, hists, errors = {}, {}, []
    if not client.enabled:
        log("국내 리그: APISPORTS_KEY 없음 → 건너뜀 (CSV 입력만 사용)")
        return games, hists, errors
    for lg in load_json(os.path.join(ROOT, "config", "domestic.json"), []):
        try:
            # 경기 임박·진행 중이면 10분, 평소 60분 캐시 → 종목별 하루 100회 안에서 운영
            up, hist = client.games(lg, ttl_min=60)
            live = any(g["state"] == "in" or timedelta(0) < parse_utc(g["start_utc"]) - now < timedelta(hours=2) for g in up)
            if live:
                up, hist = client.games(lg, ttl_min=10)
            hists[lg["key"]] = (lg["sport"], hist)
            for g in up:
                start = parse_utc(g["start_utc"])
                if timedelta(days=-cfg["days_back"] - 1) < start - now < timedelta(days=cfg["days_ahead"] + 1):
                    if lg["sport"] == "soccer" and g["state"] != "post" and start - now < timedelta(hours=2):
                        g.update(client.football_details(g))
                    games[g["id"]] = g
        except Exception as e:
            errors.append(f"{lg['key']}: {e}")
    client.save()
    used = ", ".join(k.split(".")[1] + " " + str(v) for k, v in client.budget.items() if k != "date")
    log(f"국내 경기 {len(games)}개 (오늘 API 사용량: {used or '0'})")
    return games, hists, errors


def build_models(cfg, leagues, games, domestic_hists, now, log):
    """리그별 Elo 모델과 팀별 경기 날짜(휴식일 계산용)."""
    models, team_dates = {}, defaultdict(lambda: defaultdict(list))
    by_league = defaultdict(list)
    for g in games.values():
        by_league[g["league"]].append(g)
    for lg in leagues:
        if not by_league.get(lg["key"]):
            continue  # 시즌이 아닌 리그는 기록 갱신 생략
        history.refresh_espn(ROOT, lg, now, log)
        hist = history.merge_finished(ROOT, lg["key"], by_league[lg["key"]])
        prev = history.refresh_prev(ROOT, lg, log)
        models[lg["key"]] = analysis.League(lg["sport"], list(hist["games"].values()), prev)
    for key, (sport, hist) in domestic_hists.items():
        models[key] = analysis.League(sport, hist)
    for key, m in models.items():
        for g in m.games:
            team_dates[m.sport][g["home"]].append(analysis._dt(g["date"]))
            team_dates[m.sport][g["away"]].append(analysis._dt(g["date"]))
    for g in games.values():  # 예정 경기도 포함해야 내일 경기의 연전 여부를 안다
        if g["home"].get("id"):
            for side in ("home", "away"):
                team_dates[g["sport"]][g[side]["id"]].append(parse_utc(g["start_utc"]))
    return models, team_dates


def diff(games, state, now_iso, ko):
    """직전 상태와 비교해 새 소식만 이벤트로 만든다."""
    events, new_state = [], {}
    for g in games.values():
        prev = state.get(g["id"], {})
        cur = {
            "state": g["state"],
            "lineup": sorted(g.get("lineups", {}).keys()),
            "inj": sorted({f"{tid}|{i['name']}|{i['status']}" for tid, lst in g.get("injuries", {}).items() for i in lst}),
            "score": f"{g['home'].get('score')}-{g['away'].get('score')}",
            "fav": (g.get("prob") or {}).get("home"),
        }
        new_state[g["id"]] = cur
        if not prev:
            continue
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
            events.append({**base, "kind": "injury", "text": f"{ko(g[side]['name'])} {name}: {espn.inj_ko(status)}", "detail": ""})
        if prev.get("fav") is not None and cur["fav"] is not None and g["state"] == "pre" and abs(cur["fav"] - prev["fav"]) >= 0.05:
            events.append({**base, "kind": "prob",
                           "text": f"{title} 승률 변화: {ko(g['home']['name'])} {prev['fav'] * 100:.0f}% → {cur['fav'] * 100:.0f}%",
                           "detail": "라인업·부상 반영"})
        if cur["state"] == "post" and prev.get("state") != "post":
            events.append({**base, "kind": "final",
                           "text": f"경기 종료 {ko(g['home']['name'])} {g['home'].get('score')} : {g['away'].get('score')} {ko(g['away']['name'])}",
                           "detail": ""})
    return events, new_state


def telegram_text(events, cfg):
    icon = {"lineup": "📋", "injury": "🚑", "final": "🏁", "prob": "📊"}
    lines = []
    for e in events[:25]:
        lines.append(f"{icon.get(e['kind'], '•')} <b>[{html.escape(e['league'])}]</b> {html.escape(e['text'])}")
        if e.get("detail"):
            lines.append(f"   {html.escape(e['detail'][:300])}")
    lines.append(f"\n경기별 분석: {cfg['base_url']}/")
    return "\n".join(lines)


def run_once(args, log=print):
    cfg = load_json(os.path.join(ROOT, "config", "site.json"), {})
    leagues = load_json(os.path.join(ROOT, "config", "leagues.json"), [])
    ko = make_ko()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    games, errors = collect_espn(cfg, leagues, now, log)
    dom, dom_hists, dom_err = collect_domestic(cfg, now, log)
    games.update(dom)
    errors += dom_err
    for g in manual.load_domestic(os.path.join(DATA, "manual", "domestic.csv")):
        games[g["id"]] = g
    proto = manual.load_proto(os.path.join(DATA, "manual", "proto.csv"))

    models, team_dates = build_models(cfg, leagues, games, dom_hists, now, log)
    record = {}
    for key, m in models.items():
        record[key] = m.backtest()
    for g in games.values():
        m = models.get(g["league"])
        an = analysis.analyze(g, m, team_dates[g["sport"]]) if m and m.games else None
        g["analysis"] = an
        g["comment"] = analysis.comment(g, an, ko)
        g["prob"] = an["prob"] if an else model.probabilities(g)
    analyzed = sum(1 for g in games.values() if g.get("analysis"))
    log(f"분석 {analyzed}경기 · 오류 {len(errors)}개")

    state = load_json(os.path.join(DATA, "state.json"), {})
    events, new_state = diff(games, state, now_iso, ko)
    feed = (events + load_json(os.path.join(DATA, "events.json"), []))[:300]
    save_json(os.path.join(DATA, "state.json"), new_state)
    save_json(os.path.join(DATA, "events.json"), feed)
    save_json(os.path.join(DATA, "games.json"), {"updated": now_iso, "errors": errors, "games": list(games.values())})
    save_json(os.path.join(DATA, "model_record.json"), {"updated": now_iso, "leagues": record})
    log(f"새 소식 {len(events)}건")

    if events and not args.no_notify:
        try:
            if notify.send(telegram_text(events, cfg)):
                log("텔레그램 발송 완료")
        except Exception as e:
            log(f"텔레그램 발송 실패: {e}")

    if not args.no_publish:
        n = publish.build(cfg, list(games.values()), feed, proto, ko, now, os.path.join(ROOT, "site"), models, record)
        log(f"사이트 페이지 {n}개 생성")
    return games


def next_interval(games):
    now = datetime.now(timezone.utc)
    soon = [g for g in games.values() if g.get("source") != "수동 입력" and (
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
            wait = next_interval(run_once(args))
        except Exception as e:
            print(f"실행 오류: {e}", file=sys.stderr)
            wait = 120
        print(f"{wait}초 뒤 다시 확인")
        time.sleep(wait)


if __name__ == "__main__":
    main()
