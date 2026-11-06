"""리그별 시즌 경기 기록 저장소.

- 전체 갱신: 팀별 시즌 일정을 모두 받아 합친다 (12시간마다)
- 증분 갱신: 매 실행마다 스코어보드에서 끝난 경기를 추가한다
"""
import json
import os
from datetime import datetime, timedelta, timezone

from . import espn

FULL_REFRESH = timedelta(hours=12)


def _path(root, key):
    return os.path.join(root, "data", "history", f"{key}.json")


def load(root, key):
    try:
        with open(_path(root, key), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"updated": None, "games": {}}


def save(root, key, hist):
    p = _path(root, key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def refresh_espn(root, league, now, log):
    hist = load(root, league["key"])
    stale = not hist["updated"] or now - datetime.fromisoformat(hist["updated"]) > FULL_REFRESH
    if not stale:
        return hist
    try:
        ids = espn.team_ids(league)
    except Exception as e:
        log(f"{league['key']} 팀 목록 실패: {e}")
        return hist
    n = 0
    for tid in ids:
        try:
            for g in espn.team_schedule(league, tid):
                hist["games"][g["id"]] = g
                n += 1
        except Exception as e:
            log(f"{league['key']} 팀 {tid} 일정 실패: {e}")
    hist["updated"] = now.isoformat(timespec="seconds")
    save(root, league["key"], hist)
    log(f"{league['key']} 시즌 기록 전체 갱신: {len(hist['games'])}경기")
    return hist


def merge_finished(root, key, games):
    """오늘 스코어보드에서 끝난 경기를 기록에 더한다."""
    hist = load(root, key)
    added = 0
    for g in games:
        if g["state"] != "post" or g["id"] in hist["games"]:
            continue
        try:
            hs, as_ = int(g["home"]["score"]), int(g["away"]["score"])
        except (TypeError, ValueError):
            continue
        hist["games"][g["id"]] = {"id": g["id"], "date": g["start_utc"], "home": g["home"]["id"], "away": g["away"]["id"],
                                  "home_name": g["home"]["name"], "away_name": g["away"]["name"], "hs": hs, "as": as_}
        added += 1
    if added:
        save(root, key, hist)
    return hist


def refresh_prev(root, league, log):
    """지난 시즌 기록. 한 번 받으면 다시 받지 않는다.
    승격팀의 하부리그 경기는 상대팀 등장 횟수가 적어 걸러진다."""
    if not league.get("prev_season"):
        return []
    key = f"{league['key']}_prev{league['prev_season']}"
    hist = load(root, key)
    if hist["games"]:
        return list(hist["games"].values())
    try:
        ids = espn.team_ids(league)
    except Exception as e:
        log(f"{league['key']} 지난 시즌 팀 목록 실패: {e}")
        return []
    raw = {}
    for tid in ids:
        try:
            for g in espn.team_schedule(league, tid, league["prev_season"]):
                raw[g["id"]] = g
        except Exception as e:
            log(f"{league['key']} 지난 시즌 {tid} 실패: {e}")
    count = {}
    for g in raw.values():
        for t in (g["home"], g["away"]):
            count[t] = count.get(t, 0) + 1
    hist["games"] = {k: g for k, g in raw.items() if count[g["home"]] >= 10 and count[g["away"]] >= 10}
    hist["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(root, key, hist)
    log(f"{league['key']} 지난 시즌 기록: {len(hist['games'])}경기")
    return list(hist["games"].values())
