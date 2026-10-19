"""성과 학습: 만든 숏폼과 그 성과(조회수, 시청 지속률)를 기록하고, 다음 하이라이트를 고를 때
잘된 숏폼의 공통점은 따라 하고 안된 숏폼의 공통점은 피하게 한다.

- 숏폼을 만들 때마다 프로그램 폴더의 '성과기록.csv'에 한 줄씩 적는다 (엑셀로 열린다).
- 올린 뒤 조회수, 평균 시청률(%), 좋아요, 링크 칸을 채워 두면 된다.
  링크가 유튜브 쇼츠이고 유튜브 연결(client_secret.json)이 되어 있으면 조회수·좋아요는
  프로그램이 알아서 가져온다.
- 성과가 3개 이상 쌓이면 다음 숏폼부터 반영한다.
"""
from __future__ import annotations

import csv
import os
import re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(ROOT, "성과기록.csv")
COLUMNS = ["날짜", "파일", "제목", "훅 자막", "길이(초)", "영상 종류", "계정", "분위기",
           "조회수", "평균 시청률(%)", "좋아요", "링크"]
MIN_ROWS = 3


def _read() -> list[dict]:
    try:
        with open(FILE, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def _write(rows: list[dict]) -> None:
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, FILE)


def ensure_file() -> str:
    if not os.path.exists(FILE):
        _write([])
    return FILE


def record(path: str, *, title: str, hook: str, seconds: float, guide: str, account: str,
           mood: str) -> None:
    """만든 숏폼을 기록한다 (같은 파일이면 덮어쓴다). 엑셀이 파일을 열고 있으면 건너뛴다."""
    try:
        rows = [r for r in _read() if r.get("파일") != path]
        rows.append({"날짜": date.today().isoformat(), "파일": path,
                     "제목": title.replace("\n", " ").replace("{", "").replace("}", ""),
                     "훅 자막": hook, "길이(초)": f"{seconds:.0f}", "영상 종류": guide,
                     "계정": account, "분위기": mood})
        _write(rows)
    except OSError as e:
        print(f"  (성과기록.csv에 적지 못했어요. 엑셀로 열려 있으면 닫아 주세요: {e})")


def _num(text) -> float:
    m = re.search(r"\d[\d,]*(\.\d+)?", str(text or ""))
    return float(m.group().replace(",", "")) if m else 0.0


def fetch_youtube() -> int:
    """링크가 유튜브인 줄의 조회수·좋아요를 가져온다. 가져온 개수 (설정이 안 되어 있으면 0)."""
    rows = _read()
    ids = {}
    for r in rows:
        m = re.search(r"(?:shorts/|v=|youtu\.be/)([\w-]{11})", r.get("링크", ""))
        if m:
            ids[m.group(1)] = r
    if not ids:
        return 0
    try:
        from . import youtube
        if not os.path.exists(youtube.CLIENT_SECRET):
            return 0
        stats = youtube.statistics(list(ids))
    except Exception as e:
        print(f"  (유튜브 조회수를 가져오지 못했어요: {e})")
        return 0
    for vid, s in stats.items():
        ids[vid]["조회수"] = s.get("viewCount", ids[vid].get("조회수", ""))
        ids[vid]["좋아요"] = s.get("likeCount", ids[vid].get("좋아요", ""))
    _write(rows)
    return len(stats)


def lessons(guide: str = "") -> str:
    """Claude에게 줄 '지난 숏폼 성과' 글. 성과가 부족하면 빈 글."""
    rows = [r for r in _read() if _num(r.get("조회수")) > 0 or _num(r.get("평균 시청률(%)")) > 0]
    same = [r for r in rows if r.get("영상 종류") == guide]
    if len(same) >= MIN_ROWS:
        rows = same
    if len(rows) < MIN_ROWS:
        return ""
    views = [_num(r.get("조회수")) for r in rows]
    top_views = max(views) or 1

    def score(r):  # 조회수와 시청률을 반반 (시청률이 없으면 조회수만)
        v = _num(r.get("조회수")) / top_views
        ret = _num(r.get("평균 시청률(%)"))
        return 0.5 * v + 0.5 * ret / 100 if ret else v

    rows.sort(key=score, reverse=True)
    k = min(5, max(1, len(rows) // 2))
    best, worst = rows[:k], rows[-min(3, len(rows) - k):] if len(rows) > k else []

    def line(r):
        parts = [f"title: {r.get('제목', '')}", f"hook: {r.get('훅 자막', '')}",
                 f"length {r.get('길이(초)', '')}s", f"views {r.get('조회수', '') or '?'}"]
        if r.get("평균 시청률(%)"):
            parts.append(f"avg watched {r['평균 시청률(%)']}%")
        return "- " + " / ".join(parts)

    text = ["How this creator's past shorts performed. Learn the pattern: pick moments, hooks,",
            "titles and lengths like the best ones and avoid what the worst ones have in common.",
            "Best:"] + [line(r) for r in best]
    if worst:
        text += ["Worst:"] + [line(r) for r in worst]
    return "\n".join(text)
