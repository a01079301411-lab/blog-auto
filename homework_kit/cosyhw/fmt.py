"""수치 표기 규칙 (스펙 3장): 1만 이상 '3.4만', 미만 '9,627'."""
from __future__ import annotations

import re


def fmt_count(n) -> str:
    if n is None:
        return "미확인"
    n = int(n)
    if n >= 100_000_000:
        v = n / 100_000_000
        return f"{v:.1f}".rstrip("0").rstrip(".") + "억"
    if n >= 10_000:
        v = n / 10_000
        s = f"{v:.1f}" if v < 100 else f"{v:.0f}"
        return s.rstrip("0").rstrip(".") + "만"
    return f"{n:,}"


def parse_count(text) -> int | None:
    """'3.4만', '1.2천', '9,627', '12K', '1.5M', '조회수 96만회' → 정수."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(억|만|천|[KkMmBb])?", s)
    if not m:
        return None
    v = float(m.group(1))
    mul = {"억": 1e8, "만": 1e4, "천": 1e3, "k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
    return int(round(v * mul))


def vs_recent(target: int, recent: list[int]) -> dict:
    """평소 대비: 최근 N개 평균·중앙값과 배수."""
    vals = [int(x) for x in recent if x is not None]
    if not vals:
        return {"error": "최근 수치가 없음"}
    avg = sum(vals) / len(vals)
    srt = sorted(vals)
    mid = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
    mult = target / avg if avg else None
    return {
        "n": len(vals),
        "recent": [fmt_count(v) for v in vals],
        "avg": fmt_count(avg),
        "median": fmt_count(mid),
        "multiple_vs_avg": round(mult, 1) if mult else None,
        "sentence": f"최근 {len(vals)}개 평균 약 {fmt_count(avg)}의 약 {mult:.1f}배" if mult else "",
    }
