"""Claude로 숏폼 자막 다듬기: 음성 인식 오타를 문맥으로 고치고 자연스러운 곳에서 끊는다.

단어마다 번호를 붙여 보내고, Claude는 "몇 번~몇 번 단어를 한 줄로, 고친 글자는
이것" 형태로 돌려준다. 시간 정보는 단어 번호로 계산하므로 자막 싱크가 어긋나지 않는다.
결과가 이상하면 None을 돌려주고, 호출한 쪽에서 기존 방식으로 자막을 만든다.
"""
from __future__ import annotations

import json

from .highlights import MODEL
from .subtitles import Cue, Word

SYSTEM_PROMPT = """\
You edit burned-in subtitles for Korean short-form videos (YouTube Shorts, Reels).
You receive the speech-recognition output of one clip as numbered words. Recognition
makes mistakes: misheard words, wrong spacing, words split or merged oddly.

Group consecutive words into subtitle lines and write the corrected text of each line:
- Every line covers a consecutive run of word numbers. Lines are in order and do not
  overlap. You may leave out pure filler words (음, 어, 그) by skipping their numbers.
- Keep each line short enough to read at a glance: at most {max_chars} characters
  (not counting spaces). Prefer breaking at natural phrase boundaries; never break
  inside a word or between a noun and its particle.
- Fix recognition errors using the surrounding context and the information about the
  video, and fix Korean spacing. Keep the speaker's own words, tone and slang; do not
  paraphrase, summarize, add words, or censor.
- Do not add sentence-final periods. Keep ? and ! where the speaker clearly asks or
  exclaims."""

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first": {"type": "integer", "description": "first word number"},
                    "last": {"type": "integer", "description": "last word number"},
                    "text": {"type": "string", "description": "corrected subtitle text"},
                },
                "required": ["first", "last", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def fix_cues(words: list[Word], *, max_chars: int = 14, context: str = "",
             client=None) -> list[Cue] | None:
    """words(숏폼 타임라인 기준)로 다듬은 자막 줄을 만든다. 실패하면 None."""
    if not words:
        return []
    numbered = "\n".join(f"{i}: {w.text.strip()}" for i, w in enumerate(words))
    about = f"<about_video>\n{context}\n</about_video>\n\n" if context else ""
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            system=SYSTEM_PROMPT.format(max_chars=max_chars),
            messages=[{"role": "user", "content": f"{about}<words>\n{numbered}\n</words>"}],
        )
    except Exception as e:  # API 키 없음, 네트워크 오류 등: 기존 방식 자막으로
        print(f"  (자막 다듬기 건너뜀: {type(e).__name__}: {str(e)[:120]})")
        return None
    if response.stop_reason != "end_turn":
        print(f"  (자막 다듬기 건너뜀: {response.stop_reason})")
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        lines = json.loads(text)["lines"]
    except (ValueError, KeyError):
        return None
    return _to_cues(lines, words)


def _to_cues(lines: list[dict], words: list[Word]) -> list[Cue] | None:
    cues: list[Cue] = []
    last = -1
    for ln in lines:
        a, b, txt = int(ln["first"]), int(ln["last"]), str(ln["text"]).strip()
        if not (last < a <= b < len(words)) or not txt:
            return None  # 순서가 꼬였거나 범위를 벗어남 → 믿을 수 없음
        cues.append(Cue(words[a].start, words[b].end, txt))
        last = b
    covered = sum(int(ln["last"]) - int(ln["first"]) + 1 for ln in lines)
    if covered < len(words) * 0.8:  # 말을 너무 많이 빼먹었으면 믿지 않는다
        return None
    for x, y in zip(cues, cues[1:]):  # 다음 자막과 겹치지 않게, 너무 빨리 사라지지 않게
        x.end = min(max(x.end, x.start + 0.6), y.start)
    return cues
