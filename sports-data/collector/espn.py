"""ESPN 공개 JSON에서 일정·결과·라인업·부상·최근 5경기를 가져와 공통 형식으로 바꾼다.

배당(odds, pickcenter)과 티켓 링크는 해외 업체 정보라 의도적으로 버린다.
"""
from .http import get_json

BASE = "https://site.api.espn.com/apis/site/v2/sports"


def _team(c):
    t = c.get("team", {})
    rec = (c.get("records") or [{}])[0].get("summary")
    return {
        "id": t.get("id"),
        "name": t.get("displayName") or t.get("name"),
        "abbr": t.get("abbreviation"),
        "logo": t.get("logo"),
        "score": c.get("score"),
        "form": c.get("form"),
        "record": rec,
    }


def scoreboard(league, yyyymmdd):
    data = get_json(f"{BASE}/{league['espn']}/scoreboard?dates={yyyymmdd}")
    games = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in sides or "away" not in sides:
            continue
        st = (ev.get("status") or comp.get("status") or {}).get("type", {})
        games.append({
            "id": f"{league['key']}-{ev['id']}",
            "espn_id": ev["id"],
            "league": league["key"],
            "league_name": league["name"],
            "sport": league["sport"],
            "start_utc": ev.get("date"),
            "state": st.get("state", "pre"),          # pre / in / post
            "status_detail": st.get("shortDetail") or st.get("detail"),
            "home": _team(sides["home"]),
            "away": _team(sides["away"]),
            "venue": (comp.get("venue") or {}).get("fullName"),
            "source": "ESPN",
        })
    return games


def _lineups(summary):
    out = {}
    for r in summary.get("rosters", []) or []:
        tid = (r.get("team") or {}).get("id")
        starters = [
            {
                "name": (p.get("athlete") or {}).get("displayName"),
                "pos": (p.get("position") or {}).get("abbreviation"),
                "no": p.get("jersey"),
            }
            for p in r.get("roster", []) or []
            if p.get("starter")
        ]
        if tid and starters:
            out[tid] = {"formation": r.get("formation"), "starters": starters}
    return out


def _injuries(summary):
    out = {}
    for block in summary.get("injuries", []) or []:
        tid = (block.get("team") or {}).get("id")
        items = []
        for i in block.get("injuries", []) or []:
            a = i.get("athlete") or {}
            d = i.get("details") or {}
            items.append({
                "name": a.get("displayName"),
                "pos": (a.get("position") or {}).get("abbreviation"),
                "status": i.get("status"),
                "part": d.get("type"),
                "return": d.get("returnDate"),
            })
        if tid:
            out[tid] = items
    return out


def _last_five(summary):
    out = {}
    for block in summary.get("lastFiveGames", []) or []:
        tid = (block.get("team") or {}).get("id")
        games = []
        for e in block.get("events", []) or []:
            games.append({
                "date": e.get("gameDate"),
                "result": e.get("gameResult"),
                "score": e.get("score"),
                "at_vs": e.get("atVs"),
                "opponent": (e.get("opponent") or {}).get("displayName"),
                "competition": e.get("competitionName"),
            })
        if tid:
            out[tid] = games
    return out


def _series(summary):
    for s in summary.get("seasonseries", []) or []:
        if s.get("summary"):
            return s["summary"]
    return None


def details(league, espn_id):
    """경기 상세. 라인업은 발표 전이면 비어 있다."""
    s = get_json(f"{BASE}/{league['espn']}/summary?event={espn_id}")
    return {
        "lineups": _lineups(s),
        "injuries": _injuries(s),
        "last_five": _last_five(s),
        "series": _series(s),
    }

