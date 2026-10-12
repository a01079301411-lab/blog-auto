"""롱폼 편집: 직접 찍은 여러 촬영본 + 기획안 → 편집 순서표(EDL) → 롱폼 영상.

1) 촬영본마다 음성 인식 (결과는 작업 폴더에 저장해 다시 쓰기)
2) 촬영본 장면 몇 장 + 대본 + 기획안을 Claude에게 보내 편집 순서표를 받는다
   - 기획안의 흐름(오프닝 → 세부 기획 → 엔딩)대로 챕터를 나누고
   - NG 컷·같은 말 다시 찍은 컷은 가장 좋은 테이크만 남기고, 의미 없는 구간은 뺀다
3) 사용자가 순서표를 보고 고친다 (프로그램 창 또는 메모장)
4) longrender로 1920x1080 영상, 자막, 챕터, 썸네일, 프리미어 XML을 만든다
"""
from __future__ import annotations

import base64
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field

from . import media
from .highlights import MODEL, split_lines
from .transcribe import Sentence, Transcript, transcribe

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts")


@dataclass
class Segment:
    clip: int           # 촬영본 번호 (clips 목록의 위치)
    start: float        # 촬영본 안에서의 시간 (초)
    end: float
    note: str = ""      # 어떤 장면인지 (편집자 메모)
    on: bool = True     # 영상에 넣을지


@dataclass
class Chapter:
    title: str
    segments: list[Segment] = field(default_factory=list)


@dataclass
class Edl:
    clips: list[str]
    title: str = ""
    description: str = ""
    thumbnail_text: str = ""
    thumbnail_clip: int = 0
    thumbnail_time: float = 0.0
    commerce: bool = False
    chapters: list[Chapter] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # 뺀 구간과 이유 (참고용)

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "Edl":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        chapters = [Chapter(c["title"], [Segment(**s) for s in c["segments"]])
                    for c in data.pop("chapters", [])]
        return cls(**data, chapters=chapters)

    def kept(self) -> list[tuple[int, Segment]]:
        """(챕터 번호, 구간) — 영상에 넣는 구간만, 순서대로."""
        return [(i, s) for i, c in enumerate(self.chapters) for s in c.segments if s.on]


# ---------- 촬영본 ----------

def collect_clips(paths: list[str]) -> list[str]:
    """파일·폴더 목록 → 촬영본 파일 목록. 폴더는 안의 영상을 이름순으로."""
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(f for f in glob.glob(os.path.join(p, "*"))
                          if f.lower().endswith(VIDEO_EXT))
        elif os.path.isfile(p):
            out.append(p)
    seen = set()
    return [os.path.abspath(p) for p in out
            if not (os.path.abspath(p) in seen or seen.add(os.path.abspath(p)))]


def _hms(t: float) -> str:
    t = round(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def _tc(t: float) -> str:
    """순서표용 시간: 0.1초까지 (예: 1:05.3)."""
    t = round(max(t, 0.0), 1)
    m, sec = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02}:{sec:04.1f}" if h else f"{m}:{sec:04.1f}"


def transcribe_all(clips: list[str], workdir: str, *, model: str, language: str | None,
                   device: str) -> list[Transcript]:
    out = []
    for i, clip in enumerate(clips, 1):
        name = os.path.splitext(os.path.basename(clip))[0]
        cache = os.path.join(workdir, f"{i:03}_{_safe(name)}.{model}.transcript.json")
        print(f"  [{i}/{len(clips)}] {os.path.basename(clip)}")
        if not media.has_audio(clip):
            out.append(Transcript([], [], language))
            continue
        out.append(transcribe(clip, model=model, language=language, cache=cache, device=device))
    return out


def _safe(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")[:60] or "clip"


def _frames(clip: str, duration: float, count: int, workdir: str) -> list[tuple[float, str]]:
    """장면 몇 장 (Claude가 말 없는 장면도 알아보게). (시간, base64 JPEG)"""
    shots = []
    for k in range(count):
        t = duration * (k + 0.5) / count
        out = os.path.join(workdir, f"frame_{k}.jpg")
        try:
            media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                       "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1",
                       "-vf", "scale=480:-2", "-q:v", "6", out])
            with open(out, "rb") as f:
                shots.append((t, base64.b64encode(f.read()).decode()))
        except (RuntimeError, OSError):
            continue  # 장면을 못 뽑아도 대본만으로 진행
    return shots


# ---------- Claude ----------

SYSTEM_PROMPT = """\
You are a senior Korean YouTube vlog editor. You cut a long-form video (vlog / daily
life, family, hobby, work) from a creator's raw footage, following their content plan.

You receive:
- the channel concept and the plan for this episode (기획안): topic, opening, detailed
  flow, cautions, ad notes. Follow the plan's flow and intent.
- every raw clip, in shooting order: file name, length, orientation, a few frames
  (with their times) and the speech transcript as "[start-end] text" lines.

Build the edit (EDL):
- chapters: the story in viewing order. Start with a strong opening (hook) as the plan
  describes. If the plan's opening was not shot, open with the most gripping moment
  of the footage as a cold open, then continue. Chapter titles are short Korean
  phrases (at most 16 characters), usable as YouTube chapter names.
- segments inside each chapter, in viewing order: {clip, start, end, note}. Times are
  seconds inside that clip. You may reorder freely and use the same clip in different
  chapters, but never overlap ranges of the same clip.
- Remove NG takes: false starts, flubbed lines, repeated takes of the same line (keep
  only the best, usually the last complete one), "다시", "컷", camera checks, setup,
  dead air, accidental recordings, shaky transitions with nothing happening.
- Keep moments without speech when they show something worth seeing (scenery,
  reactions, the activity itself), usually 2-6 seconds each, as b-roll between talk.
- With speech, start at the start of a transcript line and end at the end of a line;
  never cut in the middle of a sentence.
- Respect the plan's cautions (e.g. personal information, a child who did not want
  to be filmed). Drop such moments.
- note: what happens in the segment, in Korean, one short phrase.
- dropped: the notable ranges you removed and why (Korean, short), so the creator can
  check your decisions.
- title: a YouTube title in Korean that fits the channel concept and the plan.
- description: a YouTube description in Korean (2-4 sentences + 3-5 hashtags). Do not
  write chapter timestamps; they are added automatically.
- thumbnail: pick the most expressive frame (clip + time) and write thumbnail_text,
  1-2 short Korean lines separated by "\\n", at most 10 characters per line."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "thumbnail_text": {"type": "string"},
        "thumbnail_clip": {"type": "integer"},
        "thumbnail_time": {"type": "number"},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "clip": {"type": "integer"},
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "note": {"type": "string"},
                            },
                            "required": ["clip", "start", "end", "note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "segments"],
                "additionalProperties": False,
            },
        },
        "dropped": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip": {"type": "integer"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["clip", "start", "end", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "thumbnail_text", "thumbnail_clip", "thumbnail_time",
                 "chapters", "dropped"],
    "additionalProperties": False,
}

MAX_IMAGES = 90  # 요청 하나에 넣을 장면 수 상한


def _lines(t: Transcript) -> list[Sentence]:
    return split_lines(t.words) if t.words else t.sentences


def _request(clips, durations, verticals, transcripts, *, plan: str, context: str,
             target_minutes: float, frames: bool, workdir: str) -> list[dict]:
    content: list[dict] = []
    head = []
    if context:
        head.append(f"<channel>\n{context}\n</channel>")
    head.append(f"<plan>\n{plan.strip() or '(기획안 없음: 촬영본 흐름을 살려 자연스럽게 구성)'}\n</plan>")
    content.append({"type": "text", "text": "\n\n".join(head)})

    per_clip = 0
    if frames and clips:
        per_clip = max(1, min(4, MAX_IMAGES // len(clips)))
    used = 0
    for i, clip in enumerate(clips):
        kind = "vertical" if verticals[i] else "horizontal"
        content.append({"type": "text", "text":
                        f"<clip id=\"{i}\" file=\"{os.path.basename(clip)}\" "
                        f"length=\"{durations[i]:.1f}s\" orientation=\"{kind}\">"})
        n = min(per_clip, MAX_IMAGES - used)
        if n > 0:
            with tempfile.TemporaryDirectory(dir=workdir) as tmp:
                for t, data in _frames(clip, durations[i], n, tmp):
                    content.append({"type": "text", "text": f"frame at {t:.1f}s:"})
                    content.append({"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": data}})
                    used += 1
        lines = _lines(transcripts[i])
        speech = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in lines)
        content.append({"type": "text",
                        "text": f"<transcript>\n{speech or '(말소리 없음)'}\n</transcript>\n</clip>"})

    total = sum(durations)
    if target_minutes > 0:
        length = f"Aim for about {target_minutes:.0f} minutes in total."
    else:
        length = ("Choose the length the material deserves: keep what is engaging, cut the "
                  "rest. Typical vlogs end up 8-20 minutes.")
    content.append({"type": "text", "text":
                    f"There are {len(clips)} clips, {_hms(total)} of footage. {length} "
                    "Build the EDL."})
    return content


def ask_claude(clips, durations, verticals, transcripts, *, plan: str, context: str,
               target_minutes: float = 0, frames: bool = True, workdir: str,
               client=None) -> Edl:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    content = _request(clips, durations, verticals, transcripts, plan=plan, context=context,
                       target_minutes=target_minutes, frames=frames, workdir=workdir)
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 요청을 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("편집 순서표가 너무 길어 잘렸어요. 촬영본을 나눠서 넣어 주세요.")
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    edl = Edl(clips=list(clips), title=data["title"], description=data["description"],
              thumbnail_text=data["thumbnail_text"].replace("\\n", "\n"),
              thumbnail_clip=int(data["thumbnail_clip"]),
              thumbnail_time=float(data["thumbnail_time"]),
              chapters=[Chapter(c["title"], [Segment(int(s["clip"]), float(s["start"]),
                                                     float(s["end"]), s["note"])
                                             for s in c["segments"]])
                        for c in data["chapters"]],
              dropped=data["dropped"])
    return tidy(edl, durations, transcripts)


def tidy(edl: Edl, durations: list[float], transcripts: list[Transcript]) -> Edl:
    """Claude가 준 시간을 촬영본 길이 안으로, 문장 중간이면 문장 경계로 맞춘다."""
    used: dict[int, list[tuple[float, float]]] = {}
    for ch in edl.chapters:
        good = []
        for s in ch.segments:
            if not 0 <= s.clip < len(durations):
                continue
            lines = _lines(transcripts[s.clip])
            for ln in lines:  # 말하는 도중에 시작·끝나면 그 문장 처음·끝으로
                if ln.start < s.start < ln.end:
                    s.start = ln.start
                if ln.start < s.end < ln.end:
                    s.end = ln.end
            s.start = max(0.0, s.start - 0.1)
            s.end = min(durations[s.clip], s.end + 0.15)
            if s.end - s.start < 0.8:
                continue
            # 같은 촬영본에서 이미 쓴 구간과 겹치면 겹치는 만큼 줄인다
            for a, b in used.get(s.clip, []):
                if s.start < b and a < s.end:
                    if a <= s.start:
                        s.start = b
                    else:
                        s.end = min(s.end, a)
            if s.end - s.start < 0.8:
                continue
            used.setdefault(s.clip, []).append((s.start, s.end))
            good.append(s)
        ch.segments = good
    edl.chapters = [c for c in edl.chapters if c.segments]
    if not 0 <= edl.thumbnail_clip < len(durations):
        edl.thumbnail_clip, edl.thumbnail_time = 0, 0.0
    edl.thumbnail_time = min(max(edl.thumbnail_time, 0.0), durations[edl.thumbnail_clip] - 0.1)
    return edl


def plan_from_order(clips: list[str], durations: list[float]) -> Edl:
    """Claude 없이: 촬영본을 순서대로 통째로 잇는 순서표 (API 키가 없을 때)."""
    return Edl(clips=list(clips), title="", chapters=[
        Chapter(os.path.splitext(os.path.basename(c))[0][:16], [Segment(i, 0.0, durations[i])])
        for i, c in enumerate(clips)])


# ---------- 순서표 검토 (메모장용) ----------

REVIEW_HEADER = """\
# ───────────────────────────────────────────────
#  롱폼 편집 순서표
# ───────────────────────────────────────────────
#  - 맨 앞의 [O]를 [X]로 바꾸면 그 장면은 빼요.
#  - 줄을 위아래로 옮기면 순서가 바뀌어요. (## 줄은 챕터 제목)
#  - 구간(시작 ~ 끝)과 챕터 제목, 맨 위 제목·썸네일 문구를 고칠 수 있어요.
#  - 다 고쳤으면 저장(Ctrl+S)하고 메모장을 닫으세요. 닫으면 바로 만들기 시작해요.
# ───────────────────────────────────────────────
"""


def write_review(path: str, edl: Edl) -> None:
    lines = [REVIEW_HEADER,
             f"제목: {edl.title}",
             f"썸네일: {edl.thumbnail_text.replace(chr(10), ' / ')}", ""]
    n = 0
    for ch in edl.chapters:
        lines.append(f"## {ch.title}")
        for s in ch.segments:
            n += 1
            mark = "O" if s.on else "X"
            name = os.path.basename(edl.clips[s.clip])
            lines.append(f"[{mark}] {n:03}  {name}  {_tc(s.start)} ~ {_tc(s.end)}"
                         f"  ({s.end - s.start:.0f}초)  | {s.note}")
        lines.append("")
    if edl.dropped:
        lines.append("# 뺀 구간 (참고, 넣고 싶으면 위에 줄을 직접 추가하세요)")
        for d in edl.dropped:
            c = d.get("clip", 0)
            name = os.path.basename(edl.clips[c]) if 0 <= c < len(edl.clips) else "?"
            lines.append(f"#   {name}  {_tc(d['start'])} ~ {_tc(d['end'])}  | {d['reason']}")
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def _sec(text: str) -> float:
    total = 0.0
    for part in text.strip().split(":"):
        total = total * 60 + float(part)
    return total


_ROW = re.compile(r"^\s*\[([OoXx○×])\]\s*(\d+)?\s+(.+?)\s+([\d:.]+)\s*~\s*([\d:.]+)(.*)$")


def read_review(path: str, edl: Edl) -> Edl:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    names = {os.path.basename(c): i for i, c in enumerate(edl.clips)}
    chapters: list[Chapter] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("제목:"):
            edl.title = line[3:].strip()
        elif line.startswith("썸네일:"):
            edl.thumbnail_text = "\n".join(p.strip() for p in line[4:].split("/") if p.strip())
        elif line.startswith("## "):
            chapters.append(Chapter(line[3:].strip()))
        elif m := _ROW.match(line):
            clip = names.get(m.group(3).strip())
            if clip is None:
                print(f"  (촬영본 이름을 못 찾아 건너뜀: {m.group(3)})")
                continue
            try:
                a, b = _sec(m.group(4)), _sec(m.group(5))
            except ValueError:
                print(f"  (구간을 못 읽어 건너뜀: {line})")
                continue
            if b <= a:
                continue
            note = m.group(6).split("|", 1)[1].strip() if "|" in m.group(6) else ""
            if not chapters:
                chapters.append(Chapter("오프닝"))
            chapters[-1].segments.append(Segment(clip, a, b, note, m.group(1) in "Oo○"))
    edl.chapters = [c for c in chapters if c.segments]
    return edl


def review(workdir: str, edl: Edl, edl_path: str) -> Edl:
    if os.environ.get("SHORTFORM_GUI"):
        done = edl_path + ".done"
        if os.path.exists(done):
            os.remove(done)
        print("\n[순서표 검토] 창에서 편집 순서를 확인해 주세요.")
        print(f"@@LONGREVIEW@@ {edl_path}", flush=True)
        while not os.path.exists(done):
            time.sleep(0.3)
        os.remove(done)
        return Edl.load(edl_path)
    path = os.path.join(workdir, "..", "편집_순서표.txt")
    path = os.path.abspath(path)
    write_review(path, edl)
    if sys.platform == "win32":
        print("\n[순서표 검토] 메모장에서 순서를 확인·수정하고, 저장한 뒤 메모장을 닫아 주세요.")
        subprocess.run(["notepad.exe", path])
    else:
        print(f"\n[순서표 검토] 파일을 고친 뒤 Enter를 누르세요: {path}")
        input()
    edl = read_review(path, edl)
    edl.save(edl_path)
    return edl


# ---------- 전체 실행 ----------

def run(args) -> str:
    """롱폼 하나를 만든다. 결과 폴더를 돌려준다."""
    from . import longrender
    from . import plan as plan_mod

    clips = collect_clips(args.inputs)
    if not clips:
        raise RuntimeError("촬영본 영상을 찾지 못했어요.")
    from .settings import long_output_dir

    out_dir = os.path.abspath(args.output or long_output_dir(args.inputs))
    work = os.path.join(out_dir, "작업파일")
    os.makedirs(work, exist_ok=True)

    plan_text = ""
    if args.plan:
        if os.path.isfile(args.plan):
            plan_text = plan_mod.read(args.plan)
            print(f"[기획안] {os.path.basename(args.plan)} ({len(plan_text)}자)")
        else:
            plan_text = args.plan
    print(f"[촬영본] {len(clips)}개")
    durations = [media.duration(c) for c in clips]
    verticals = [media.is_vertical(c) for c in clips]
    for c, d, v in zip(clips, durations, verticals):
        print(f"  {os.path.basename(c)}  {_hms(d)}{'  (세로)' if v else ''}")

    print("\n[음성 인식]")
    transcripts = transcribe_all(clips, work, model=args.model,
                                 language=args.language or None, device=args.device)

    edl_path = os.path.join(work, "edl.json")
    edl = None
    if os.path.exists(edl_path) and not args.replan:
        old = Edl.load(edl_path)
        if old.clips == clips:
            edl = old
            print("\n[편집 순서] 지난번 순서표를 다시 써요. (새로 짜려면 '다시 기획' 옵션)")
    if edl is None:
        print("\n[편집 순서] Claude가 기획안과 촬영본을 보고 편집 순서를 짜는 중... (몇 분 걸려요)")
        try:
            edl = ask_claude(clips, durations, verticals, transcripts, plan=plan_text,
                             context=args.context or "", target_minutes=args.minutes,
                             frames=args.frames, workdir=work)
        except Exception as e:
            if not args.allow_fallback:
                raise
            print(f"  (Claude를 쓸 수 없어 촬영 순서대로 이어 붙여요: {type(e).__name__}: {e})")
            edl = plan_from_order(clips, durations)
        edl.save(edl_path)
    edl.commerce = args.commerce
    kept = edl.kept()
    total = sum(s.end - s.start for _, s in kept)
    print(f"  챕터 {len(edl.chapters)}개, 장면 {len(kept)}개, 약 {_hms(total)}")
    for ch in edl.chapters:
        print(f"   · {ch.title} ({len(ch.segments)}장면)")

    if args.review:
        edl = review(work, edl, edl_path)
        edl.commerce = args.commerce
        edl.save(edl_path)
    if not edl.kept():
        raise RuntimeError("영상에 넣을 장면이 없어요.")

    longrender.render(edl, transcripts, out_dir, work, args)
    return out_dir
