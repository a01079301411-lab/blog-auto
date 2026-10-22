"""무음 구간 탐지와 남길 구간 계산."""
from __future__ import annotations

import re
import subprocess

from .media import NO_WINDOW, Segment

_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: (-?[\d.]+)")


def detect_silences(
    path: str,
    *,
    noise_db: float = -35.0,
    min_silence: float = 0.5,
    start: float | None = None,
    end: float | None = None,
) -> list[Segment]:
    """FFmpeg silencedetect로 무음 구간(원본 기준 초)을 찾는다."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    offset = 0.0
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
        offset = start
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", path, "-vn",
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-"]
    stderr = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW).stderr

    silences: list[Segment] = []
    cur: float | None = None
    for line in stderr.splitlines():
        if m := _START.search(line):
            cur = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) and cur is not None:
            silences.append((cur + offset, float(m.group(1)) + offset))
            cur = None
    if cur is not None:  # 끝까지 무음으로 끝난 경우
        silences.append((cur + offset, end if end is not None else float("inf")))
    return silences


def keep_segments(
    silences: list[Segment],
    start: float,
    end: float,
    *,
    padding: float = 0.15,
    min_keep: float = 0.25,
) -> list[Segment]:
    """[start, end] 범위에서 무음을 뺀 구간을 돌려준다.

    말이 갑자기 잘리지 않도록 무음 구간 양끝을 padding만큼 남긴다.
    """
    keeps: list[Segment] = []
    cursor = start
    for s, e in sorted(silences):
        s, e = max(s + padding, start), min(e - padding, end)
        if e <= s:
            continue  # 패딩을 빼면 무음이 남지 않음
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < end:
        keeps.append((cursor, end))
    return [(s, e) for s, e in keeps if e - s >= min_keep]


def split_points(
    silences: list[Segment],
    total: float,
    chunk_len: float,
    *,
    search: float = 60.0,
) -> list[float]:
    """약 chunk_len 간격으로, 가능하면 무음 한가운데에서 자를 지점을 고른다."""
    mids = [(s + e) / 2 for s, e in silences if e != float("inf")]
    cuts: list[float] = []
    target = chunk_len
    while target < total - chunk_len * 0.5:
        near = [m for m in mids if abs(m - target) <= search and (not cuts or m > cuts[-1])]
        cut = min(near, key=lambda m: abs(m - target)) if near else target
        cuts.append(cut)
        target = cut + chunk_len
    return cuts


FILLERS = {"음", "어", "으", "엄", "흠", "음음", "어어", "으음", "어음"}


def drop_fillers(keeps: list[Segment], words) -> list[Segment]:
    """캡컷 '군말 삭제'처럼: '음', '어' 같은 군말만 있는 단어를 잘라낸다."""
    cuts = []
    for w in words:
        if re.sub(r"[\s.,?!~…]", "", w.text) in FILLERS and w.end - w.start >= 0.12:
            cuts.append((w.start + 0.02, w.end - 0.02))
    if not cuts:
        return keeps
    out: list[Segment] = []
    for s, e in keeps:
        cur = s
        for a, b in cuts:
            if b <= cur or a >= e:
                continue
            if a - cur >= 0.15:
                out.append((cur, a))
            cur = max(cur, b)
        if e - cur >= 0.15:
            out.append((cur, e))
    return out or keeps
