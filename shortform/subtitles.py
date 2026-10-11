"""단어 타임스탬프 → 자막 cue 생성, 컷 편집에 맞춘 시간 재계산, SRT 저장."""
from __future__ import annotations

import re
from bisect import bisect_right
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
    starts = [s for s, _ in keeps]
    offsets = [0.0]
    for s, e in keeps:
        offsets.append(offsets[-1] + e - s)

    out: list[Word] = []
    for w in words:
        i = bisect_right(starts, (w.start + w.end) / 2) - 1
        if i < 0:
            continue
        s, e = keeps[i]
        if (w.start + w.end) / 2 > e:
            continue  # 잘려나간 구간
        out.append(Word(offsets[i] + max(w.start, s) - s,
                        offsets[i] + min(w.end, e) - s, w.text))
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


# ---- 세로 숏폼용 ASS 자막 (상단 제목 + 키워드 강조) ----

YELLOW = r"{\c&H00E5FF&}"  # ASS 색상은 &HBBGGRR& 순서
RESET = r"{\r}"


def _ass_ts(t: float) -> str:
    cs = round(max(t, 0) * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")")


def _highlight(text: str, keywords: list[str]) -> str:
    text = _ass_escape(text)
    kws = sorted({_ass_escape(k.strip()) for k in keywords if k.strip()}, key=len, reverse=True)
    if not kws:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in kws))
    return pattern.sub(lambda m: f"{YELLOW}{m.group(0)}{RESET}", text)


def write_ass(
    cues: list[Cue],
    path: str,
    *,
    duration: float,
    font: str,
    title: str = "",
    keywords: list[str] | None = None,
    video_top: int = 656,
    video_bottom: int = 1264,
    subs_below_video: bool = True,
) -> None:
    """1080x1920 세로 영상용 자막 파일.

    title이 있으면 영상 위쪽에 두 줄 제목(둘째 줄 노란색)을 띄우고,
    자막은 영상 바로 아래에 크게 넣으며 keywords를 노란색으로 강조한다.
    """
    sub_align, sub_margin = (8, video_bottom + 50) if subs_below_video else (2, 380)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{font},74,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,6,0,{sub_align},70,70,{sub_margin},1",
        f"Style: Title,{font},96,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,7,0,2,50,50,{1920 - video_top + 60},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title.strip():
        parts = [_ass_escape(p.strip()) for p in title.strip().split("\n") if p.strip()]
        if len(parts) > 1:  # 마지막 줄을 노란색 펀치라인으로
            parts[-1] = YELLOW + parts[-1]
        lines.append(f"Dialogue: 1,{_ass_ts(0)},{_ass_ts(duration)},Title,,0,0,0,,"
                     + r"\N".join(parts))
    for c in cues:
        lines.append(f"Dialogue: 0,{_ass_ts(c.start)},{_ass_ts(c.end)},Sub,,0,0,0,,"
                     + _highlight(c.text, keywords or []))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
