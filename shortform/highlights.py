"""자막 텍스트를 Claude에게 보내 숏폼으로 쓸 하이라이트 구간을 고른다."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .transcribe import Sentence

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are an experienced short-form video editor (YouTube Shorts, Reels, TikTok).
You receive a timestamped transcript of a long-form video and pick the moments that
would work best as standalone vertical short clips.

A good clip:
- makes sense on its own without the rest of the video (no dangling "as I said earlier")
- has a hook in the first 3 seconds: a surprising claim, a question, a strong opinion,
  a punchline, or a concrete useful tip
- ends on a complete thought, not mid-sentence
- does not overlap with other clips you pick

Use only timestamps that appear in the transcript: start each clip at the start of a
line and end it at the end of a line. Write the title in the transcript's language.
Order the clips from best to worst."""

SCHEMA = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "seconds"},
                    "end": {"type": "number", "description": "seconds"},
                    "title": {"type": "string", "description": "short catchy title"},
                    "reason": {"type": "string", "description": "why this works as a short"},
                },
                "required": ["start", "end", "title", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["highlights"],
    "additionalProperties": False,
}


@dataclass
class Highlight:
    start: float
    end: float
    title: str
    reason: str = ""


def format_transcript(sentences: list[Sentence]) -> str:
    return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in sentences)


def pick_highlights(
    sentences: list[Sentence],
    *,
    count: int = 3,
    min_len: float = 20,
    max_len: float = 60,
) -> list[Highlight]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"<transcript>\n{format_transcript(sentences)}\n</transcript>\n\n"
                f"Pick up to {count} clips, each between {min_len:.0f} and "
                f"{max_len:.0f} seconds long."
            ),
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 너무 길어 잘렸습니다. --count를 줄여 보세요.")
    text = next(b.text for b in response.content if b.type == "text")
    raw = json.loads(text)["highlights"]
    picked = [Highlight(float(h["start"]), float(h["end"]), h["title"], h["reason"])
              for h in raw]
    return clean(picked, sentences, count=count, min_len=min_len, max_len=max_len)


def clean(
    highlights: list[Highlight],
    sentences: list[Sentence],
    *,
    count: int,
    min_len: float,
    max_len: float,
) -> list[Highlight]:
    """문장 경계에 맞추고, 길이를 보정하고, 겹치는 구간을 제거한다."""
    if not sentences:
        return []
    starts = [s.start for s in sentences]
    ends = [s.end for s in sentences]
    out: list[Highlight] = []
    for h in highlights:
        # 가장 가까운 문장 시작/끝으로 맞춘다
        h.start = min(starts, key=lambda t: abs(t - h.start))
        h.end = min(ends, key=lambda t: abs(t - h.end))
        if h.end - h.start > max_len:  # 너무 길면 max_len 안의 마지막 문장 끝에서 자른다
            fit = [t for t in ends if h.start < t <= h.start + max_len]
            h.end = max(fit) if fit else h.start + max_len
        if h.end - h.start < min_len * 0.5:
            continue
        if any(h.start < o.end and o.start < h.end for o in out):
            continue
        out.append(h)
        if len(out) == count:
            break
    return out


def parse_ranges(text: str) -> list[Highlight]:
    """'60-120,5:00-5:45' 형식의 수동 구간 지정."""
    def sec(t: str) -> float:
        total = 0.0
        for part in t.strip().split(":"):
            total = total * 60 + float(part)
        return total

    out = []
    for i, r in enumerate(filter(None, text.split(",")), 1):
        a, b = r.split("-")
        out.append(Highlight(sec(a), sec(b), f"clip{i}"))
    return out
