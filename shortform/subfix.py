"""Claude로 숏폼 자막 다듬기: 음성 인식 오타를 문맥으로 고치고 자연스러운 곳에서 끊는다.

Claude에게는 고친 자막 줄의 글자만 받는다. 각 줄이 언제 나와야 하는지는 고친 글자를
원래 음성 인식 글자와 한 글자씩 맞춰 보고(difflib), 그 글자를 말한 단어의 시간에서
가져온다. 그래서 Claude가 줄을 어떻게 나눠도 자막이 실제 말하는 순간에 맞게 나온다.
고친 내용이 원래 말과 너무 다르면 None을 돌려주고, 호출한 쪽에서 기존 방식으로 만든다.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .highlights import MODEL
from .subtitles import Cue, Word

SYSTEM_PROMPT = """\
You edit burned-in subtitles for Korean short-form videos (YouTube Shorts, Reels).
You receive the speech-recognition transcript of one clip. Recognition makes mistakes:
misheard words, wrong spacing, words split or merged oddly.

Rewrite it as subtitle lines, in the order spoken:
- Keep each line short enough to read at a glance: at most {max_chars} characters
  (not counting spaces). Break at natural phrase boundaries; never break inside a word
  or between a noun and its particle.
- Fix recognition errors using the surrounding context and the information about the
  video, and fix Korean spacing. Keep the speaker's own words, tone and slang; do not
  paraphrase, summarize, reorder, add words, or censor. You may drop pure filler
  sounds (음, 어).
- Cover the whole transcript from start to end.
- Do not add sentence-final periods. Keep ? and ! where the speaker clearly asks or
  exclaims.

For every line also give:
- who: "main" if the main person of the clip says it (the interviewee, the speaker the
  video is about), "other" if someone else does (an interviewer, host, off-camera voice,
  friend). Questions asked to the main person usually come from "other". If only one
  person talks, every line is "main".
- note: a short reaction or action note shown with the line, in parentheses, such as
  "(고민)", "(당황)", "(웃음)", "(정적)", "(한숨)", only when the words clearly imply it
  (a hesitant answer, laughing, a sudden silence). At most one note every 5 lines;
  otherwise "".
- image: if <images> are listed, the file name of one image that fits this exact line as
  a funny or clarifying cut-in (a surprised meme when someone is shocked, a photo of the
  person or thing being talked about), else "". At most one image every 4 lines, only
  where it clearly adds, never the same image twice in a row. Judge an image only by its
  file name."""

SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "who": {"type": "string", "enum": ["main", "other"]},
                       "note": {"type": "string"}, "image": {"type": "string"}},
        "required": ["text", "who", "note", "image"],
        "additionalProperties": False,
    }}},
    "required": ["lines"],
    "additionalProperties": False,
}

# 글자 맞추기에서 무시할 것: 띄어쓰기와 문장부호
_IGNORE = re.compile(r"[\s.,?!~…·'\"“”‘’()\[\]-]")


def _norm(text: str) -> str:
    return _IGNORE.sub("", text)


def fix_cues(words: list[Word], *, max_chars: int = 14, context: str = "",
             images: list[str] | None = None, client=None) -> list[Cue] | None:
    """words(숏폼 타임라인 기준)로 다듬은 자막 줄을 만든다. 실패하면 None.

    줄마다 말한 사람(main/other), 표정 자막(note), 끼워 넣을 짤(image, images 중 하나)도 받는다.
    """
    if not words:
        return []
    transcript = " ".join(w.text.strip() for w in words)
    about = f"<about_video>\n{context}\n</about_video>\n\n" if context else ""
    if images:
        about += "<images>\n" + "\n".join(images) + "\n</images>\n\n"
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
            messages=[{"role": "user",
                       "content": f"{about}<transcript>\n{transcript}\n</transcript>"}],
        )
    except Exception as e:  # API 키 없음, 네트워크 오류 등: 기존 방식 자막으로
        print(f"  (자막 다듬기 건너뜀: {type(e).__name__}: {str(e)[:120]})")
        return None
    if response.stop_reason != "end_turn":
        print(f"  (자막 다듬기 건너뜀: {response.stop_reason})")
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        items = [x if isinstance(x, dict) else {"text": str(x)} for x in json.loads(text)["lines"]]
    except (ValueError, KeyError, TypeError):
        return None
    items = [x for x in items if _norm(str(x.get("text", "")))]
    cues = align([str(x["text"]) for x in items], words)
    if cues is None:
        print("  (고친 자막이 원래 말과 너무 달라서 원래 자막을 써요)")
        return None
    allowed = set(images or [])
    for c, x in zip(cues, items):
        c.who = "other" if x.get("who") == "other" else "main"
        note = str(x.get("note", "")).strip()
        c.note = f"({note.strip('()')})" if note.strip("() ") else ""
        c.image = x.get("image", "") if x.get("image", "") in allowed else ""
    if all(c.who == "other" for c in cues):  # 전부 다른 사람일 리는 없다
        for c in cues:
            c.who = "main"
    return cues


def align(lines: list[str], words: list[Word], *, min_ratio: float = 0.55) -> list[Cue] | None:
    """고친 자막 줄을 원래 단어 시간에 맞춘다."""
    # 원래 글자들과 글자마다 말한 시간 (단어 안에서는 글자 수로 나눈다)
    orig, c_start, c_end = "", [], []
    for w in words:
        t = _norm(w.text)
        step = (w.end - w.start) / max(len(t), 1)
        orig += t
        c_start += [w.start + k * step for k in range(len(t))]
        c_end += [w.start + (k + 1) * step for k in range(len(t))]
    if not orig:
        return None

    kept = [(ln.strip(), _norm(ln)) for ln in lines if _norm(ln)]
    corr = "".join(n for _, n in kept)
    if not corr:
        return None
    sm = SequenceMatcher(None, orig, corr, autojunk=False)
    if sm.ratio() < min_ratio:
        return None

    # 고친 글자 위치 → 원래 글자 위치
    to_orig = [0] * len(corr)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        for k in range(j2 - j1):
            if tag == "equal":
                to_orig[j1 + k] = i1 + k
            elif tag == "replace":
                to_orig[j1 + k] = i1 + k * (i2 - i1) // (j2 - j1)
            elif tag == "insert":  # 원래 없던 글자는 바로 앞 글자에 붙인다 ("뭐" + "해")
                to_orig[j1 + k] = max(i1 - 1, 0)
    last = len(orig) - 1

    cues: list[Cue] = []
    pos = 0
    for text, n in kept:
        a = min(to_orig[pos], last)
        b = max(min(to_orig[pos + len(n) - 1], last), a)
        pos += len(n)
        start = c_start[a]
        if cues:
            start = max(start, cues[-1].end)
        end = max(c_end[b], start + 0.3)
        cues.append(Cue(start, end, text))
    for x, y in zip(cues, cues[1:]):  # 다음 자막과 겹치지 않게, 너무 빨리 사라지지 않게
        x.end = min(max(x.end, x.start + 0.6), y.start)
    return cues
