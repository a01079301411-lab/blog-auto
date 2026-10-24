"""자막 텍스트를 Claude에게 보내 숏폼으로 쓸 하이라이트 구간을 고른다."""
from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from .transcribe import Sentence

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are an experienced short-form video editor (YouTube Shorts, Reels, TikTok) who
makes viral clips from long Korean videos of any kind: talks, lectures, interviews,
vlogs, comedy, stories, tips, work footage and product videos. A <video_type> guide
tells you what works for this particular video; when it conflicts with the generic advice below,
follow the guide.
You receive a timestamped transcript of a long-form video and pick the moments that
would work best as standalone vertical short clips.

A good clip:
- makes sense on its own without the rest of the video (no dangling "as I said earlier")
- has a hook in the first 3 seconds (see the hook types in the <video_type> guide)
- delivers a payoff: a concrete lesson, a punchline, a story with a turn, or a line
  that viewers will want to argue about or share in the comments
- ends on a complete thought, not mid-sentence
- does not overlap with other clips you pick

Use only timestamps that appear in the transcript: start each clip at the start of a
line and end it at the end of a line. The transcript comes from speech recognition, so
infer the intended words when a line is slightly garbled. When <frames> are given, they
show what is on screen at those times; footage with little speech (sports, workouts,
action) is judged mainly by the frames, and any time may be used.

parts: the pieces of the source played in this order to make the clip. Normally one
piece equal to start-end. Only when the <video_type> guide says montage is allowed, a
clip may join 2-6 pieces from anywhere in the footage (e.g. the most dramatic moment
first as the hook, then the setup, the action and the ending); each piece at least 2
seconds, pieces never overlap, and the total of the pieces is the clip length. Then
start is the earliest and end the latest time used.

For each clip also write, in the transcript's language:
- title_options: 4 different hook titles for the clip, each built on a different hook
  type (e.g. number + question, result first, warning, secret, reaction, turn teaser).
  Write them from the clip's single most surprising concrete fact or moment, NOT from
  its topic. Test each one: if it could be a chapter name or a topic label ("사장 마인드",
  "악플 해명", "직원 관리 노하우"), throw it away and write a hook instead.
- title: the one of title_options that would win an A/B test for stopping a stranger's
  scroll. 1-2 lines separated by "\\n", at most 16 characters in total including spaces;
  follow the title rules in <video_type>. Wrap the 1-2 most striking words in curly
  braces; they are shown in an accent color. The first line sets up, the last line is
  the punch, e.g. "사장님 속터지는\\n{진상 직원}의 한마디" or "망하는 사장님의\\n{치명적 실수}".
  Make people stop scrolling, but do not promise anything the clip does not deliver.
- label: a short teaser shown in a small badge above the title, at most 10 characters,
  e.g. "당신만 몰랐던..".
- speaker: who is talking, as "name / role" (e.g. "권기준 / 꼴통사장 대표"), using the
  information about the video when available; or, when the clip is a situation rather
  than a talk, a short situation note instead (e.g. "남편과 월급 협상 중").
- bottom: a one-line viewer reaction shown at the bottom, at most 14 characters,
  e.g. "나 같아도 열 받겠다".
- keywords: 2-5 words or short phrases that appear verbatim in the clip's speech and
  carry its impact; they are highlighted in the subtitles.
- caption: an upload description of 1-2 sentences followed by 3-5 hashtags.
- hook_text: the big text shown over the video for the first 2 seconds, at most 14
  characters. It must make the viewer need to see the end (open loop): a question the
  clip answers, a surprising claim, or the stakes ("이거 모르면 손해", "딸의 마지막 한마디").
  Never give away the payoff. Different from the title.
- rehook_text and rehook_time: a short teaser (at most 12 characters, e.g. "진짜는 지금부터",
  "근데 반전이…") shown just before the payoff to stop viewers leaving midway, and the
  time in seconds from the clip start when it appears (about 40-70% into the clip, a
  few seconds before the payoff). Empty text and 0 if the clip is short or needs none.
- bgm_mood: background music mood for the clip: bright, calm, tension or funny.

Retention (watch time) rules that proven Shorts and Reels follow; apply them:
- Start on the strongest line or reaction, not on a greeting or setup. The first
  sentence must create a question in the viewer's head.
- Keep the payoff for the last third and end right after it (no outro), so the loop
  restarts naturally and viewers rewatch.
- Prefer clips where something changes every 3-5 seconds (new point, new emotion,
  new image); avoid long explanations with no turn.
- If <references> are given, copy their hook and pacing style, not their content.

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
                    "parts": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"start": {"type": "number"}, "end": {"type": "number"}},
                        "required": ["start", "end"], "additionalProperties": False}},
                    "title_options": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string", "description": "hook headline, {accent}"},
                    "label": {"type": "string"},
                    "sub_title": {"type": "string",
                                  "description": "short line shown above the title"},
                    "speaker": {"type": "string"},
                    "bottom": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "caption": {"type": "string", "description": "upload description + hashtags"},
                    "reason": {"type": "string", "description": "why this works as a short"},
                    "hook_text": {"type": "string"},
                    "rehook_text": {"type": "string"},
                    "rehook_time": {"type": "number"},
                    "bgm_mood": {"type": "string", "enum": ["bright", "calm", "tension", "funny"]},
                    "score": {"type": "integer",
                              "description": "1-10, how well it would perform as a short"},
                },
                "required": ["start", "end", "parts", "title_options", "title", "label", "sub_title", "speaker", "bottom", "keywords",
                             "hook_text", "rehook_text", "rehook_time", "bgm_mood",
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
    hook: str = ""       # 처음 2초 크게 띄우는 훅 자막
    rehook: str = ""     # 중간 이탈을 막는 한마디
    rehook_at: float = 0.0  # 원본 영상 기준 몇 초에 띄울지 (0이면 없음)
    bgm_mood: str = ""   # 배경음악 분위기 (bright, calm, tension, funny)
    title_options: list[str] = field(default_factory=list)  # AI가 쓴 제목 후보들
    parts: list[list[float]] = field(default_factory=list)  # 여러 장면을 이어 붙일 때 [시작, 끝]들

    def pieces(self) -> list[tuple[float, float]]:
        """숏폼에 들어갈 원본 구간들 (보여 줄 순서대로)."""
        if len(self.parts) > 1:
            return [(float(a), float(b)) for a, b in self.parts]
        return [(self.start, self.end)]

    def length(self) -> float:
        return sum(b - a for a, b in self.pieces())


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


def clean_title(title: str) -> str:
    """AI가 쓴 제목 정리: 줄바꿈 표시(\\n, ' / ')를 진짜 줄바꿈으로, 화면에 어색한 기호는 뺀다."""
    t = title.replace("\\n", "\n")
    if "\n" not in t and "/" in t:  # '앞줄 / 뒷줄'로 쓴 경우
        t = re.sub(r"\s*/\s*", "\n", t, count=1)
    t = re.sub(r"\s*[/|·]\s*", " ", t)
    t = re.sub(r"[\[\]()<>:;~]", "", t)
    lines = [" ".join(ln.split()) for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln.strip("{} "))


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
        f"Title style for this account: {acct.title_hint.replace(' / ', chr(92) + 'n')}",
        "Even when the account style says informational (정보형), the title must still be a "
        "hook with a curiosity gap, not a topic label.",
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


def _frame_blocks(frames: list[tuple[float, str]] | None) -> list[dict]:
    """장면 사진들 (말이 적은 운동·액션 영상도 AI가 화면을 보고 고르게)."""
    if not frames:
        return []
    out: list[dict] = [{"type": "text", "text": "<frames> (what is on screen at each time)"}]
    for t, data in frames:
        out.append({"type": "text", "text": f"{t:.1f}s:"})
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": data}})
    out.append({"type": "text", "text": "</frames>"})
    return out


def _source_time(h_parts: list[tuple[float, float]], t: float) -> float:
    """숏폼 안에서 t초 → 원본 시간 (여러 장면을 이어 붙였을 때)."""
    for a, b in h_parts:
        if t <= b - a:
            return a + t
        t -= b - a
    return h_parts[-1][1]


def _ask_claude(client, sentences: list[Sentence], count: int, min_len: float, max_len: float,
                context: str, account=None, exclude: list[tuple[float, float]] | None = None,
                ref_blocks: list[dict] | None = None, guide: str = "",
                frames: list[tuple[float, str]] | None = None) -> list[Highlight]:
    about = f"<about_video>\n{context}\n</about_video>\n\n" if context else ""
    if guide:
        about += f"<video_type>\n{guide}\n</video_type>\n\n"
    # 레퍼런스와 대본은 계정마다 똑같이 보내므로 캐시해서 두 번째 계정부터 비용을 줄인다
    content = list(ref_blocks or []) + _frame_blocks(frames) + [{"type": "text",
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
    out = []
    for h in json.loads(text)["highlights"]:
        parts = [(float(p["start"]), float(p["end"])) for p in h.get("parts", [])
                 if float(p["end"]) - float(p["start"]) >= 1.0]
        hl = _make(h, account)
        if len(parts) > 1:
            hl.parts = [list(p) for p in parts]
            hl.start, hl.end = min(a for a, _ in parts), max(b for _, b in parts)
            rt = float(h.get("rehook_time", 0) or 0)
            hl.rehook_at = _source_time(parts, rt) if rt > 0 else 0.0
        out.append(hl)
    return out


def _make(h: dict, account) -> Highlight:
    return (Highlight(float(h["start"]), float(h["end"]), clean_title(h["title"]),
                      h["reason"], int(h["score"]), h["keywords"], h["caption"],
                      h["label"], h["speaker"], h["bottom"], h.get("sub_title", ""),
                      account.no if account is not None else 0,
                      h.get("hook_text", ""), h.get("rehook_text", ""),
                      # 원본 기준 시간으로 저장 (검증 단계에서 시작점이 바뀌어도 그 장면에 뜨게)
                      float(h["start"]) + float(h.get("rehook_time", 0) or 0)
                      if float(h.get("rehook_time", 0) or 0) > 0 else 0.0,
                      h.get("bgm_mood", ""),
                      [clean_title(t) for t in h.get("title_options", []) if t.strip()]))


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
return them unchanged. Also check every title against the title rules in <video_type>
(short, plain words, no "/" or other symbols, a curiosity gap with a concrete fact, not
giving away the answer) and rewrite any title that breaks them. Return the title that
would win an A/B test for stopping a stranger's scroll: the proposed one, one of the other
title ideas, or a better one you write. A title that only names the clip's topic is never
acceptable, even for informational accounts. verdict: one Korean sentence on why it works or why it fails."""

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
        nl = lambda t: t.replace(chr(10), chr(92) + "n")
        opts = [o for o in h.title_options if o != h.title]
        other = ("other title ideas: " + " | ".join(nl(o) for o in opts) + "\n") if opts else ""
        parts.append(f"<candidate id=\"{i}\">\nproposed: {h.start:.1f}-{h.end:.1f}s\n"
                     f"title: {nl(h.title)}{sub}\n{other}"
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
        if r["end"] > r["start"] and len(h.parts) < 2:  # 이어 붙인 숏폼은 장면 구성을 그대로 둔다
            h.start, h.end = float(r["start"]), float(r["end"])
        if r["title"].strip():
            h.title = clean_title(r["title"])
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
    frames: list[tuple[float, str]] | None = None,
    check: bool = True,
) -> list[Highlight]:
    """1) 후보를 넉넉히 뽑고 2) 엄격하게 다시 검증해서 통과한 것만 고른다.

    frames: 장면 사진 (말이 적은 영상용). check=False면 2)를 건너뛴다 (운동처럼 화면이 중요한 영상).
    """
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
                                  exclude, ref_blocks, guide, frames)
    if exclude:  # 다른 계정이 이미 쓴 구간과 겹치면 뺀다
        candidates = [h for h in candidates if not _overlaps(h, exclude)]
    if not check:
        picked = sorted(candidates, key=lambda h: -h.score)
    else:
        print(f"  후보 {len(candidates)}개를 다시 꼼꼼히 검증하는 중...")
        try:
            picked = verify(client, candidates, lines, min_len=min_len, max_len=max_len,
                            context=context, account=account, guide=guide)
        except Exception as e:  # 검증이 실패해도 1단계 결과로 계속
            print(f"  (검증 단계 건너뜀: {type(e).__name__}: {str(e)[:100]})")
            picked = sorted(candidates, key=lambda h: -h.score)
    if exclude:
        picked = [h for h in picked if not _overlaps(h, exclude)]
    result = clean(picked, lines, count=count, min_len=min_len, max_len=max_len)
    if len(result) < count:
        # 검증 기준에 못 미쳐도 빈손으로 끝내지 않는다: 남은 후보 중 점수 높은 것으로 채운다
        rest = sorted((h for h in candidates if h not in picked), key=lambda h: -h.score)
        if exclude:
            rest = [h for h in rest if not _overlaps(h, exclude)]
        more = clean(result + rest, lines, count=count, min_len=min_len, max_len=max_len)
        if len(more) > len(result):
            print(f"  확실한 하이라이트가 {len(result)}개라, 검증 기준엔 조금 못 미치지만 가장 나은 "
                  f"구간 {len(more) - len(result)}개를 더해 {len(more)}개를 만들어요.")
            result = more
        else:
            print(f"  확실한 하이라이트가 {len(result)}개뿐이라 {len(result)}개만 만들어요.")
    return result


def _overlaps(h: Highlight, used) -> bool:
    """h의 장면 중 하나라도 used 구간들과 겹치는지."""
    return any(a < d and c < b for a, b in h.pieces() for c, d in used)


def clean(
    highlights: list[Highlight],
    sentences: list[Sentence],
    *,
    count: int,
    min_len: float,
    max_len: float,
) -> list[Highlight]:
    """문장 경계에 맞추고, 길이를 보정하고, 겹치는 구간을 제거한다.

    말이 없는 영상(문장이 없음)이나 여러 장면을 이어 붙인 숏폼은 AI가 고른 시간을 그대로 쓴다.
    """
    starts = sorted(s.start for s in sentences)
    ends = sorted(s.end for s in sentences)

    def nearest(sorted_ts: list[float], t: float) -> float:
        i = bisect_left(sorted_ts, t)
        return min(sorted_ts[max(i - 1, 0):i + 1], key=lambda x: abs(x - t))

    out: list[Highlight] = []
    for h in highlights:
        if len(h.parts) > 1:
            parts = [(a, b) for a, b in h.pieces() if b > a]  # 보여 줄 순서는 그대로
            kept, total = [], 0.0
            for a, b in parts:  # 너무 길면 뒤쪽 장면부터 줄인다
                if total + (b - a) > max_len:
                    b = a + max(max_len - total, 0)
                if b - a >= 1.0 and not any(a < d and c < b for c, d in kept):
                    kept.append((a, b))
                    total += b - a
            if not kept:
                continue
            h.parts = [list(p) for p in kept]
            h.start, h.end = min(a for a, _ in kept), max(b for _, b in kept)
        elif starts:
            # 가까운 문장 시작/끝으로 맞춘다 (말이 없는 곳이라 문장이 멀면 AI가 고른 시간 그대로)
            a, b = nearest(starts, h.start), nearest(ends, h.end)
            if abs(a - h.start) <= 1.5:
                h.start = a
            if abs(b - h.end) <= 1.5 and b > h.start:
                h.end = b
            if h.end - h.start > max_len:  # 너무 길면 max_len 안의 마지막 문장 끝에서 자른다
                i = bisect_right(ends, h.start + max_len) - 1
                h.end = ends[i] if i >= 0 and ends[i] > h.start else h.start + max_len
        elif h.end - h.start > max_len:
            h.end = h.start + max_len
        if h.length() < min_len * 0.5:
            continue
        if _overlaps(h, [p for o in out for p in o.pieces()]):
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
