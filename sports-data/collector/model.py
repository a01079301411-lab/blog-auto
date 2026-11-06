"""시즌 성적만으로 계산하는 기본 확률(베타).

전적이 적을 때 극단값이 나오지 않도록 5할에 가깝게 끌어당긴 뒤 log5 + 홈 이점으로 계산한다.
정밀 모델(Elo, 포아송)로 바꾸기 전까지 '참고용 기본 확률'로만 표기한다.
"""

HOME_EDGE = {"soccer": 0.06, "basketball": 0.05, "hockey": 0.03, "baseball": 0.03}
PRIOR_GAMES = 5


def _strength(record, sport):
    if not record:
        return None
    try:
        parts = [int(x) for x in record.split("-")]
    except ValueError:
        return None
    if sport == "soccer" and len(parts) == 3:
        w, d, l = parts
        points, games = w + 0.5 * d, w + d + l
    else:
        w, l = parts[0], parts[1]
        otl = parts[2] if len(parts) > 2 else 0  # NHL 연장패
        points, games = w + 0.5 * otl, w + l + otl
    return (points + 0.5 * PRIOR_GAMES) / (games + PRIOR_GAMES)


def probabilities(game):
    sport = game["sport"]
    h = _strength(game["home"].get("record"), sport)
    a = _strength(game["away"].get("record"), sport)
    if h is None or a is None:
        return None
    p = h * (1 - a) / (h * (1 - a) + a * (1 - h))
    p = min(max(p + HOME_EDGE.get(sport, 0.03), 0.05), 0.95)
    if sport == "soccer":
        draw = max(0.18, 0.28 - 0.25 * abs(p - 0.5))
        return {"home": round(p * (1 - draw), 3), "draw": round(draw, 3), "away": round((1 - p) * (1 - draw), 3)}
    return {"home": round(p, 3), "away": round(1 - p, 3)}
