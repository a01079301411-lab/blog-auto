"""자막 텍스트를 Claude에게 보내 숏폼으로 쓸 하이라이트 구간을 고른다."""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from .transcribe import Sentence

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are an experienced short-form video editor (YouTube Shorts, Reels, TikTok) who
makes viral clips from long talks, lectures and interviews, especially Korean
business, money and self-improvement content.
You receive a timestamped transcript of a long-form video and pick the moments that
would work best as standalone vertical short clips.

A good clip:
- makes sense on its own without the rest of the video (no dangling "as I said earlier")
- has a hook in the first 3 seconds: a provocative claim, a blunt opinion, a specific
  number (money, revenue, years), a common mistake, or a question viewers ask themselves
- delivers a payoff: a concrete lesson, a punchline, a story with a turn, or a line
  that viewers will want to argue about or share in the comments
- ends on a complete thought, not mid-sentence
- does not overlap with other clips you pick

Use only timestamps that appear in the transcript: start each clip at the start of a
line and end it at the end of a line. The transcript comes from speech recognition, so
infer the intended words when a line is slightly garbled.

For each clip also write, in the transcript's language:
- title: the hook headline shown above the video, 2 lines (at most 3) separated by
  "\\n", each line at most 13 characters. Wrap the 1-2 most striking words in curly
  braces; they are shown in an accent color. The first line sets up, the last line is
  the punch, e.g. "사장님 속터지는\\n{진상 직원}의 한마디" or "망하는 사장님의\\n{치명적 실수}".
  Make people stop scrolling, but do not promise anything the clip does not deliver.
- label: a short teaser shown in a small badge above the title, at most 10 characters,
  e.g. "당신만 몰랐던..".
- speaker: who is talking, as "name / role" (e.g. "권기준 / 꼴통사장 대표"), using the
  information about the video when available.
- bottom: a one-line viewer reaction shown at the bottom, at most 14 characters,
  e.g. "나 같아도 열 받겠다".
- keywords: 2-5 words or short phrases that appear verbatim in the clip's speech and
  carry its impact; they are highlighted in the subtitles.
- caption: an upload description of 1-2 sentences followed by 3-5 hashtags.

Order the clips from best to worst and score each one honestly."""

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
                    "title": {"type": "string", "description": "hook headline, {accent}"},
                    "label": {"type": "string"},
                    "sub_title": {"type": "string",
                                  "description": "short line shown above the title"},
                    "speaker": {"type": "string"},
                    "bottom": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "caption": {"type": "string", "description": "upload description + hashtags"},
                    "reason": {"type": "string", "description": "why this works as a short"},
                    "score": {"type": "integer",
                              "description": "1-10, how well it would perform as a short"},
                },
                "required": ["start", "end", "title", "label", "sub_title", "speaker", "bottom", "keywords",
                             "caption", "reason", "score"],
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
    score: int = 0
    keywords: list[str] = field(default_factory=list)
    caption: str = ""
    label: str = ""
    speaker: str = ""
    bottom: str = ""
    sub_title: str = ""
    account: int = 0   # 코시 계정 번호 (0이면 계정 없이 일반 스타일)


def format_transcript(sentences: list[Sentence]) -> str:
    return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in sentences)


# 한 번에 보낼 대본 최대 글자 수. 이보다 긴 대본(대략 10시간 이상)은 나눠서 보낸다.
MAX_CHARS_PER_REQUEST = 400_000


def _windows(sentences: list[Sentence], max_chars: int) -> list[list[Sentence]]:
    windows: list[list[Sentence]] = [[]]
    size = 0
    for s in sentences:
        if windows[-1] and size + len(s.text) + 20 > max_chars:
            windows.append([])
            size = 0
        windows[-1].append(s)
        size += len(s.text) + 20
    return windows


def _account_brief(acct) -> str:
    """계정 컨셉과 이 계정 가이드에 맞는 글자 작성 요령."""
    max_chars = max(8, int(960 / (acct.video.title.size * 0.92)))
    uses_sub = acct.video.sub_title is not None or acct.thumb.pill is not None
    lines = [
        f"These clips are for the Instagram account {acct.handle} \"{acct.name}\" ({acct.kind}).",
        f"Concept (what this account posts): {acct.concept}",
        f"Audience: {acct.audience}",
        f"Profile tone: {acct.bio}",
        "Only pick moments that fit this account's concept and audience; return fewer clips "
        "rather than clips that do not fit.",
        f"Title style for this account: {acct.title_hint}",
        f"Each title line at most {max_chars} characters, at most 2 lines.",
        "sub_title: " + ("a short line of at most 10 characters (shown above the title or as a "
                         "badge on the thumbnail)." if uses_sub else "leave empty."),
        "speaker: the yellow caption shown in brackets above the subtitles, either who is talking "
        "(e.g. '권기준 / 연매출 300억 대표') or a short situation / emotion note "
        "(e.g. '무단 결근 100회'), at most 16 characters, without the brackets.",
        "bottom: " + ("a one-line viewer reaction shown below the video, at most 14 characters, "
                      "without the angle brackets." if acct.bottom else "leave empty."),
    ]
    if acct.caution:
        lines.append(f"Caution: {acct.caution}")
    return "\n".join(lines)


def _ask_claude(client, sentences: list[Sentence], count: int, min_len: float, max_len: float,
                context: str, account=None, exclude: list[tuple[float, float]] | None = None,
                ) -> list[Highlight]:
    about = f"<about_video>\n{context}\n</about_video>\n\n" if context else ""
    # 대본 부분은 계정마다 똑같이 보내므로 캐시해서 두 번째 계정부터 비용을 줄인다
    content = [{"type": "text",
                "text": f"{about}<transcript>\n{format_transcript(sentences)}\n</transcript>",
                "cache_control": {"type": "ephemeral"}}]
    ask = ""
    if account is not None:
        ask += f"<account>\n{_account_brief(account)}\n</account>\n\n"
    if exclude:
        used = ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in exclude)
        ask += f"These ranges are already used by other accounts; do not overlap them: {used}\n\n"
    ask += (f"Pick up to {count} clips, each between {min_len:.0f} and {max_len:.0f} "
            f"seconds long.")
    content.append({"type": "text", "text": ask})
    # 대본이 길면 응답 대기 시간도 길어지므로 스트리밍으로 받는다
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("응답이 너무 길어 잘렸습니다. --count를 줄여 보세요.")
    text = next(b.text for b in response.content if b.type == "text")
    return [Highlight(float(h["start"]), float(h["end"]), h["title"].replace("\\n", "\n"),
                      h["reason"], int(h["score"]), h["keywords"], h["caption"],
                      h["label"], h["speaker"], h["bottom"], h.get("sub_title", ""),
                      account.no if account is not None else 0)
            for h in json.loads(text)["highlights"]]


def pick_highlights(
    sentences: list[Sentence],
    *,
    count: int = 3,
    min_len: float = 20,
    max_len: float = 60,
    context: str = "",
    account=None,
    exclude: list[tuple[float, float]] | None = None,
) -> list[Highlight]:
    import anthropic

    client = anthropic.Anthropic()
    windows = _windows(sentences, MAX_CHARS_PER_REQUEST)
    picked: list[Highlight] = []
    for i, window in enumerate(windows, 1):
        if len(windows) > 1:
            print(f"  대본이 길어 나눠서 분석합니다 [{i}/{len(windows)}]")
        # 구간별로 넉넉히 뽑은 뒤 점수순으로 전체에서 고른다
        want = count if len(windows) == 1 else min(count, max(3, count // len(windows) + 2))
        picked += _ask_claude(client, window, want, min_len, max_len, context, account, exclude)
    picked.sort(key=lambda h: -h.score)  # 같은 점수는 Claude가 매긴 순서 유지
    if exclude:  # 다른 계정이 이미 쓴 구간과 겹치면 뺀다
        picked = [h for h in picked if not any(h.start < b and a < h.end for a, b in exclude)]
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
    starts = sorted(s.start for s in sentences)
    ends = sorted(s.end for s in sentences)

    def nearest(sorted_ts: list[float], t: float) -> float:
        i = bisect_left(sorted_ts, t)
        return min(sorted_ts[max(i - 1, 0):i + 1], key=lambda x: abs(x - t))

    out: list[Highlight] = []
    for h in highlights:
        # 가장 가까운 문장 시작/끝으로 맞춘다
        h.start = nearest(starts, h.start)
        h.end = nearest(ends, h.end)
        if h.end - h.start > max_len:  # 너무 길면 max_len 안의 마지막 문장 끝에서 자른다
            i = bisect_right(ends, h.start + max_len) - 1
            h.end = ends[i] if i >= 0 and ends[i] > h.start else h.start + max_len
        if h.end - h.start < min_len * 0.5:
            continue
        if any(h.start < o.end and o.start < h.end for o in out):
            continue
        out.append(h)
        if len(out) == count:
            break
    return out


def parse_ranges(text: str) -> list[Highlight]:
    """'60-120,5:00-5:45=망하는 사장님의/{치명적 실수}' 형식의 수동 구간 지정.

    '=' 뒤는 상단 제목(선택)이고, '/'로 줄을 나누고 {중괄호}로 강조한다.
    """
    def sec(t: str) -> float:
        total = 0.0
        for part in t.strip().split(":"):
            total = total * 60 + float(part)
        return total

    out = []
    for i, r in enumerate(filter(None, text.split(",")), 1):
        r, _, title = r.partition("=")
        a, b = r.split("-")
        out.append(Highlight(sec(a), sec(b), title.strip().replace("/", "\n")))
    return out
