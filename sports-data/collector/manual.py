"""국내 리그·프로토 회차 수동 입력(CSV).

국내 리그 공식 사이트와 베트맨은 해외 IP에서 막히거나 공개 API가 없어,
처음에는 CSV로 입력하고 같은 화면에 함께 보여준다.
"""
import csv
import os
from datetime import datetime, timedelta

SPORT_BY_LEAGUE = {
    "KBL": "basketball", "WKBL": "basketball", "V리그 남자": "volleyball", "V리그 여자": "volleyball",
    "K리그1": "soccer", "K리그2": "soccer", "KBO": "baseball",
}


def load_domestic(path):
    """date,time,league,home,away,venue,note → 경기 목록 (시각은 KST)."""
    if not os.path.exists(path):
        return []
    games = []
    with open(path, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if not row.get("date") or row["date"].startswith("#"):
                continue
            hh, mm = (row.get("time") or "00:00").split(":")
            kst = datetime.strptime(f"{row['date']} {hh}:{mm}", "%Y-%m-%d %H:%M")
            utc = kst - timedelta(hours=9)
            league = row.get("league", "").strip()
            games.append({
                "id": f"kr-{row['date']}-{i}",
                "league": "kr",
                "league_name": league,
                "sport": SPORT_BY_LEAGUE.get(league, "etc"),
                "start_utc": utc.strftime("%Y-%m-%dT%H:%MZ"),
                "state": "pre",
                "status_detail": "예정",
                "home": {"name": row.get("home", "").strip(), "id": None},
                "away": {"name": row.get("away", "").strip(), "id": None},
                "venue": row.get("venue"),
                "note": row.get("note"),
                "source": "수동 입력",
            })
    return games


def load_proto(path):
    """round,game_no,date,time,league,type,home,away,odd_win,odd_draw,odd_lose (베트맨 공식 배당을 옮겨 적음)."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row.get("round") or row["round"].startswith("#"):
                continue
            for k in ("odd_win", "odd_draw", "odd_lose"):
                try:
                    row[k] = float(row[k]) if row.get(k) else None
                except ValueError:
                    row[k] = None
            rows.append(row)
    return rows
