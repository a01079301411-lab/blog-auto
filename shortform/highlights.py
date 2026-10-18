"""자막 텍스트를 Claude에게 보내 숏폼으로 쓸 하이라이트 구간을 고른다."""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from .transcribe import Sentence

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are an experienced short-form video editor (YouTube Shorts, Reels, TikTok) who
makes viral clips from long Korean videos of any kind: talks, lectures, interviews,
family vlogs, work footage and product videos. A <video_type> guide tells you what
works for this particular video; when it conflicts with the generic advice below,
follow the guide.
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


def split_lines(words, *, max_chars: int = 45, gap: float = 0.5) -> list[Sentence]:
    """단어 타임스탬프로 대본을 짧은 문장 단위 줄로 나눈다.

    Whisper 구간은 여러 문장이 한데 묶여 길어서, 숏폼 시작·끝을 문장 단위로 정확히
    고를 수 있게 문장 끝(. ? !)이나 쉬는 곳에서 다시 끊는다.
    """
    lines: list[Sentence] = []
    cur: list = []

    def flush():
        if cur:
            text = "".join(w.text for w in cur).strip()
            if text:
                lines.append(Sentence(cur[0].start, cur[-1].end, text))
            cur.clear()

    for w in words:
        if cur and (w.start - cur[-1].end > gap
                    or len("".join(x.text for x in cur)) + len(w.text) > max_chars):
            flush()
        cur.append(w)
        if w.text.rstrip()[-1:] in (".", "?", "!"):  # 문장 끝
            flush()
    flush()
    return lines


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
                ref_blocks: list[dict] | None = None, guide: str = "") -> list[Highlight]:
    about = f"<about_video>\n{context}\n</about_video>\n\n" if context else ""
    if guide:
        about += f"<video_type>\n{guide}\n</video_type>\n\n"
    # 레퍼런스와 대본은 계정마다 똑같이 보내므로 캐시해서 두 번째 계정부터 비용을 줄인다
    content = list(ref_blocks or []) + [{"type": "text",
                "text": f"{about}<transcript>\n{format_transcript(sentences)}\n</transcript>",
                "cache_control": {"type": "ephemeral"}}]
    ask = ""
    if account is not None:
        ask += f"<account>\n{_account_brief(account)}\n</account>\n\n"
    if exclude:
        used = ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in exclude)
        ask += f"These ranges are already used by other accounts; do not overlap them: {used}\n\n"
    ask += (f"Propose up to {count} candidate clips, each between {min_len:.0f} and "
            f"{max_len:.0f} seconds long. A stricter editor will review every candidate "
            f"afterwards, so include every strong moment you find, best first.")
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


VERIFY_PROMPT = """\
You are a strict senior short-form editor (Reels, YouTube Shorts) reviewing candidate
clips that a junior editor cut from a long Korean video. Judge each candidate as a
viewer scrolling Reels who has never seen the long video.

For each candidate you get the transcript lines around it; lines inside the proposed
range are marked with ">". Score 1-10:
- hook: would the first 3 seconds stop the scroll? The first line itself must be the
  hook. Preambles like "그래서", "아 그리고", "자 이제", greetings or recaps are weak.
- payoff: does it deliver a clear point, punchline, lesson or turn that feels worth it?
- standalone: fully understandable alone? No missing context, no references to earlier
  parts ("아까 말씀드린", "이거"), no unfinished thought at the end.
- fit: fits the account concept and audience (if an account is given; otherwise how
  well it fits the video's audience).

Set keep=false if any score is below 6, or the clip is filler, small talk, logistics,
an ad, repetitive, or only interesting with visuals the transcript does not show.

Tighten the boundaries: start at the exact line where the hook begins (drop the
preamble) and end right after the payoff line (drop trailing filler). Use only
timestamps of the lines shown, and keep the length between {min_len:.0f} and
{max_len:.0f} seconds. If the boundaries change what the clip says, rewrite title and
sub_title by the same rules as before (keep the {{accent}} braces style); otherwise
return them unchanged. verdict: one Korean sentence on why it works or why it fails."""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "hook": {"type": "integer"},
                    "payoff": {"type": "integer"},
                    "standalone": {"type": "integer"},
                    "fit": {"type": "integer"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "sub_title": {"type": "string"},
                    "verdict": {"type": "string"},
                },
                "required": ["id", "keep", "hook", "payoff", "standalone", "fit", "start", "end",
                             "title", "sub_title", "verdict"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}


def _excerpt(lines: list[Sentence], h: Highlight, pad: float = 20.0) -> str:
    out = []
    for ln in lines:
        if ln.end < h.start - pad or ln.start > h.end + pad:
            continue
        mark = ">" if h.start - 0.5 <= ln.start and ln.end <= h.end + 0.5 else " "
        out.append(f"{mark} [{ln.start:.1f}-{ln.end:.1f}] {ln.text}")
    return "\n".join(out)


def verify(client, candidates: list[Highlight], lines: list[Sentence], *, min_len: float,
           max_len: float, context: str = "", account=None, guide: str = "") -> list[Highlight]:
    """후보를 다시 엄격하게 평가해 경계를 다듬고, 통과한 것만 점수와 함께 돌려준다."""
    if not candidates:
        return []
    parts = []
    if context:
        parts.append(f"<about_video>\n{context}\n</about_video>")
    if guide:
        parts.append(f"<video_type>\n{guide}\n</video_type>")
    if account is not None:
        parts.append(f"<account>\n{_account_brief(account)}\n</account>")
    for i, h in enumerate(candidates):
        sub = f" / sub_title: {h.sub_title}" if h.sub_title else ""
        parts.append(f"<candidate id=\"{i}\">\nproposed: {h.start:.1f}-{h.end:.1f}s\n"
                     f"title: {h.title.replace(chr(10), ' / ')}{sub}\n"
                     f"{_excerpt(lines, h)}\n</candidate>")
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": VERIFY_SCHEMA}},
        system=VERIFY_PROMPT.format(min_len=min_len, max_len=max_len),
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason != "end_turn":
        print(f"  (검증 단계 건너뜀: {response.stop_reason})")
        return candidates
    text = next(b.text for b in response.content if b.type == "text")
    kept, rejected = [], []
    for r in json.loads(text)["reviews"]:
        if not 0 <= r["id"] < len(candidates):
            continue
        h = candidates[r["id"]]
        scores = [r["hook"], r["payoff"], r["standalone"], r["fit"]]
        h.score = round(sum(scores) / len(scores))
        if r["end"] > r["start"]:
            h.start, h.end = float(r["start"]), float(r["end"])
        if r["title"].strip():
            h.title = r["title"].replace("\\n", "\n")
        if r["sub_title"].strip():
            h.sub_title = r["sub_title"]
        h.reason = f"{r['verdict']} (훅 {r['hook']}·결론 {r['payoff']}·이해 {r['standalone']}·컨셉 {r['fit']})"
        (kept if r["keep"] and min(scores) >= 6 else rejected).append(h)
    print(f"  후보 {len(candidates)}개 중 {len(kept)}개 통과")
    return sorted(kept, key=lambda h: -h.score)


def pick_highlights(
    sentences: list[Sentence],
    *,
    count: int = 3,
    min_len: float = 20,
    max_len: float = 60,
    context: str = "",
    account=None,
    exclude: list[tuple[float, float]] | None = None,
    words=None,
    ref_blocks: list[dict] | None = None,
    guide: str = "",
) -> list[Highlight]:
    """1) 후보를 넉넉히 뽑고 2) 엄격하게 다시 검증해서 통과한 것만 고른다."""
    import anthropic

    client = anthropic.Anthropic()
    lines = split_lines(words) if words else sentences
    windows = _windows(lines, MAX_CHARS_PER_REQUEST)
    want_total = min(max(count * 3, 6), 15)  # 필요한 개수의 3배쯤 후보를 뽑는다
    candidates: list[Highlight] = []
    for i, window in enumerate(windows, 1):
        if len(windows) > 1:
            print(f"  대본이 길어 나눠서 분석합니다 [{i}/{len(windows)}]")
        want = want_total if len(windows) == 1 else max(4, want_total // len(windows) + 2)
        candidates += _ask_claude(client, window, want, min_len, max_len, context, account,
                                  exclude, ref_blocks, guide)
    if exclude:  # 다른 계정이 이미 쓴 구간과 겹치면 뺀다
        candidates = [h for h in candidates
                      if not any(h.start < b and a < h.end for a, b in exclude)]
    print(f"  후보 {len(candidates)}개를 다시 꼼꼼히 검증하는 중...")
    try:
        picked = verify(client, candidates, lines, min_len=min_len, max_len=max_len,
                        context=context, account=account, guide=guide)
    except Exception as e:  # 검증이 실패해도 1단계 결과로 계속
        print(f"  (검증 단계 건너뜀: {type(e).__name__}: {str(e)[:100]})")
        picked = sorted(candidates, key=lambda h: -h.score)
    if exclude:
        picked = [h for h in picked if not any(h.start < b and a < h.end for a, b in exclude)]
    result = clean(picked, lines, count=count, min_len=min_len, max_len=max_len)
    if len(result) < count:
        print(f"  확실한 하이라이트가 {len(result)}개뿐이라 {len(result)}개만 만들어요.")
    return result


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
