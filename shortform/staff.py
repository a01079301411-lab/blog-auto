"""편집팀: 영상 만드는 일을 담당자별로 나누고, 수정은 그 담당자만 다시 하게 한다.

담당자
- 리서처: 같은 주제로 잘된 영상을 찾아 편집 설계도 (research.py)
- 기획자: 스토리, 쓸 구간, 훅, 상황 설명 글자 순서
- 작가: 제목, 자막 문장, 상황 설명 글자 문구, 업로드 설명글
- 편집자: 앞뒤 자르기, 색 보정, 짤, 군말·무음 자르기, 첫 화면 썸네일
- 음향: 배경음악(켜기·끄기·분위기·크기), 목소리 보정
- 디자이너: 썸네일(글자·장면·사람 위치), 자막 효과
- PD: 수정 요청을 담당자에게 나눠 주고, 완성본을 보고 검수해서 되돌려 보낸다

숏폼마다 '_작업/숏폼NN.json'에 담당자들이 한 일을 저장한다. 수정할 때는 그 기록을 읽어
해당 담당자의 결과만 바꾸고 그 숏폼만 다시 만든다 (음성 인식·구간 고르기·자막 다듬기를
처음부터 다시 하지 않는다).
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from dataclasses import asdict

from .highlights import MODEL, Highlight
from .subtitles import Cue

STAFF = {
    "researcher": "리서처",
    "planner": "기획자",
    "writer": "작가",
    "editor": "편집자",
    "sound": "음향",
    "designer": "디자이너",
}
WORKERS = ["planner", "writer", "editor", "sound", "designer", "researcher"]
MOODS = ["bright", "calm", "tension", "funny"]

# 담당자별로 바꿀 수 있는 설정 (args 이름)
ARG_KEYS = {"auto_color", "inserts", "fillers", "cover_intro", "no_silence_cut",
            "bgm_source", "bgm_volume", "voice_enhance", "karaoke", "sub_pop"}


def _say(text: str) -> None:
    print(text, flush=True)


# ---------------------------------------------------------------- 작업 기록

def work_dir(output: str) -> str:
    return os.path.join(output, "_작업")


def _json_safe(value):
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def save_project(output: str, args, *, total: float, transcript_path: str) -> None:
    """다시 만들 때 필요한 설정을 저장한다."""
    os.makedirs(work_dir(output), exist_ok=True)
    skip = {"func", "frames", "ref_blocks", "lessons"}
    saved = {k: v for k, v in vars(args).items() if k not in skip and _json_safe(v)}
    saved["input"] = os.path.abspath(args.input)
    saved["output"] = os.path.abspath(args.output)
    with open(os.path.join(work_dir(output), "project.json"), "w", encoding="utf-8") as f:
        json.dump({"args": saved, "total": total, "transcript": transcript_path,
                   "saved": time.time()}, f, ensure_ascii=False, indent=1)


def load_project(output: str) -> dict:
    path = os.path.join(work_dir(output), "project.json")
    if not os.path.exists(path):
        raise SystemExit("이 폴더에는 편집팀 작업 기록이 없어요. 새 버전(10.33 이상)으로 "
                         "만든 결과 폴더를 골라 주세요.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def relocate(project: dict, folder: str) -> dict:
    """결과 폴더를 통째로 옮겼으면(휴대폰 작업은 '_완료'로 옮겨진다) 저장된 경로를 새 위치로."""
    old = project["args"].get("output", "")
    folder = os.path.abspath(folder)
    if not old or os.path.normcase(os.path.abspath(old)) == os.path.normcase(folder):
        return project

    def move(p: str) -> str:
        if not p or os.path.exists(p):
            return p
        q = os.path.normpath(os.path.join(folder, os.path.relpath(p, old)))
        return q if os.path.exists(q) else p

    project["args"]["input"] = move(project["args"].get("input", ""))
    project["transcript"] = move(project.get("transcript", ""))
    project["args"]["output"] = folder
    for rec in records(folder):
        rec.data["out"] = os.path.join(folder, os.path.relpath(rec.out, old)) if rec.out else ""
        rec.save()
    with open(os.path.join(work_dir(folder), "project.json"), "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=1)
    return project


class Record:
    """숏폼 하나에 대해 담당자들이 한 일."""

    def __init__(self, output: str, number: int):
        self.output = output
        self.number = number
        self.path = os.path.join(work_dir(output), f"숏폼{number:02d}.json")
        self.cue_path = os.path.join(work_dir(output), f"숏폼{number:02d}.cues.json")
        self.data: dict = {"number": number, "out": "", "highlight": {}, "args": {},
                           "history": [], "review": []}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))

    @property
    def highlight(self) -> Highlight:
        return Highlight(**self.data["highlight"])

    @highlight.setter
    def highlight(self, h: Highlight) -> None:
        self.data["highlight"] = asdict(h)

    @property
    def out(self) -> str:
        return self.data.get("out", "")

    def save(self) -> None:
        os.makedirs(work_dir(self.output), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)

    def log(self, who: str, what: str) -> None:
        self.data["history"].append({"at": time.strftime("%Y-%m-%d %H:%M"), "who": who,
                                     "what": what})

    def apply(self, args):
        """이 숏폼에 담당자들이 바꾼 설정을 얹은 args (원래 args는 그대로)."""
        import argparse

        a = argparse.Namespace(**vars(args))
        for k, v in self.data.get("args", {}).items():
            setattr(a, k, v)
        return a

    # 자막 작가가 다듬은 자막: 다시 만들 때 그대로 쓴다
    def load_cues(self) -> list[Cue] | None:
        try:
            with open(self.cue_path, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            return None
        return [Cue(r["start"], r["end"], r["text"], r.get("who", "main"), r.get("note", ""),
                    r.get("image", ""), [tuple(w) for w in r.get("words", [])]) for r in rows]

    def save_cues(self, cues: list[Cue]) -> None:
        os.makedirs(work_dir(self.output), exist_ok=True)
        with open(self.cue_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in cues], f, ensure_ascii=False)

    def drop_cues(self) -> None:
        if os.path.exists(self.cue_path):
            os.remove(self.cue_path)


def records(output: str) -> list[Record]:
    folder = work_dir(output)
    if not os.path.isdir(folder):
        return []
    nums = sorted(int(m.group(1)) for f in os.listdir(folder)
                  if (m := re.fullmatch(r"숏폼(\d+)\.json", f)))
    return [Record(output, n) for n in nums]


# ---------------------------------------------------------------- Claude

def _client(client=None):
    if client is not None:
        return client
    import anthropic

    return anthropic.Anthropic()


def _ask(system: str, content, schema: dict, *, client=None, effort: str = "medium") -> dict | None:
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    try:
        with _client(client).beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            msg = stream.get_final_message()
    except Exception as e:  # API 키 없음, 네트워크 오류 등
        _say(f"  (AI 호출 실패: {type(e).__name__}: {str(e)[:120]})")
        return None
    if msg.stop_reason != "end_turn":
        _say(f"  (AI 답변이 끝나지 않음: {msg.stop_reason})")
        return None
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        return None


def _num_or_null(kind: str = "number") -> dict:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def _hms(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def describe(rec: Record) -> str:
    """담당자·PD에게 보여 줄 숏폼 현재 상태."""
    h = rec.highlight
    a = rec.data.get("args", {})
    beats = "; ".join(f"{_hms(float(t))} {x}" for t, x in h.beats) or "(없음)"
    pieces = ", ".join(f"{a_:.1f}-{b_:.1f}s" for a_, b_ in h.pieces())
    return (f"[숏폼 {rec.number}] 제목: {h.title}\n"
            f"  원본 구간(초): {pieces} (길이 {h.length():.0f}초)\n"
            f"  훅: {h.hook}\n  상황 설명 글자(원본 시각): {beats}\n"
            f"  썸네일 글자: {h.thumb_text or h.title} / 썸네일 순간: {h.thumb_at or '자동'}\n"
            f"  배경음악 분위기: {h.bgm_mood or '자동'} / 담당자가 바꾼 설정: "
            f"{json.dumps(a, ensure_ascii=False) if a else '없음'}\n"
            f"  업로드 설명: {h.caption[:200]}")


def _cue_lines(rec: Record) -> str:
    cues = rec.load_cues() or []
    return "\n".join(f"{i}. [{_hms(c.start)}] {c.text}" for i, c in enumerate(cues)) or "(자막 없음)"


# ---------------------------------------------------------------- PD: 일 나눠 주기

PD_ROUTE = """\
You are the PD (producer) of a Korean short-form video team. The creator sent a revision
request about finished clips. Split it into tasks for the right staff member, so only
that part is redone and everything else stays exactly as it is.

Staff:
- planner: which moments of the source are used (segments, order, length), the story,
  the hook moment, the timing of on-screen beat captions, choosing a different scene.
- writer: title, subtitle wording/typos, on-screen beat caption wording, upload caption,
  hashtags.
- editor: trimming the start or end, color correction, meme cut-ins, cutting fillers
  or silences, the 0.4s cover frame at the start.
- sound: background music (on/off, mood, volume), voice enhancement.
- designer: thumbnail (text, which moment, where the person is), subtitle effects
  (word-by-word color fill, pop-in).
- researcher: researching new reference videos (only when the creator asks for a new
  reference style or trend).

Rules: clip 0 means every clip. Give each task one concrete instruction in Korean that
the staff member can act on. Do not invent requests the creator did not make. reply is
one or two Korean sentences telling the creator who will do what."""

ROUTE_SCHEMA = _obj({
    "tasks": {"type": "array", "items": _obj({
        "clip": {"type": "integer"},
        "staff": {"type": "string", "enum": WORKERS},
        "instruction": {"type": "string"},
    })},
    "reply": {"type": "string"},
})


def route(request: str, recs: list[Record], *, client=None) -> tuple[list[dict], str]:
    clips = "\n\n".join(describe(r) for r in recs)
    data = _ask(PD_ROUTE, f"<clips>\n{clips}\n</clips>\n\n<request>\n{request}\n</request>",
                ROUTE_SCHEMA, client=client, effort="medium")
    if not data:
        return [], ""
    nums = {r.number for r in recs}
    tasks = []
    for t in data.get("tasks", []):
        if t.get("staff") not in STAFF:
            continue
        targets = sorted(nums) if t.get("clip", 0) == 0 else [t["clip"]]
        tasks += [{"clip": n, "staff": t["staff"], "instruction": t["instruction"]}
                  for n in targets if n in nums]
    return tasks, data.get("reply", "")


# ---------------------------------------------------------------- 담당자들

COMMON = ("You are the {role} of a Korean short-form video team, revising one finished clip. "
          "Change only what the instruction asks, within your own job; keep everything else "
          "exactly as it is (return null for anything you leave unchanged). Never add anything "
          "false; exaggeration is fine, lies are not. Titles are at most 16 Korean characters "
          "and never use a slash.")

PLANNER = COMMON.format(role="planner") + """
You decide which moments of the source footage are used. Segments are in source seconds,
played in the given order (chronological unless a short hook comes first). Use only times
that exist in the transcript. Keep the clip length within the target range unless the
instruction says otherwise. Beats are short on-screen captions at source times inside the
segments; thumb_time is a source time inside the segments that best shows the clip's claim."""

PLANNER_SCHEMA = _obj({
    "segments": {"anyOf": [{"type": "array", "items": _obj({"start": {"type": "number"},
                                                           "end": {"type": "number"}})},
                           {"type": "null"}]},
    "hook": _num_or_null("string"),
    "beats": {"anyOf": [{"type": "array", "items": _obj({"time": {"type": "number"},
                                                        "text": {"type": "string"}})},
                        {"type": "null"}]},
    "thumb_time": _num_or_null(),
    "note": {"type": "string"},
})

WRITER = COMMON.format(role="writer") + """
You own the words: the title, the subtitle lines, the wording of on-screen beat captions,
and the upload caption with hashtags. Subtitle edits keep the speaker's actual words
unless fixing a recognition error or the instruction asks; give the line index and the
full new text of each line you change. For beats, change wording only (keep their times)."""

WRITER_SCHEMA = _obj({
    "title": _num_or_null("string"),
    "caption": _num_or_null("string"),
    "beat_texts": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
    "subtitle_edits": {"type": "array", "items": _obj({"index": {"type": "integer"},
                                                       "text": {"type": "string"}})},
    "note": {"type": "string"},
})

EDITOR = COMMON.format(role="editor") + """
trim_start / trim_end: seconds to cut from the start / end of the clip (negative adds
that much back from the source). Booleans switch: auto color correction, meme cut-ins,
cutting fillers (음, 어), keeping silences (keep_silences true = do not cut pauses), the
0.4s thumbnail cover at the very start."""

EDITOR_SCHEMA = _obj({
    "trim_start": _num_or_null(), "trim_end": _num_or_null(),
    "auto_color": _num_or_null("boolean"), "inserts": _num_or_null("boolean"),
    "fillers": _num_or_null("boolean"), "keep_silences": _num_or_null("boolean"),
    "cover_intro": _num_or_null("boolean"), "note": {"type": "string"},
})

SOUND = COMMON.format(role="sound engineer") + """
music: true = background music on, false = off. mood: bright, calm, tension or funny.
music_volume: 0-1 (0.15 is the normal level; voices must stay clear). voice_enhance:
clean and level the voice."""

SOUND_SCHEMA = _obj({
    "music": _num_or_null("boolean"),
    "mood": {"anyOf": [{"type": "string", "enum": MOODS}, {"type": "null"}]},
    "music_volume": _num_or_null(), "voice_enhance": _num_or_null("boolean"),
    "note": {"type": "string"},
})

DESIGNER = COMMON.format(role="designer") + """
thumb_text: the cover text (short, big, a hook; wrap the 1-2 most important words in
{braces} to color them). thumb_time: source time of the frame (inside the clip's
segments). thumb_focus_x/y: where the main person is in that frame (0-1). karaoke:
color each word as it is spoken. sub_pop: subtitles pop in."""

DESIGNER_SCHEMA = _obj({
    "thumb_text": _num_or_null("string"), "thumb_time": _num_or_null(),
    "thumb_focus_x": _num_or_null(), "thumb_focus_y": _num_or_null(),
    "karaoke": _num_or_null("boolean"), "sub_pop": _num_or_null("boolean"),
    "note": {"type": "string"},
})


def _context(project: dict, rec: Record, others: list[Record]) -> str:
    a = project["args"]
    text = describe(rec)
    if a.get("direction"):
        text = f"<creator_instructions>\n{a['direction']}\n</creator_instructions>\n\n" + text
    if a.get("blueprint_text"):
        text = a["blueprint_text"] + "\n\n" + text
    text += f"\n  목표 길이: {a.get('min_len', 15):g}~{a.get('max_len', 60):g}초"
    if others:
        text += "\n\n<other_clips>\n" + "\n".join(
            f"숏폼 {o.number}: " + ", ".join(f"{x:.1f}-{y:.1f}s" for x, y in o.highlight.pieces())
            for o in others) + "\n</other_clips>"
    return text


def work(task: dict, rec: Record, project: dict, *, transcript=None, others=(),
         client=None) -> str:
    """담당자 한 명이 숏폼 하나를 고친다. 무엇을 했는지 한 줄로 돌려준다."""
    staff, instr = task["staff"], task["instruction"]
    ctx = _context(project, rec, list(others))
    ask = f"{ctx}\n\n<instruction>\n{instr}\n</instruction>"
    h = rec.highlight
    a = rec.data.setdefault("args", {})
    done: list[str] = []

    if staff == "researcher":
        from . import research
        pa = project["args"]
        bp = research.blueprint(guide_key=pa.get("guide", ""), guide_name=pa.get("guide", ""),
                                topic=pa.get("context", "") or "",
                                direction=f"{pa.get('direction', '')}\n{instr}",
                                target=f"{pa.get('min_len', 15):g}~{pa.get('max_len', 60):g}초",
                                client=client, refresh=True)
        research.log(bp)
        if bp:
            pa["blueprint_text"] = research.prompt_text(bp)
            done.append("새 레퍼런스 설계도")
            # 새 설계도로 글을 다시 쓰게 작가에게 넘긴다
            done.append(work({"staff": "writer", "instruction": "새 레퍼런스 설계도에 맞게 제목·"
                              "상황 설명 글자·설명글을 다듬어 주세요. " + instr}, rec, project,
                             client=client))
        return ", ".join(d for d in done if d) or "바꾼 것 없음"

    if staff == "planner":
        from .highlights import format_transcript
        lines = format_transcript(transcript.sentences) if transcript else "(대본 없음)"
        data = _ask(PLANNER, f"<transcript>\n{lines}\n</transcript>\n\n{ask}", PLANNER_SCHEMA,
                    client=client, effort="high")
        if not data:
            return "실패"
        total = float(project.get("total") or 1e9)
        segs = [(max(0.0, float(s["start"])), min(total, float(s["end"])))
                for s in data.get("segments") or [] if float(s["end"]) - float(s["start"]) > 0.5]
        if segs:
            h.parts = [list(s) for s in segs] if len(segs) > 1 else []
            h.start, h.end = min(s for s, _ in segs), max(e for _, e in segs)
            rec.drop_cues()  # 구간이 바뀌면 자막도 새로
            done.append("구간 " + ", ".join(f"{_hms(s)}~{_hms(e)}" for s, e in segs))
        if data.get("hook") is not None:
            h.hook = data["hook"]
            done.append(f"훅 '{h.hook}'")
        if data.get("beats") is not None:
            h.beats = [[float(b["time"]), b["text"]] for b in data["beats"]]
            done.append(f"상황 설명 글자 {len(h.beats)}개")
        if data.get("thumb_time") is not None:
            h.thumb_at = float(data["thumb_time"])
    elif staff == "writer":
        data = _ask(WRITER, f"<subtitles>\n{_cue_lines(rec)}\n</subtitles>\n\n{ask}",
                    WRITER_SCHEMA, client=client)
        if not data:
            return "실패"
        if data.get("title"):
            h.title = data["title"].replace("/", " ").strip()
            done.append(f"제목 '{h.title}'")
        if data.get("caption"):
            h.caption = data["caption"]
            done.append("설명글")
        if data.get("beat_texts"):
            texts = data["beat_texts"]
            h.beats = [[t, texts[i] if i < len(texts) else x] for i, (t, x) in enumerate(h.beats)]
            done.append("상황 설명 문구")
        cues = rec.load_cues()
        edits = [e for e in data.get("subtitle_edits", []) if cues and 0 <= e["index"] < len(cues)]
        for e in edits:
            c = cues[e["index"]]
            if c.text != e["text"]:
                if len(e["text"].split()) != len(c.text.split()):
                    c.words = []  # 단어 수가 바뀌면 단어별 색 채우기 시간은 버린다
                c.text = e["text"]
        if edits:
            rec.save_cues(cues)
            done.append(f"자막 {len(edits)}줄")
    elif staff == "editor":
        data = _ask(EDITOR, ask, EDITOR_SCHEMA, client=client)
        if not data:
            return "실패"
        pieces = [list(p) for p in h.pieces()]
        total = float(project.get("total") or 1e9)
        if data.get("trim_start"):
            pieces[0][0] = min(max(0.0, pieces[0][0] + float(data["trim_start"])), pieces[0][1] - 1)
            done.append(f"앞 {data['trim_start']:+g}초")
        if data.get("trim_end"):
            pieces[-1][1] = max(min(total, pieces[-1][1] - float(data["trim_end"])), pieces[-1][0] + 1)
            done.append(f"뒤 {data['trim_end']:+g}초")
        if data.get("trim_start") or data.get("trim_end"):
            h.parts = pieces if len(pieces) > 1 else []
            h.start, h.end = min(p[0] for p in pieces), max(p[1] for p in pieces)
            rec.drop_cues()
        for key, name in (("auto_color", "색 보정"), ("inserts", "짤"), ("fillers", "군말 자르기"),
                          ("cover_intro", "첫 화면 썸네일")):
            if data.get(key) is not None:
                a[key] = bool(data[key])
                done.append(f"{name} {'켬' if a[key] else '끔'}")
        if data.get("keep_silences") is not None:
            a["no_silence_cut"] = bool(data["keep_silences"])
            done.append("무음 " + ("살림" if a["no_silence_cut"] else "자르기"))
        if data.get("fillers") is not None or data.get("keep_silences") is not None:
            rec.drop_cues()
    elif staff == "sound":
        data = _ask(SOUND, ask, SOUND_SCHEMA, client=client)
        if not data:
            return "실패"
        if data.get("music") is not None:
            a["bgm_source"] = (project["args"].get("bgm_source") if project["args"].get("bgm_source")
                               != "none" else "auto") if data["music"] else "none"
            done.append("배경음악 " + ("켬" if data["music"] else "끔"))
        if data.get("mood"):
            h.bgm_mood = data["mood"]
            if a.get("bgm_source") == "none":
                a["bgm_source"] = "auto"
            done.append(f"음악 분위기 {data['mood']}")
        if data.get("music_volume") is not None:
            a["bgm_volume"] = min(max(float(data["music_volume"]), 0.0), 0.6)
            done.append(f"음악 크기 {a['bgm_volume']:.2f}")
        if data.get("voice_enhance") is not None:
            a["voice_enhance"] = bool(data["voice_enhance"])
            done.append("목소리 보정 " + ("켬" if a["voice_enhance"] else "끔"))
    elif staff == "designer":
        data = _ask(DESIGNER, ask, DESIGNER_SCHEMA, client=client)
        if not data:
            return "실패"
        if data.get("thumb_text"):
            h.thumb_text = data["thumb_text"]
            done.append(f"썸네일 글자 '{h.thumb_text}'")
        if data.get("thumb_time") is not None:
            h.thumb_at = float(data["thumb_time"])
            done.append(f"썸네일 장면 {_hms(h.thumb_at)}")
        if data.get("thumb_focus_x") is not None and data.get("thumb_focus_y") is not None:
            h.thumb_focus = [float(data["thumb_focus_x"]), float(data["thumb_focus_y"])]
        for key, name in (("karaoke", "단어 색 채우기"), ("sub_pop", "자막 튀어나오기")):
            if data.get(key) is not None:
                a[key] = bool(data[key])
                done.append(f"{name} {'켬' if a[key] else '끔'}")
    else:
        return "모르는 담당"
    rec.highlight = h
    summary = ", ".join(done) or "바꾼 것 없음"
    if data.get("note"):
        summary += f" ({data['note']})"
    rec.log(STAFF[staff], f"{instr} → {summary}")
    return summary


# ---------------------------------------------------------------- PD: 검수

PD_REVIEW = """\
You are the PD (producer) of a Korean short-form video team doing the final check of a
finished clip before it is posted. You see frames from the finished video (with their
times), the cover thumbnail, the subtitles and the plan. Judge it like a top creator of
this genre: does the first second hook, does the story make sense in order, are the
subtitles correct and in sync with what is happening, are title and thumbnail clickable
and true, is anything repetitive, boring or confusing, does it follow the creator's
instructions and the reference blueprint.

pass = true only if you would post it as is. If not, list at most 3 fixes, each sent to
the one staff member who can fix it (planner: scenes/story/length/beat timing; writer:
title/subtitle words/beat wording/caption; editor: trims/color/cut-ins/fillers; sound:
music/voice; designer: thumbnail/subtitle effects), with a concrete Korean instruction.
Only ask for fixes that are possible with this footage. Write summary in Korean."""

REVIEW_SCHEMA = _obj({
    "score": {"type": "integer"},
    "pass": {"type": "boolean"},
    "summary": {"type": "string"},
    "fixes": {"type": "array", "items": _obj({
        "staff": {"type": "string", "enum": ["planner", "writer", "editor", "sound", "designer"]},
        "instruction": {"type": "string"},
    })},
})


def _frames(video: str, count: int = 8) -> list[tuple[float, str]]:
    from . import media
    from .references import _jpeg

    try:
        dur = media.duration(video)
    except Exception:
        return []
    shots = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(count):
            t = 0.6 + (dur - 1.2) * k / max(count - 1, 1) if dur > 2 else dur / 2
            out = os.path.join(tmp, f"{k}.jpg")
            try:
                media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                           "-i", video, "-frames:v", "1", "-vf", "scale=360:-2", out])
                with open(out, "rb") as f:
                    img = _jpeg(f.read(), 480)
                if img:
                    shots.append((t, img))
            except (RuntimeError, OSError):
                continue
    return shots


def review(rec: Record, project: dict, *, client=None) -> dict | None:
    """완성본을 보고 검수한다. {'pass', 'score', 'summary', 'fixes'}"""
    video = rec.out
    if not video or not os.path.exists(video):
        return None
    content: list[dict] = []
    for t, img in _frames(video):
        content += [{"type": "text", "text": f"frame at {t:.1f}s of the finished clip:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": img}}]
    cover = os.path.splitext(video)[0] + "_썸네일.jpg"
    if os.path.exists(cover):
        from .references import _jpeg
        with open(cover, "rb") as f:
            img = _jpeg(f.read(), 720)
        if img:
            content += [{"type": "text", "text": "cover thumbnail:"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": img}}]
    content.append({"type": "text", "text": _context(project, rec, [])
                    + f"\n\n<subtitles (times in the finished clip)>\n{_cue_lines(rec)}\n</subtitles>"})
    data = _ask(PD_REVIEW, content, REVIEW_SCHEMA, client=client, effort="high")
    if data:
        rec.data.setdefault("review", []).append(
            {"at": time.strftime("%Y-%m-%d %H:%M"), "score": data.get("score"),
             "pass": data.get("pass"), "summary": data.get("summary", "")})
        rec.save()
    return data


def review_loop(rec: Record, project: dict, render, *, transcript=None, others=(),
                rounds: int = 2, client=None) -> None:
    """PD가 검수하고, 고칠 게 있으면 담당자에게 넘겨 다시 만든다 (최대 rounds번)."""
    for k in range(rounds + 1):
        _say(f"  [PD 검수] 완성본을 보는 중{' (다시 만든 뒤)' if k else ''}...")
        data = review(rec, project, client=client)
        if not data:
            return
        _say(f"  PD 점수 {data.get('score', '?')}/10: {data.get('summary', '')}")
        fixes = data.get("fixes") or []
        if data.get("pass") or not fixes:
            _say("  PD 통과")
            return
        if k == rounds:
            _say("  (PD 수정은 여기까지. 남은 의견은 수정 요청으로 보낼 수 있어요)")
            return
        for fx in fixes[:3]:
            _say(f"  → {STAFF[fx['staff']]}에게: {fx['instruction']}")
            did = work(fx, rec, project, transcript=transcript, others=others, client=client)
            _say(f"    {STAFF[fx['staff']]}: {did}")
        rec.save()
        render(rec)


def write_log(output: str, lines: list[str]) -> None:
    with open(os.path.join(output, "수정기록.txt"), "a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M')}]\n" + "\n".join(lines) + "\n")


def b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()
