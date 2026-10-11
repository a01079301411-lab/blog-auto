"""단어 타임스탬프 → 자막 cue 생성, 컷 편집에 맞춘 시간 재계산, SRT 저장."""
from __future__ import annotations

from dataclasses import dataclass

from .media import Segment


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str


def words_in_range(words: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in words if start <= (w.start + w.end) / 2 <= end]


def remap(words: list[Word], keeps: list[Segment]) -> list[Word]:
    """원본 시간의 단어를 컷 편집 후 타임라인 시간으로 옮긴다.

    잘려나간 구간에 있는 단어는 버린다.
    """
    out: list[Word] = []
    for w in words:
        mid = (w.start + w.end) / 2
        offset = 0.0
        for s, e in keeps:
            if s <= mid <= e:
                ns = offset + max(w.start, s) - s
                ne = offset + min(w.end, e) - s
                out.append(Word(ns, ne, w.text))
                break
            offset += e - s
    return out


def build_cues(
    words: list[Word],
    *,
    max_chars: int = 16,
    max_duration: float = 2.5,
    max_gap: float = 0.5,
) -> list[Cue]:
    """단어들을 화면에 띄울 짧은 자막 덩어리로 묶는다."""
    cues: list[Cue] = []
    cur: list[Word] = []

    def flush() -> None:
        if cur:
            text = "".join(w.text for w in cur).strip()
            if text:
                cues.append(Cue(cur[0].start, cur[-1].end, text))
            cur.clear()

    for w in words:
        if cur:
            text_len = len("".join(x.text for x in cur + [w]).strip())
            if (text_len > max_chars
                    or w.end - cur[0].start > max_duration
                    or w.start - cur[-1].end > max_gap):
                flush()
        cur.append(w)
        if w.text.rstrip().endswith((".", "?", "!", "。")):
            flush()
    flush()

    # 다음 자막과 겹치지 않게 하되, 너무 빨리 사라지지 않도록 살짝 늘린다
    for a, b in zip(cues, cues[1:]):
        a.end = min(max(a.end, a.start + 0.6), b.start)
    return cues


def _ts(t: float) -> str:
    ms = round(max(t, 0) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(cues: list[Cue], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text}\n\n")
