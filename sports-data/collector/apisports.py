"""API-Sports 무료 플랜(종목별 하루 100회)으로 국내 리그를 가져온다.

- K리그1·K리그2: API-Football (일정·결과·라인업·부상)
- KBL·WKBL: API-Basketball / V리그 남녀: API-Volleyball / KBO: API-Baseball (일정·결과)

키: 환경변수 APISPORTS_KEY (dashboard.api-football.com 무료 가입, 한 키로 전 종목 사용)
호출 수는 data/apisports_budget.json에 기록하고 종목별 하루 90회를 넘기지 않는다.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HOSTS = {
    "soccer": "v3.football.api-sports.io",
    "basketball": "v1.basketball.api-sports.io",
    "volleyball": "v1.volleyball.api-sports.io",
    "baseball": "v1.baseball.api-sports.io",
}
DAILY_CAP = 90
PRE = {"NS", "TBD"}
POST = {"FT", "AET", "PEN", "AOT", "AP", "AWD", "WO", "POST"}
OFF = {"PST": "연기", "CANC": "취소", "ABD": "중단", "SUSP": "중단", "INTR": "중단"}


class Client:
    def __init__(self, root, log=print):
        self.key = os.environ.get("APISPORTS_KEY") or ("proxy" if os.environ.get("APISPORTS_PROXY") else None)
        self.root = root
        self.log = log
        self.budget_path = os.path.join(root, "data", "apisports_budget.json")
        self.cache_path = os.path.join(root, "data", "apisports_cache.json")
        self.budget = self._load(self.budget_path, {})
        self.cache = self._load(self.cache_path, {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.budget.get("date") != today:
            self.budget = {"date": today}

    @staticmethod
    def _load(p, default):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def save(self):
        for p, obj in ((self.budget_path, self.budget), (self.cache_path, self.cache)):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)

    @property
    def enabled(self):
        return bool(self.key)

    def get(self, sport, path, params, ttl_min):
        """ttl_min 안에 같은 요청을 했으면 캐시를 쓴다. 한도에 닿으면 캐시(없으면 None)."""
        host = HOSTS[sport]
        url = f"https://{host}/{path}?{urllib.parse.urlencode(params)}"
        now = datetime.now(timezone.utc)
        hit = self.cache.get(url)
        if hit and now - datetime.fromisoformat(hit["t"]) < timedelta(minutes=ttl_min):
            return hit["data"]
        if self.budget.get(host, 0) >= DAILY_CAP:
            return hit["data"] if hit else None
        req = urllib.request.Request(url, headers={"x-apisports-key": self.key, "User-Agent": "sports-data-collector/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8"))
        self.budget[host] = self.budget.get(host, 0) + 1
        if data.get("errors"):
            self.log(f"API-Sports 오류 {path}: {data['errors']}")
            return hit["data"] if hit else None
        self.cache[url] = {"t": now.isoformat(timespec="seconds"), "data": data.get("response", [])}
        return self.cache[url]["data"]

    # ---------- 리그·시즌 찾기 ----------
    def resolve(self, lg):
        rows = self.get(lg["sport"], "leagues", {"country": lg.get("country", "South-Korea")}, ttl_min=60 * 24 * 7) or []
        want = lg["match"].lower()
        for r in rows:
            league = r.get("league", r)
            name = (league.get("name") or "").lower()
            if name == want or (lg.get("loose") and want in name):
                seasons = r.get("seasons", []) or []
                cur = [s for s in seasons if s.get("current")] or seasons[-1:]
                if not cur:
                    continue
                return league.get("id"), cur[0].get("year", cur[0].get("season"))
        return None, None

    # ---------- 경기 ----------
    def games(self, lg, ttl_min):
        lid, season = self.resolve(lg)
        if not lid:
            self.log(f"API-Sports 리그 못 찾음: {lg['name']}")
            return [], []
        path = "fixtures" if lg["sport"] == "soccer" else "games"
        rows = self.get(lg["sport"], path, {"league": lid, "season": season}, ttl_min) or []
        upcoming, history = [], []
        for r in rows:
            g = self._norm(lg, r)
            if not g:
                continue
            upcoming.append(g)
            if g["state"] == "post" and g["home"]["score"] is not None and g["away"]["score"] is not None:
                history.append({"id": g["id"], "date": g["start_utc"], "home": g["home"]["id"], "away": g["away"]["id"],
                                "home_name": g["home"]["name"], "away_name": g["away"]["name"],
                                "hs": int(g["home"]["score"]), "as": int(g["away"]["score"])})
        return upcoming, history

    def _norm(self, lg, r):
        if lg["sport"] == "soccer":
            fx = r.get("fixture", {})
            gid, date, st, venue = fx.get("id"), fx.get("date"), fx.get("status", {}), (fx.get("venue") or {}).get("name")
            sh, sa = (r.get("goals") or {}).get("home"), (r.get("goals") or {}).get("away")
        else:
            gid, date, st, venue = r.get("id"), r.get("date"), r.get("status", {}), None
            sc = r.get("scores") or {}
            def tot(x):
                return x.get("total") if isinstance(x, dict) else x
            sh, sa = tot(sc.get("home")), tot(sc.get("away"))
        teams = r.get("teams") or {}
        if not gid or not date or not teams.get("home") or not teams.get("away"):
            return None
        short = (st.get("short") or "").upper()
        state = "pre" if short in PRE or short in OFF else "post" if short in POST else "in"
        dt = datetime.fromisoformat(date.replace("Z", "+00:00")).astimezone(timezone.utc)
        team = lambda t, s: {"id": str(t.get("id")), "name": t.get("name"), "logo": t.get("logo"), "score": s, "record": None}
        return {
            "id": f"{lg['key']}-{gid}", "api_id": gid, "league": lg["key"], "league_name": lg["name"], "sport": lg["sport"],
            "start_utc": dt.strftime("%Y-%m-%dT%H:%MZ"), "state": state,
            "status_detail": OFF.get(short, st.get("long")), "home": team(teams["home"], sh), "away": team(teams["away"], sa),
            "venue": venue, "source": "API-Sports",
        }

    def football_details(self, g):
        """킥오프 2시간 전부터 라인업·부상을 조회 (라인업은 발표 전이면 30분 캐시, 발표 후 고정)."""
        fid = g["api_id"]
        out = {"lineups": {}, "injuries": {}}
        lu = self.get("soccer", "fixtures/lineups", {"fixture": fid}, ttl_min=30 if not g.get("lineups") else 60 * 24) or []
        for t in lu:
            tid = str((t.get("team") or {}).get("id"))
            xi = [{"name": (p.get("player") or {}).get("name"), "pos": (p.get("player") or {}).get("pos"),
                   "no": (p.get("player") or {}).get("number")} for p in t.get("startXI", []) or []]
            if xi:
                out["lineups"][tid] = {"formation": t.get("formation"), "starters": xi}
        inj = self.get("soccer", "injuries", {"fixture": fid}, ttl_min=120) or []
        for i in inj:
            tid = str((i.get("team") or {}).get("id"))
            pl = i.get("player") or {}
            out["injuries"].setdefault(tid, []).append({"name": pl.get("name"), "status": "Out" if pl.get("type") == "Missing Fixture" else "Questionable",
                                                       "part": pl.get("reason")})
        return out
