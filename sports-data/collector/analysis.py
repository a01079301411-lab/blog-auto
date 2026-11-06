"""승률 분석 엔진.

1. Elo: 시즌 경기를 날짜순으로 돌려 팀 전력 점수를 만든다 (득실차 반영)
2. 경기 요인: 홈/원정 성적 차이, 휴식일·연전, 부상(주축 선수 가중), 최근 흐름, 요일별 성적, 상대전적
   → 모두 Elo 점수(±)로 바꿔 더한다. 근거가 적은 요인은 표본 수에 따라 0 쪽으로 줄인다
3. 축구·하키: 포아송 득점 모델과 섞어 승무패, 예상 스코어, 언더/오버, 양팀 득점 확률을 낸다
4. 농구: 예상 점수차·총점
5. 백테스트: 경기 전 시점 Elo만으로 예측했을 때의 적중률·브라이어 점수
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .espn import inj_ko

KST = timezone(timedelta(hours=9))

SPORT = {
    #            K   홈이점 득실보정 무승부 연전패널티 부상스케일 점수차분모
    "basketball": dict(k=20, hfa=70, mov=True, draw=False, b2b=45, inj=1.0, margin_div=28),
    "hockey":     dict(k=10, hfa=35, mov=True, draw=False, b2b=25, inj=0.6, margin_div=None),
    "soccer":     dict(k=20, hfa=60, mov=True, draw=True,  b2b=0,  inj=0.5, margin_div=None),
    "baseball":   dict(k=6,  hfa=24, mov=False, draw=False, b2b=0, inj=0.4, margin_div=None),
    "volleyball": dict(k=24, hfa=40, mov=False, draw=False, b2b=20, inj=0.6, margin_div=None),
}
WD = "월화수목금토일"


def _dt(s):
    s = s.replace("Z", "+00:00")
    if len(s) == 22:
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s)


def expected(diff):
    return 1 / (1 + 10 ** (-diff / 400))


def three_way(diff):
    p = expected(diff)
    draw = max(0.16, 0.28 - 0.35 * abs(p - 0.5))
    return p * (1 - draw), draw, (1 - p) * (1 - draw)


def poisson(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_matrix(lh, la, n=9):
    return [[poisson(lh, i) * poisson(la, j) for j in range(n)] for i in range(n)]


CARRY = 0.7   # 지난 시즌 전력의 70%를 이어받는다


class League:
    def __init__(self, sport, games, prev_games=None):
        self.sport = sport
        self.cfg = SPORT.get(sport, SPORT["basketball"])
        self.games = sorted(games, key=lambda g: g["date"])
        self.elo = {}
        self.default = 1500.0
        self.has_prior = False
        self.pre = {}                      # 경기 id → 경기 전 홈 승리 확률(백테스트용)
        self.team_games = defaultdict(list)
        if prev_games:
            self._prior(sorted(prev_games, key=lambda g: g["date"]))
        self._run()

    def _prior(self, prev):
        """지난 시즌을 돌려 시작 전력을 만든다. 처음 보는 팀(승격팀)은 지난 시즌 하위 3팀 평균에서 출발."""
        self._run(prev, record=False)
        if not self.elo:
            return
        vals = sorted(self.elo.values())
        self.default = 1500 + (sum(vals[:3]) / len(vals[:3]) - 1500) * CARRY
        self.elo = {t: 1500 + (r - 1500) * CARRY for t, r in self.elo.items()}
        self.has_prior = True

    # ---------- Elo ----------
    def _run(self, games=None, record=True):
        c = self.cfg
        for g in (self.games if games is None else games):
            h, a = g["home"], g["away"]
            self.elo.setdefault(h, self.default)
            self.elo.setdefault(a, self.default)
            diff = self.elo[h] + c["hfa"] - self.elo[a]
            e = expected(diff)
            res = 1.0 if g["hs"] > g["as"] else 0.0 if g["hs"] < g["as"] else 0.5
            if record:
                self.pre[g["id"]] = (e, diff, res)
            mult = 1.0
            if c["mov"]:
                m = abs(g["hs"] - g["as"])
                if self.sport == "soccer":
                    mult = 1 if m <= 1 else 1.5 if m == 2 else (11 + m) / 8
                elif self.sport == "basketball":
                    wd = diff if res == 1 else -diff
                    mult = ((m + 3) ** 0.8) / (7.5 + 0.006 * wd)
                else:
                    mult = 1 + 0.25 * max(0, m - 1)
            delta = c["k"] * mult * (res - e)
            self.elo[h] += delta
            self.elo[a] -= delta
            if not record:
                continue
            post = {"date": g["date"], "pre_e": e}
            self.team_games[h].append({**post, "home": True, "opp": a, "gf": g["hs"], "ga": g["as"], "res": res, "exp": e})
            self.team_games[a].append({**post, "home": False, "opp": h, "gf": g["as"], "ga": g["hs"], "res": 1 - res, "exp": 1 - e})

    def rank(self, tid):
        order = sorted(self.elo, key=lambda t: -self.elo[t])
        return order.index(tid) + 1 if tid in order else None, len(order)

    # ---------- 백테스트 ----------
    def backtest(self, warmup=3):
        """각 팀이 warmup 경기 이상 치른 뒤의 경기만 채점 (지난 시즌 전력이 있으면 첫 경기부터)."""
        if self.has_prior:
            warmup = 0
        played = defaultdict(int)
        n = hit = 0
        brier = 0.0
        for g in self.games:
            e, diff, res = self.pre[g["id"]]
            ok = played[g["home"]] >= warmup and played[g["away"]] >= warmup
            played[g["home"]] += 1
            played[g["away"]] += 1
            if not ok:
                continue
            if self.cfg["draw"]:
                ph, pd, pa = three_way(diff)
                pick = max((ph, 1.0), (pd, 0.5), (pa, 0.0))[1]
                actual = [1 if res == 1 else 0, 1 if res == 0.5 else 0, 1 if res == 0 else 0]
                brier += sum((p - o) ** 2 for p, o in zip((ph, pd, pa), actual)) / 3
            else:
                pick = 1.0 if e >= 0.5 else 0.0
                brier += (e - res) ** 2
            hit += pick == res
            n += 1
        return {"n": n, "acc": hit / n if n else None, "brier": brier / n if n else None}

    # ---------- 팀 통계 ----------
    def team_stats(self, tid):
        tg = self.team_games.get(tid, [])
        def rate(lst):
            return sum(x["res"] for x in lst) / len(lst) if lst else None
        home = [x for x in tg if x["home"]]
        away = [x for x in tg if not x["home"]]
        return {
            "n": len(tg), "win": rate(tg), "home_n": len(home), "home_win": rate(home),
            "away_n": len(away), "away_win": rate(away),
            "gf": sum(x["gf"] for x in tg) / len(tg) if tg else None,
            "ga": sum(x["ga"] for x in tg) / len(tg) if tg else None,
            "home_gf": sum(x["gf"] for x in home) / len(home) if home else None,
            "home_ga": sum(x["ga"] for x in home) / len(home) if home else None,
            "away_gf": sum(x["gf"] for x in away) / len(away) if away else None,
            "away_ga": sum(x["ga"] for x in away) / len(away) if away else None,
            "last": tg[-10:],
        }

    def league_avgs(self):
        if not self.games:
            return None, None
        return (sum(g["hs"] for g in self.games) / len(self.games), sum(g["as"] for g in self.games) / len(self.games))


def shrink(value, n, k):
    return value * n / (n + k)


def last_game_date(tid, all_team_dates, before):
    ds = [d for d in all_team_dates.get(tid, []) if d < before]
    return max(ds) if ds else None


def injury_points(items, leaders, scale):
    """Out 선수: 주축(시즌 팀 내 1위 기록 보유) 35점, 일반 8점. 출전 의문은 절반 미만."""
    pts, notes = 0.0, []
    for i in items or []:
        st = (i.get("status") or "").lower()
        w = 1.0 if st in ("out", "injured reserve", "suspension") or "out" in st else 0.35 if st else 0.5
        star = i.get("name") in (leaders or {})
        base = 35 if star else 8
        pts += base * w
        if star and w >= 0.35:
            notes.append(f"{i.get('name')}({', '.join(leaders[i['name']][:1])}) {inj_ko(i.get('status'))}")
    return min(pts * scale, 90), notes


def analyze(game, lg, all_team_dates):
    """경기 하나의 승률·요인·코멘트를 만든다. lg: League, all_team_dates: 팀 → 경기 날짜 목록(모든 대회)."""
    c = lg.cfg
    h, a = game["home"].get("id"), game["away"].get("id")
    if not h or not a:
        return None
    start = _dt(game["start_utc"])
    hs, as_ = lg.team_stats(h), lg.team_stats(a)
    factors = []

    def add(key, label, pts, text):
        factors.append({"key": key, "label": label, "pts": round(pts, 1), "text": text})

    eh_, ea_ = lg.elo.get(h, lg.default), lg.elo.get(a, lg.default)
    base_diff = eh_ - ea_
    add("elo", "시즌 전력(Elo)", base_diff, f"전력 점수 {eh_:.0f} 대 {ea_:.0f}" + (" (지난 시즌 70% 반영)" if lg.has_prior else ""))
    add("home", "홈 이점(리그 평균)", c["hfa"], "리그 평균 홈 이점")

    # 홈/원정 성적 차이
    if hs["home_win"] is not None and as_["away_win"] is not None and hs["win"] is not None and as_["win"] is not None:
        sh = shrink(hs["home_win"] - hs["win"], hs["home_n"], 8)
        sa = shrink(as_["away_win"] - as_["win"], as_["away_n"], 8)
        pts = max(-35, min(35, (sh - sa) * 200))
        add("split", "홈·원정 성적", pts,
            f"홈팀 홈 승률 {hs['home_win'] * 100:.0f}%({hs['home_n']}경기), 원정팀 원정 승률 {as_['away_win'] * 100:.0f}%({as_['away_n']}경기)")

    # 휴식일
    def rest_days(tid):
        d = last_game_date(tid, all_team_dates, start)
        return (start - d).total_seconds() / 86400 if d else None
    rh, ra = rest_days(h), rest_days(a)
    def rest_pen(r):
        if r is None:
            return 0
        if r < 1.6 and c["b2b"]:
            return c["b2b"]          # 연전(백투백)
        if lg.sport == "soccer" and r < 3.6:
            return 15                # 주중·주말 연속 경기
        return 0
    rp = rest_pen(ra) - rest_pen(rh)
    if rh is not None or ra is not None:
        fmt = lambda r: f"{r:.0f}일" if r is not None else "정보 없음"
        add("rest", "휴식일·일정", rp, f"직전 경기 후 홈팀 {fmt(rh)}, 원정팀 {fmt(ra)}")

    # 부상
    inj = game.get("injuries") or {}
    leaders = game.get("leaders") or {}
    ih, nh = injury_points(inj.get(h), leaders.get(h), c["inj"])
    ia, na = injury_points(inj.get(a), leaders.get(a), c["inj"])
    if inj:
        add("injury", "부상·결장", ia - ih,
            f"홈팀 {len(inj.get(h) or [])}명, 원정팀 {len(inj.get(a) or [])}명" + (f" · 주축: {'; '.join(nh + na)}" if nh or na else ""))

    # 최근 흐름 (기대 대비 실제)
    def momentum(tg):
        last = tg[-5:]
        if not last:
            return 0, ""
        over = sum(x["res"] - x["exp"] for x in last)
        rec = "".join("승" if x["res"] == 1 else "패" if x["res"] == 0 else "무" for x in last)
        return over, rec
    mh, rech = momentum(hs["last"])
    ma, reca = momentum(as_["last"])
    pts = max(-20, min(20, (mh - ma) * 12))
    if rech or reca:
        add("form", "최근 5경기 흐름", pts, f"홈팀 {rech or '-'}, 원정팀 {reca or '-'} (기대 대비 홈 {mh:+.1f}승, 원정 {ma:+.1f}승)")

    # 요일
    wd = start.astimezone(KST).weekday()
    def wd_edge(tid, overall):
        lst = [x for x in lg.team_games.get(tid, []) if _dt(x["date"]).astimezone(KST).weekday() == wd]
        if not lst or overall is None:
            return 0, 0, None
        r = sum(x["res"] for x in lst) / len(lst)
        return shrink(r - overall, len(lst), 10), len(lst), r
    eh, nwh, rwh = wd_edge(h, hs["win"])
    ea, nwa, rwa = wd_edge(a, as_["win"])
    if nwh or nwa:
        pts = max(-12, min(12, (eh - ea) * 100))
        fr = lambda r, n: f"{r * 100:.0f}%({n}경기)" if r is not None else "기록 없음"
        add("weekday", f"{WD[wd]}요일 성적", pts, f"{WD[wd]}요일 홈팀 {fr(rwh, nwh)}, 원정팀 {fr(rwa, nwa)}")

    # 상대전적
    h2h = [x for x in lg.team_games.get(h, []) if x["opp"] == a]
    if h2h:
        over = sum(x["res"] - x["exp"] for x in h2h)
        pts = max(-15, min(15, shrink(over / len(h2h), len(h2h), 3) * 60))
        w = sum(1 for x in h2h if x["res"] == 1)
        l = sum(1 for x in h2h if x["res"] == 0)
        d = len(h2h) - w - l
        add("h2h", "이번 시즌 상대전적", pts, f"홈팀 기준 {w}승" + (f" {d}무" if d else "") + f" {l}패")

    total = sum(f["pts"] for f in factors)
    out = {"factors": factors, "diff": round(total, 1)}
    n_min = min(hs["n"], as_["n"])
    out["confidence"] = "낮음" if n_min < 5 else "보통" if n_min < 15 else "높음"
    out["games_used"] = n_min
    out["prior"] = lg.has_prior
    if lg.has_prior and out["confidence"] == "낮음":
        out["confidence"] = "보통"

    if lg.sport in ("soccer", "hockey"):
        mh_, ma_ = lg.league_avgs()
        k = 4
        def rate(v, n, avg):
            return ((v or 0) * n + avg * k) / (n + k) / avg if avg else 1
        lam_h = mh_ * rate(hs["home_gf"], hs["home_n"], mh_) * rate(as_["away_ga"], as_["away_n"], mh_) if mh_ else None
        lam_a = ma_ * rate(as_["away_gf"], as_["away_n"], ma_) * rate(hs["home_ga"], hs["home_n"], ma_) if ma_ else None
        if lam_h and lam_a:
            adj = 10 ** ((total - base_diff - c["hfa"]) / 1600)   # 요인 조정을 득점 기대값에 반영
            lam_h, lam_a = lam_h * adj, lam_a / adj
            m = score_matrix(lam_h, lam_a)
            ph = sum(m[i][j] for i in range(9) for j in range(9) if i > j)
            pd = sum(m[i][i] for i in range(9))
            pa = 1 - ph - pd
            top = sorted(((m[i][j], f"{i}-{j}") for i in range(6) for j in range(6)), reverse=True)[:3]
            out["xg"] = (round(lam_h, 2), round(lam_a, 2))
            out["top_scores"] = [(s, round(p, 3)) for p, s in top]
            line = 2.5 if lg.sport == "soccer" else 5.5
            out["ou_line"] = line
            out["over"] = round(sum(m[i][j] for i in range(9) for j in range(9) if i + j > line), 3)
            out["btts"] = round(sum(m[i][j] for i in range(1, 9) for j in range(1, 9)), 3)
            if lg.sport == "soccer":
                eh_, ed_, ea_ = three_way(total)
                out["prob"] = {"home": round((ph + eh_) / 2, 3), "draw": round((pd + ed_) / 2, 3), "away": round((pa + ea_) / 2, 3)}
            else:
                pe = expected(total)
                ot = pd * pe   # 정규시간 동점이면 연장·승부치기에서 Elo 확률로 배분
                p_home = (ph + ot + pe) / 2
                out["prob"] = {"home": round(p_home, 3), "away": round(1 - p_home, 3)}
    if "prob" not in out:
        if c["draw"]:
            ph, pd, pa = three_way(total)
            out["prob"] = {"home": round(ph, 3), "draw": round(pd, 3), "away": round(pa, 3)}
        else:
            p = expected(total)
            out["prob"] = {"home": round(p, 3), "away": round(1 - p, 3)}
    if lg.sport == "basketball" and hs["gf"] and as_["gf"]:
        tot = (hs["gf"] + as_["ga"] + as_["gf"] + hs["ga"]) / 2
        margin = total / c["margin_div"]
        out["exp_score"] = (round(tot / 2 + margin / 2), round(tot / 2 - margin / 2))
        out["exp_total"] = round(tot, 1)
        out["exp_margin"] = round(margin, 1)
    return out


def comment(game, an, ko):
    """요인 기여도가 큰 순서로 한국어 분석 코멘트를 만든다."""
    if not an:
        return []
    H, A = ko(game["home"]["name"]), ko(game["away"]["name"])
    p = an["prob"]
    lines = []
    fav, fp = (H, p["home"]) if p["home"] >= p["away"] else (A, p["away"])
    cut = (0.60, 0.48, 0.40) if "draw" in p else (0.68, 0.58, 0.53)
    tone = "뚜렷한 우세" if fp >= cut[0] else "우세" if fp >= cut[1] else "근소한 우세" if fp >= cut[2] else "박빙"
    if tone == "박빙":
        lines.append(f"두 팀 승리 확률이 {p['home'] * 100:.0f}% 대 {p['away'] * 100:.0f}%로 박빙입니다.")
    else:
        lines.append(f"{fav}의 승리 확률 {fp * 100:.0f}%로 {tone}입니다." + (f" 무승부는 {p['draw'] * 100:.0f}%입니다." if "draw" in p else ""))
    key = [f for f in an["factors"] if f["key"] not in ("elo", "home")]
    key.sort(key=lambda f: -abs(f["pts"]))
    for f in key[:3]:
        if abs(f["pts"]) < 3:
            continue
        side = H if f["pts"] > 0 else A
        lines.append(f"{f['label']}은 {side} 쪽에 유리합니다({f['pts']:+.0f}점). {f['text']}.")
    if an.get("xg"):
        ts = ", ".join(s for s, _ in an["top_scores"])
        lines.append(f"예상 득점은 {H} {an['xg'][0]:.1f}골, {A} {an['xg'][1]:.1f}골이며 가능성 높은 스코어는 {ts} 순입니다.")
        lines.append(f"{an['ou_line']} 기준 오버 확률 {an['over'] * 100:.0f}%, 양 팀 모두 득점 확률 {an['btts'] * 100:.0f}%입니다.")
    if an.get("exp_score"):
        lines.append(f"예상 점수는 {H} {an['exp_score'][0]} : {an['exp_score'][1]} {A}, 총점 약 {an['exp_total']:.0f}점입니다.")
    if an["confidence"] == "낮음" and not an.get("prior"):
        lines.append(f"시즌 초반이라 표본이 {an['games_used']}경기뿐이어서 신뢰도는 낮습니다.")
    return lines
