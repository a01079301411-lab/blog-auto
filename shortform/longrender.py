"""롱폼 순서표(EDL) → 1920x1080 영상과 함께 쓰는 파일들.

1) 장면마다 같은 규격(1920x1080, 30fps, 48kHz 스테레오)으로 따로 인코딩한다.
   세로 영상은 흐린 배경을 깔고 가운데에 둔다. 말하는 장면은 말과 말 사이의 긴
   무음만 잘라낸다(말 없는 풍경 장면은 그대로). 장면 파일은 저장해 두므로
   중간에 멈춰도 다시 실행하면 이어서 한다.
2) 장면들을 이어 붙이고, 마지막에 한 번만 자막·챕터 제목·유료광고 표시를 입히고
   배경음악을 깐다(말할 때는 자동으로 줄어든다).
3) 함께 만드는 것: 자막 SRT, 유튜브 제목·설명(챕터 시간 포함), 썸네일,
   프리미어 프로에서 이어서 편집할 수 있는 XML.
"""
from __future__ import annotations

import hashlib
import os
import random
import shutil
from dataclasses import dataclass
from urllib.parse import quote
from xml.sax.saxutils import escape

from . import fonts, media
from .longform import Edl, _hms, _safe
from .silence import detect_silences, drop_fillers
from .styles import OTHER_COLOR, _c, _esc, _note, _ts
from .subfix import fix_cues
from .subtitles import Cue, Word, build_cues, write_srt

# 출력 규격. render()가 촬영본에 맞춰 바꾼다 (60fps로 찍었으면 60fps, 4K 설정이면 3840x2160)
W, H, FPS = 1920, 1080, 30
SUB_W, SUB_H = 1920, 1080  # 자막 좌표 기준 (해상도가 달라도 같은 크기로 보이게)
# 화질: 장면 조각은 거의 손실 없이, 마지막 한 번만 좋은 설정으로 압축한다
PIECE_CRF, PIECE_PRESET = 12, "faster"
FINAL_CRF, FINAL_PRESET = 17, "medium"
SUB_FONTS = ["Pretendard ExtraBold", "Pretendard Bold", "Gmarket Sans TTF Bold",
             "GmarketSansBold", "NanumSquare ExtraBold", "NanumSquareEB"]
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


@dataclass
class Piece:
    clip: int
    start: float
    end: float
    chapter: int
    path: str = ""
    offset: float = 0.0     # 완성 영상에서 시작하는 시간
    length: float = 0.0


# ---------- 장면 나누기 ----------

def _jumpcut(clip: str, start: float, end: float, words: list[Word], *,
             min_silence: float, padding: float = 0.3) -> list[tuple[float, float]]:
    """말과 말 사이의 긴 무음만 뺀다. 첫 말 전·마지막 말 뒤, 말 없는 장면은 그대로."""
    inside = [w for w in words if start <= (w.start + w.end) / 2 <= end]
    if len(inside) < 2:
        return [(start, end)]
    first, last = inside[0].start, inside[-1].end
    keeps, cursor = [], start
    for s, e in detect_silences(clip, min_silence=min_silence, start=start, end=end):
        if s < first or e > last:
            continue
        if any(w.start < e - padding and s + padding < w.end for w in inside):
            continue  # 말소리가 작아서 무음으로 잡힌 경우
        cut_a, cut_b = s + padding, e - padding
        if cut_b - cut_a < 0.3:
            continue
        keeps.append((cursor, cut_a))
        cursor = cut_b
    keeps.append((cursor, end))
    return [(a, b) for a, b in keeps if b - a >= 0.2]


def make_pieces(edl: Edl, transcripts, *, jumpcut: bool, min_silence: float,
                fillers: bool = False) -> list[Piece]:
    pieces = []
    dropped = 0
    for ch, seg in edl.kept():
        clip = edl.clips[seg.clip]
        words = transcripts[seg.clip].words
        ranges = (_jumpcut(clip, seg.start, seg.end, words, min_silence=min_silence)
                  if jumpcut else [(seg.start, seg.end)])
        if fillers:  # '음', '어' 같은 군말 잘라내기
            before = len(ranges)
            ranges = drop_fillers(ranges, [w for w in words if seg.start <= w.start < seg.end])
            dropped += len(ranges) - before
        pieces += [Piece(seg.clip, a, b, ch) for a, b in ranges]
    if dropped:
        print(f"  군말(음·어) {dropped}군데 잘라냄")
    return pieces


# ---------- 장면 인코딩 ----------

def _norm_filter(w: int, h: int, width: int | None = None, height: int | None = None,
                 pre: str = "") -> str:
    """[0:v] → [v] 를 width x height 화면에 맞춘다. pre: 맨 앞에 넣을 필터 (HDR 색 변환 등)."""
    width, height = width or W, height or H
    sc = "flags=lanczos"  # 크기를 바꿀 때 선명하게
    if not w or not h:
        return f"[0:v]{pre}scale={width}:{height}:{sc},setsar=1,format=yuv420p[v]"
    ar, target = w / h, width / height
    if abs(ar - target) < 0.03:
        if (w, h) == (width, height):
            return f"[0:v]{pre}setsar=1,format=yuv420p[v]"
        return f"[0:v]{pre}scale={width}:{height}:{sc},setsar=1,format=yuv420p[v]"
    if ar > target:  # 더 넓은 영상: 위아래 검은 띠
        return (f"[0:v]{pre}scale={width}:{height}:force_original_aspect_ratio=decrease:{sc},"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v]")
    # 세로 영상: 같은 영상을 크게 흐리게 깔고 가운데에 원본
    return (f"[0:v]{pre}split[a][b];"
            f"[a]scale={width // 4}:{height // 4}:force_original_aspect_ratio=increase,"
            f"crop={width // 4}:{height // 4},boxblur=8:2,eq=brightness=-0.08,"
            f"scale={width}:{height}[bg];"
            f"[b]scale=-2:{height}:{sc}[fg];"
            f"[bg][fg]overlay=(W-w)/2:0,setsar=1,format=yuv420p[v]")


def _encode_piece(src: str, p: Piece, out: str, size: tuple[int, int], audio: bool,
                  pre: str = "") -> None:
    frames = max(1, round((p.end - p.start) * FPS))
    dur = frames / FPS  # 영상·소리 길이를 프레임 단위로 똑같이 맞춰야 이어 붙일 때 싱크가 안 밀린다
    graph = _norm_filter(*size, pre=pre) + f";[v]fps={FPS}[vo]"
    fade = min(0.03, dur / 4)
    a_in = "[0:a]" if audio else "[1:a]"
    graph += (f";{a_in}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"afade=t=in:d={fade:.3f},apad,atrim=0:{dur:.4f},"
              f"afade=t=out:st={dur - fade:.4f}:d={fade:.3f}[ao]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{p.start:.3f}", "-to", f"{p.end:.3f}", "-i", src]
    if not audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    tmp = out + ".tmp.mp4"
    media.run(cmd + ["-filter_complex", graph, "-map", "[vo]", "-map", "[ao]",
                     "-t", f"{dur:.4f}",
                     "-c:v", "libx264", "-preset", PIECE_PRESET, "-crf", str(PIECE_CRF),
                     "-pix_fmt", "yuv420p", "-r", str(FPS), *media.COLOR_TAGS,
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", tmp])
    os.replace(tmp, out)


def encode_pieces(edl: Edl, pieces: list[Piece], work: str) -> None:
    folder = os.path.join(work, "장면")
    os.makedirs(folder, exist_ok=True)
    info = {}
    offset = 0.0
    for i, p in enumerate(pieces, 1):
        src = edl.clips[p.clip]
        if src not in info:
            info[src] = (media.display_size(src), media.has_audio(src),
                         os.path.getmtime(src), media.hdr_to_sdr(src))
        size, audio, mtime, pre = info[src]
        key = hashlib.md5(f"v2|{W}x{H}@{FPS}|{src}|{mtime}|{p.start:.3f}|{p.end:.3f}".encode()
                          ).hexdigest()[:16]
        p.path = os.path.join(folder, f"{key}.mp4")
        label = f"  [{i}/{len(pieces)}] {os.path.basename(src)} {_hms(p.start)}~{_hms(p.end)}"
        if os.path.exists(p.path):
            print(f"\r{label} (저장된 장면 사용)" + " " * 10, end="", flush=True)
        else:
            print(f"\r{label}" + " " * 20, end="", flush=True)
            _encode_piece(src, p, p.path, size, audio, pre)
        from . import progress
        progress.report(i / len(pieces), f"장면 {i}/{len(pieces)}")
        p.offset = offset
        p.length = round((p.end - p.start) * FPS) / FPS
        offset += p.length
    print()


def concat(pieces: list[Piece], out: str) -> None:
    listing = out + ".list.txt"
    with open(listing, "w", encoding="utf-8") as f:
        for p in pieces:
            f.write("file '{}'\n".format(os.path.abspath(p.path).replace("'", r"'\''")))
    media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out])
    os.remove(listing)


# ---------- 자막 ----------

def timeline_words(pieces: list[Piece], transcripts) -> list[list[Word]]:
    """챕터별, 완성 영상 시간 기준 단어."""
    by_chapter: dict[int, list[Word]] = {}
    for p in pieces:
        for w in transcripts[p.clip].words:
            mid = (w.start + w.end) / 2
            if p.start <= mid <= p.end:
                a = p.offset + max(w.start, p.start) - p.start
                b = p.offset + min(w.end, p.end) - p.start
                by_chapter.setdefault(p.chapter, []).append(Word(a, min(b, p.offset + p.length),
                                                                 w.text))
    return [by_chapter[k] for k in sorted(by_chapter)]


def make_cues(pieces, transcripts, *, fix: bool, context: str, max_chars: int = 20,
              images: list[str] | None = None) -> list[Cue]:
    """챕터마다 AI로 자막을 다듬는다: 오타, 말한 사람(묻는 사람은 노란색), (고민) 같은 표정 자막,
    끼워 넣을 짤(images 중에서)."""
    cues: list[Cue] = []
    groups = timeline_words(pieces, transcripts)
    for n, words in enumerate(groups, 1):
        fixed = None
        if fix and words:
            print(f"\r  자막 다듬는 중 [{n}/{len(groups)}]", end="", flush=True)
            fixed = fix_cues(words, max_chars=max_chars, context=context, images=images)
        cues += fixed if fixed is not None else build_cues(
            words, max_chars=max_chars, max_duration=3.5, max_gap=0.6)
    if fix and groups:
        print()
    cues.sort(key=lambda c: c.start)
    for a, b in zip(cues, cues[1:]):
        a.end = min(a.end, b.start)
    return [c for c in cues if c.end - c.start > 0.05]


def chapter_starts(edl: Edl, pieces: list[Piece]) -> list[tuple[float, str]]:
    out, seen = [], set()
    for p in pieces:
        if p.chapter not in seen:
            seen.add(p.chapter)
            out.append((p.offset, edl.chapters[p.chapter].title))
    return out


def write_ass(path: str, cues: list[Cue], chapters: list[tuple[float, str]], total: float, *,
              font: str, commerce: bool, chapter_cards: bool) -> None:
    def style(name, size, align, ml, mr, mv, border, outline, back="&H80000000&"):
        return (f"Style: {name},{font},{size},&H00FFFFFF&,&H00FFFFFF&,&H00000000&,{back},"
                f"1,0,0,0,100,100,0,0,{border},{outline},0,{align},{ml},{mr},{mv},1")

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {SUB_W}", f"PlayResY: {SUB_H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style("Sub", 72, 2, 80, 80, 64, 1, 5),
        style("SubOther", 72, 2, 80, 80, 64, 1, 5).replace(
            "&H00FFFFFF&,&H00FFFFFF&", f"{_c(OTHER_COLOR)},&H00FFFFFF&", 1),
        style("Chapter", 52, 7, 72, 72, 64, 3, 18, "&H70000000&"),
        style("Ad", 34, 9, 56, 56, 44, 3, 12, "&H60000000&"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in cues:
        name = "SubOther" if c.who == "other" else "Sub"
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},{name},,0,0,0,,"
                     f"{_note(c, 72)}{_esc(c.text)}")
    if chapter_cards:
        for k, (t, title) in enumerate(chapters):
            if k == 0 or not title.strip():
                continue  # 첫 챕터(오프닝)는 영상이 바로 시작되게 제목을 띄우지 않는다
            end = min(t + 3.5, total)
            lines.append(f"Dialogue: 1,{_ts(t + 0.2)},{_ts(end)},Chapter,,0,0,0,,"
                         f"{{\\fad(300,300)}}{_esc(title)}")
    if commerce:  # 뒷광고 방지: 영상 시작과 끝에 유료광고 표시
        for a, b in [(0.0, min(10.0, total)), (max(total - 10.0, 0.0), total)]:
            lines.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Ad,,0,0,0,,유료광고 포함")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")


# ---------- 최종 영상 ----------

def _chapters_meta(path: str, chapters: list[tuple[float, str]], total: float) -> None:
    """mp4 안에 챕터를 넣는다 (플레이어에서 챕터 이동)."""
    rows = [";FFMETADATA1"]
    for k, (t, title) in enumerate(chapters):
        end = chapters[k + 1][0] if k + 1 < len(chapters) else total
        safe = title.replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
        rows += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}",
                 f"END={int(end * 1000)}", f"title={safe}"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")


def finish(body: str, out: str, *, ass: str | None, font_path: str | None, bgm: str | None,
           bgm_volume: float, chapters: list[tuple[float, str]], total: float,
           loudnorm: bool = True, voice_enhance: bool = False,
           inserts: list[tuple[str, float, float]] | None = None) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        inputs = ["-i", os.path.abspath(body)]
        parts = []
        # 짤·사진: 자막 바로 위 가운데에 잠깐 (자막은 그 위에 그려진다)
        scale = H / SUB_H
        ins_in, ins_parts, cur = media.insert_graph(
            inserts or [], 1, "[0:v]", round(H - (64 + 72 * 1.5 + 20) * scale),
            max_w=round(W * 0.38), max_h=round(H * 0.36))
        inputs += ins_in
        parts += ins_parts
        parts.append(f"{cur}null[vbase]")
        n_in = 1 + len(inserts or [])
        if ass:
            shutil.copyfile(ass, os.path.join(work, "subs.ass"))
            fontsdir = ""
            if font_path:
                os.makedirs(os.path.join(work, "fonts"))
                shutil.copyfile(font_path, os.path.join(work, "fonts",
                                                        "f0" + os.path.splitext(font_path)[1]))
                fontsdir = ":fontsdir=fonts"
            parts.append(f"[vbase]subtitles=filename=subs.ass{fontsdir}[vout]")
        else:
            parts.append("[vbase]null[vout]")
        if voice_enhance:  # 캡컷 '음성 향상'처럼: 웅웅거림·잡음 줄이고 소리 크기 맞추기
            voice = f"[0:a]{media.voice_chain()}"
        else:
            voice = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000" if loudnorm else "[0:a]anull"
        if bgm:
            inputs += ["-stream_loop", "-1", "-i", os.path.abspath(bgm)]
            fade = max(total - 3.0, 0)
            parts.append(f"{voice},asplit[voice][key]")
            parts.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,"
                         f"volume={bgm_volume:.3f},atrim=0:{total:.3f},"
                         f"afade=t=in:d=1.5,afade=t=out:st={fade:.3f}:d=3[bg0]")
            parts.append("[bg0][key]sidechaincompress=threshold=0.03:ratio=6:attack=40:"
                         "release=700[bg]")
            parts.append("[voice][bg]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            parts.append(f"{voice}[aout]")
        meta = os.path.join(work, "chapters.txt")
        _chapters_meta(meta, chapters, total)
        meta_idx = n_in + (1 if bgm else 0)  # 0: 이어붙인 영상, 짤들, 배경음악(있으면)
        inputs += ["-f", "ffmetadata", "-i", meta]
        with open(os.path.join(work, "filter.txt"), "w", encoding="utf-8") as f:
            f.write(";\n".join(parts))
        tmp = os.path.abspath(out) + ".tmp.mp4"
        media.run_progress(total, ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
                   *media.filter_script_args("filter.txt"),
                   "-map", "[vout]", "-map", "[aout]", "-map_chapters", str(meta_idx),
                   "-c:v", "libx264", "-preset", FINAL_PRESET, "-crf", str(FINAL_CRF),
                   "-pix_fmt", "yuv420p", "-profile:v", "high", *media.COLOR_TAGS,
                   "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                   "-movflags", "+faststart", tmp], cwd=work)
        os.replace(tmp, out)


# ---------- 함께 만드는 파일 ----------

def youtube_chapters(chapters: list[tuple[float, str]], total: float) -> list[tuple[float, str]]:
    """유튜브 챕터 규칙: 0:00에서 시작, 챕터마다 10초 이상. 짧은 챕터는 다음 챕터에 합친다."""
    marks: list[tuple[float, str]] = []
    for t, title in chapters:
        if not marks:
            marks.append((0.0, title))
        elif t - marks[-1][0] < 10:
            marks[-1] = (marks[-1][0], title)  # 앞 챕터가 너무 짧으면 그 자리에서 이 챕터로
        else:
            marks.append((t, title))
    if len(marks) > 1 and total - marks[-1][0] < 10:
        marks.pop()  # 마지막 챕터가 너무 짧으면 앞 챕터에 합친다
    return marks


def youtube_text(edl: Edl, chapters: list[tuple[float, str]], total: float) -> str:
    """유튜브 업로드용 제목·설명 (챕터 시간 포함)."""
    marks = youtube_chapters(chapters, total)
    stamps = "\n".join(f"{_hms(t)} {title}" for t, title in marks)
    ad = "※ 이 영상은 유료광고를 포함하고 있습니다.\n\n" if edl.commerce else ""
    return (f"[제목]\n{edl.title}\n\n[설명]\n{ad}{edl.description}\n\n{stamps}\n\n"
            f"[썸네일 문구]\n{edl.thumbnail_text}\n")


def _pathurl(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p  # Windows: /C:/...
    return "file://localhost" + quote(p, safe="/:")


def premiere_xml(path: str, edl: Edl, pieces: list[Piece], chapters: list[tuple[float, str]],
                 durations: list[float]) -> None:
    """프리미어 프로·다빈치 리졸브에서 [파일 > 가져오기]로 여는 편집 타임라인 (FCP7 XML)."""
    rate = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
    total = round(sum(p.length for p in pieces) * FPS)
    defined: set[int] = set()

    def file_el(c: int) -> str:
        if c in defined:
            return f'<file id="file-{c + 1}"/>'
        defined.add(c)
        w, h = media.display_size(edl.clips[c])
        return (f'<file id="file-{c + 1}"><name>{escape(os.path.basename(edl.clips[c]))}</name>'
                f"<pathurl>{escape(_pathurl(edl.clips[c]))}</pathurl>{rate}"
                f"<duration>{round(durations[c] * FPS)}</duration>"
                f"<media><video><samplecharacteristics><width>{w}</width><height>{h}</height>"
                f"</samplecharacteristics></video><audio><channelcount>2</channelcount></audio>"
                f"</media></file>")

    video, audio = [], []
    for k, p in enumerate(pieces, 1):
        a = round(p.offset * FPS)
        b = a + round(p.length * FPS)
        i = round(p.start * FPS)
        o = i + (b - a)
        name = escape(os.path.basename(edl.clips[p.clip]))
        common = (f"<name>{name}</name><duration>{round(durations[p.clip] * FPS)}</duration>"
                  f"{rate}<start>{a}</start><end>{b}</end><in>{i}</in><out>{o}</out>")
        video.append(f'<clipitem id="v{k}">{common}{file_el(p.clip)}</clipitem>')
        audio.append(f'<clipitem id="a{k}">{common}<file id="file-{p.clip + 1}"/>'
                     f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex>"
                     f"</sourcetrack></clipitem>")
    markers = "".join(f"<marker><name>{escape(t)}</name><in>{round(s * FPS)}</in><out>-1</out>"
                      f"</marker>" for s, t in chapters)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
           f'<sequence id="sequence-1"><name>{escape(edl.title or "롱폼")}</name>'
           f"<duration>{total}</duration>{rate}{markers}"
           f"<media><video><format><samplecharacteristics>{rate}<width>{W}</width>"
           f"<height>{H}</height><pixelaspectratio>square</pixelaspectratio>"
           f"</samplecharacteristics></format><track>{''.join(video)}</track></video>"
           f"<audio><track>{''.join(audio)}</track></audio></media></sequence></xmeml>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def thumbnail(edl: Edl, out: str, font_path: str) -> None:
    """고른 장면 + 큰 글씨 썸네일 (1280x720)."""
    import tempfile

    from PIL import Image, ImageDraw, ImageFont

    src = edl.clips[edl.thumbnail_clip]
    with tempfile.TemporaryDirectory() as work:
        frame = os.path.join(work, "frame.png")
        graph = _norm_filter(*media.display_size(src), 1280, 720, pre=media.hdr_to_sdr(src))
        media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{edl.thumbnail_time:.2f}", "-i", src,
                   "-filter_complex", graph, "-map", "[v]", "-frames:v", "1", frame])
        img = Image.open(frame).convert("RGB")
    lines = [ln.strip() for ln in edl.thumbnail_text.split("\n") if ln.strip()][:3]
    if lines:
        draw = ImageDraw.Draw(img)
        size = 128 if max(len(ln) for ln in lines) <= 8 else 104
        while size > 50:
            font = ImageFont.truetype(font_path, size)
            if max(draw.textlength(ln, font=font) for ln in lines) <= 1280 - 120:
                break
            size -= 8
        font = ImageFont.truetype(font_path, size)
        y = 720 - 56 - len(lines) * (size + 16)
        for k, ln in enumerate(lines):
            color = (255, 226, 0) if k == len(lines) - 1 else (255, 255, 255)
            draw.text((60, y), ln, font=font, fill=color, stroke_width=max(6, size // 12),
                      stroke_fill=(0, 0, 0))
            y += size + 16
    img.save(out)


def _pick_bgm(folder: str | None) -> str | None:
    if not folder or not os.path.isdir(folder):
        return None
    files = sorted(os.path.join(folder, f) for f in os.listdir(folder)
                   if f.lower().endswith(AUDIO_EXT))
    return random.choice(files) if files else None


# ---------- 전체 ----------

def choose_format(clips: list[str], resolution: str = "auto") -> tuple[int, int, int]:
    """출력 가로·세로·프레임. 촬영본 대부분이 60fps면 60fps (30으로 줄이면 움직임이 뚝뚝 끊긴다).
    resolution: auto(1080p, 촬영본이 전부 4K 이상이고 4K로 하라고 했을 때만 4K) / 1080 / 2160"""
    total = fast = big = 0.0
    for c in clips:
        try:
            d = media.duration(c)
        except Exception:
            continue
        total += d
        if media.fps_value(c) > 45:
            fast += d
        w, h = media.display_size(c)
        if min(w, h) >= 2000:
            big += d
    fps = 60 if total and fast / total >= 0.5 else 30
    if resolution == "2160" and total and big / total >= 0.5:
        return 3840, 2160, fps
    return 1920, 1080, fps


def render(edl: Edl, transcripts, out_dir: str, work: str, args) -> str:
    global W, H, FPS
    W, H, FPS = choose_format(edl.clips, str(getattr(args, "resolution", "auto")))
    hdr = sum(1 for c in set(edl.clips) if media.is_hdr(c))
    print(f"\n[출력 규격] {W}x{H}, {FPS}fps" + (f" · HDR 촬영본 {hdr}개는 색을 일반 영상에 맞게 변환"
                                                if hdr else ""))
    print("\n[장면 자르기] 말 사이 긴 무음을 찾는 중..." if args.jumpcut else "\n[장면 자르기]")
    pieces = make_pieces(edl, transcripts, jumpcut=args.jumpcut, min_silence=args.min_silence,
                         fillers=getattr(args, "fillers", False))
    print(f"  {len(pieces)}개 조각")
    from . import progress
    print(f"\n[장면 인코딩] {W}x{H} 규격으로 맞추는 중 (저장해 두므로 멈춰도 이어서 해요)")
    progress.set_range(0.32, 0.8)
    encode_pieces(edl, pieces, work)
    total = sum(p.length for p in pieces)
    chapters = chapter_starts(edl, pieces)

    body = os.path.join(work, "이어붙인_영상.mp4")
    concat(pieces, body)

    font_path, found = fonts.find_or_fallback([args.font] if args.font else SUB_FONTS)
    if not found and args.font:
        print(f"  (글꼴 '{args.font}'을 못 찾아 기본 글꼴로 만들어요)")
    family = fonts.family(font_path)

    name = _safe(edl.title) if edl.title else "롱폼"
    ass = None
    srt = os.path.join(out_dir, f"{name}.srt")
    if args.subtitles:
        print("\n[자막]")
        from . import inserts as _inserts
        pics = _inserts.files() if getattr(args, "inserts", False) else {}
        cues = make_cues(pieces, transcripts, fix=args.fix_subtitles, context=args.context or "",
                         images=list(pics) or None)
        cut_ins = _inserts.timeline(cues, pics, limit=max(8, int(total // 40)))
        if cut_ins:
            print(f"  짤 {len(cut_ins)}개 끼워 넣기")
        others = sum(c.who == "other" for c in cues)
        if others:
            print(f"  묻는 사람 자막 {others}줄은 노란색으로")
        write_srt(cues, srt)
    else:
        cues, cut_ins = [], []
    ass = os.path.join(work, "subs.ass")
    write_ass(ass, cues, chapters, total, font=family, commerce=edl.commerce,
              chapter_cards=args.chapter_titles)

    progress.set_range(0.85, 1.0)
    bgm = None
    if getattr(args, "bgm_source", "auto") == "auto":
        from . import music
        mood = edl.bgm_mood or music.mood_for(getattr(args, "guide", "vlog") or "vlog")
        bgm = music.make(os.path.join(work, f"배경음악_{mood}.wav"), mood, min(total, 150),
                         edl.title or "롱폼")
        print(f"  배경음악: 직접 만든 곡 ({music.MOOD_NAMES.get(mood, mood)}, 저작권 걱정 없음)")
    elif getattr(args, "bgm_source", "auto") == "folder":
        bgm = _pick_bgm(args.bgm)
    print(f"\n[최종 영상] 자막과 챕터 제목을 입히{'고 배경음악을 까' if bgm else ''}는 중... "
          f"(영상 {_hms(total)}, 몇 분~수십 분 걸려요)")
    out = os.path.join(out_dir, f"{name}.mp4")
    finish(body, out, ass=ass, font_path=font_path, bgm=bgm, bgm_volume=args.bgm_volume,
           chapters=chapters, total=total, inserts=cut_ins,
           voice_enhance=getattr(args, "voice_enhance", False))
    os.remove(body)

    durations = [media.duration(c) for c in edl.clips]
    with open(os.path.join(out_dir, "유튜브_업로드.txt"), "w", encoding="utf-8") as f:
        f.write(youtube_text(edl, chapters, total))
    premiere_xml(os.path.join(out_dir, f"{name}_프리미어.xml"), edl, pieces, chapters, durations)
    if args.thumbnail:
        try:
            thumbnail(edl, os.path.join(out_dir, f"{name}_썸네일.png"), font_path)
        except Exception as e:  # 썸네일이 실패해도 영상은 완성
            print(f"  (썸네일 건너뜀: {type(e).__name__}: {e})")

    print(f"\n완성: {out}  ({_hms(total)})")
    print("  함께 만든 파일: 자막(.srt), 유튜브_업로드.txt(제목·설명·챕터), "
          "썸네일(.png), 프리미어 편집 파일(.xml)")
    return out
