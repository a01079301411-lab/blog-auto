"""명령줄 진입점: python -m shortform <명령> ..."""
from __future__ import annotations

import argparse
import hashlib
import glob
import json
import os
import re
import sys
from dataclasses import asdict

from . import media
from . import burnin, face, guides, review
from .highlights import Highlight, parse_ranges, pick_highlights
from .silence import detect_silences, drop_fillers, keep_segments
from .styles import (PRESETS, account_box_style, add_retention, dump_style, load_style,
                     video_filter, view_ratio, write_account_subs, write_ass)
from .subfix import fix_cues
from .subtitles import build_cues, remap, words_in_range, write_srt
from .transcribe import transcribe


def _hms(t: float) -> str:
    t = round(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def _cut_ranges(args, path: str, start: float, end: float) -> list[media.Segment]:
    if args.no_silence_cut:
        return [(start, end)]
    silences = detect_silences(path, noise_db=args.noise, min_silence=args.min_silence,
                               start=start, end=end)
    return keep_segments(silences, start, end, padding=args.padding)


def _get_transcript(args, path: str, workdir: str):
    name = os.path.splitext(os.path.basename(path))[0]
    cache = os.path.join(workdir, f"{name}.{args.model}.transcript.json")
    print("[음성 인식]")
    return transcribe(path, model=args.model, language=args.language or None, cache=cache,
                      device=args.device)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


def _audio_files(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in glob.glob(os.path.join(folder, "*"))
                  if f.lower().endswith(AUDIO_EXT))


def _to_output_time(t: float, keeps: list[media.Segment]) -> float | None:
    """원본 시간 → 무음을 잘라낸 숏폼 시간. 잘려나간 곳이면 None."""
    offset = 0.0
    for s, e in keeps:
        if s <= t <= e:
            return offset + t - s
        offset += e - s
    return None


def _add_retention(args, subs, h, keeps, kept, font, style) -> None:
    """훅 자막, 중간 한마디, 진행 막대를 자막 파일에 더한다 (설정에서 끌 수 있다)."""
    if not getattr(args, "retention", True):
        return
    rehook_at = _to_output_time(h.rehook_at, keeps) if h.rehook_at else None
    add_retention(subs, duration=kept, font=font, hook=h.hook, rehook=h.rehook,
                  rehook_at=rehook_at, video_top=style.video_top,
                  video_height=style.video_height)
    if h.hook:
        print(f"  훅 자막: {h.hook}" + (f" / 중간: {h.rehook}" if h.rehook else ""))


def _render_clip(args, src, start, end, out, transcript, style=None,
                 highlight: Highlight | None = None, acct=None) -> None:
    """style이 None이면 원본 비율 그대로, 있으면 세로 숏폼으로 만든다.

    acct(코시 계정)가 있으면 그 계정 가이드의 글꼴·색·배치로 만든다.
    """
    # 여러 장면을 이어 붙이는 숏폼이면 장면마다 무음을 자르고 보여 줄 순서대로 잇는다
    pieces = highlight.pieces() if highlight is not None else [(start, end)]
    keeps = [k for a, b in pieces for k in _cut_ranges(args, src, a, b)]
    if not keeps:
        raise RuntimeError("남길 구간이 없습니다. --noise 값을 낮춰 보세요 (예: -45).")
    if len(pieces) > 1:
        print(f"  장면 {len(pieces)}개 이어 붙이기: "
              + ", ".join(f"{_hms(a)}~{_hms(b)}" for a, b in pieces))
    if getattr(args, "fillers", False) and transcript is not None:
        before = len(keeps)
        keeps = drop_fillers(keeps, words_in_range(transcript.words, start, end))
        if len(keeps) > before:
            print(f"  군말(음·어) {len(keeps) - before}군데 잘라냄")
    kept = sum(e - s for s, e in keeps)
    span = sum(b - a for a, b in pieces)
    print(f"  {_hms(span)} → {_hms(kept)} (무음 {_hms(max(span - kept, 0))} 제거, "
          f"{len(keeps)}개 조각)")
    words = remap(words_in_range(transcript.words, start, end), keeps) if transcript else []

    if style is None:
        subs = None
        if transcript is not None:
            subs = os.path.splitext(out)[0] + ".srt"
            write_srt(build_cues(words, max_chars=args.max_chars), subs)
        media.render_long(src, keeps, out, srt=subs, font=args.font)
        print(f"  저장: {out}")
        return

    h = highlight or Highlight(start, end, "")
    speaker = args.speaker or h.speaker
    max_chars = args.max_chars
    if acct is not None:  # 계정 말자막 글자 크기에 맞춰 한 줄 길이를 정한다
        max_chars = min(max_chars, max(8, int(960 / acct.sub.size)))

    # 1) 원본 영상에 이미 자막이 박혀 있으면 새 자막은 넣지 않고 원본 자막을 살린다
    burned = None
    if args.burned_subs != "no":
        print("  원본 영상에 자막이 있는지 확인 중...")
        try:
            burned = burnin.detect(src, start, end)
        except Exception as e:  # 확인이 안 되면 새 자막을 넣는다
            print(f"  (원본 자막 확인 건너뜀: {type(e).__name__}: {e})")
        if burned:
            print("  원본 자막이 있어요 → 새 자막은 넣지 않고, 원본 자막이 잘리지 않게 화면을 잡아요")
    own_subs = burned is None and args.burned_subs != "yes"

    # 2) 자막: Claude로 오타 고치고 자연스럽게 끊기 (실패하면 기존 방식).
    #    말한 사람(묻는 사람은 노란색), (고민) 같은 표정 자막, 끼워 넣을 짤도 같이 고른다
    from . import inserts as _inserts
    pics = _inserts.files() if getattr(args, "inserts", False) else {}
    cues = []
    if own_subs and words:
        cues = None
        if args.fix_subtitles:
            print("  자막 다듬는 중 (오타 교정·말한 사람·표정 자막·짤 고르기)...")
            cues = fix_cues(words, max_chars=max_chars,
                            context=" ".join(filter(None, [args.context, speaker])),
                            images=list(pics) if pics else None)
        if cues is None:
            cues = build_cues(words, max_chars=max_chars)

    # 3) 화면 잡기: 원본 자막이 다 들어오게, 사람은 사람이 찍듯 자연스럽게 따라가기
    sw, sh = media.display_size(src)
    view = view_ratio(style, sw, sh)
    span = lo = hi = keep_bottom = None
    fill = style.video_fit == "fill"
    if burned and fill:
        need = min(burned.x1 - burned.x0 + 0.06, 1.0)
        keep_bottom = min(1.0, burned.y1 + 0.02)
        if need > view:  # 자막이 화면보다 넓으면 영상을 그만큼 넓게(작게) 보여준다
            span = view = need
        lo, hi = burned.x1 + 0.03 - view / 2, burned.x0 - 0.03 + view / 2
    samples, path = [], None
    if args.focus == "auto" and fill:
        print("  얼굴 위치 찾는 중...")
        try:
            for a, b in pieces:
                found = face.detect(src, a, b)
                if samples and found:  # 장면이 바뀌는 곳은 화면 이동 없이 바로 끊는다
                    found[0] = face.Sample(found[0].t, found[0].faces, True)
                samples += found
        except Exception as e:  # 얼굴 인식이 안 되면 가운데로
            print(f"  (얼굴 따라가기 건너뜀: {e})")
        mapped = [face.Sample(ot, s.faces, s.cut) for s in samples
                  if (ot := _to_output_time(s.t, keeps)) is not None]
        if any(s.faces for s in mapped):
            path = face.smooth_path(mapped, view, lo=lo, hi=hi)
    focus = 0.5 if args.focus == "auto" else float(args.focus)
    if path is None and burned and fill:
        mid = (burned.x0 + burned.x1) / 2
        path = [(0.0, min(max(mid, lo), hi) if lo <= hi else (lo + hi) / 2)]

    # 4) 배경음악: auto면 이 숏폼 분위기에 맞는 곡을 새로 만든다 (저작권 걱정 없는 자작곡)
    bgm = None
    if args.bgm_source == "auto":
        from . import music
        mood = music.mood_for(args.guide, h.bgm_mood)
        folder = os.path.join(args.output, "_배경음악")
        os.makedirs(folder, exist_ok=True)
        seed = f"{h.title}|{h.start:.1f}"
        name = hashlib.md5(seed.encode()).hexdigest()[:10]
        bgm = music.make(os.path.join(folder, f"{mood}_{name}.wav"), mood, kept + 2, seed)
        print(f"  배경음악: 직접 만든 곡 ({music.MOOD_NAMES[mood]})")
    elif args.bgm_source == "folder":
        tracks = _audio_files(args.bgm)
        if tracks:
            bgm = tracks[args.clip_index % len(tracks)]  # 숏폼마다 돌아가며 사용
            print(f"  배경음악: {os.path.basename(bgm)}")

    pick_from = cues
    if pics and not cues and words and args.fix_subtitles:  # 원본 자막을 쓸 때도 짤은 고른다
        print("  끼워 넣을 짤 고르는 중...")
        pick_from = fix_cues(words, max_chars=max_chars, context=args.context or "",
                             images=list(pics))
    cut_ins = _inserts.timeline(pick_from or [], pics)
    if cut_ins:
        print(f"  짤 {len(cut_ins)}개 끼워 넣기: "
              + ", ".join(os.path.basename(p) for p, _, _ in cut_ins))
    if cues and any(c.who == "other" for c in cues):
        print(f"  묻는 사람 자막 {sum(c.who == 'other' for c in cues)}줄은 노란색으로")

    color = ""
    if getattr(args, "auto_color", False):
        color = media.auto_color(src, start, end)
        print("  자동 색 보정: " + ("밝기·대비·채도를 조금 맞췄어요" if color else "손볼 게 없어요"))
    karaoke, pop = getattr(args, "karaoke", False), getattr(args, "sub_pop", False)

    subs = os.path.splitext(out)[0] + ".ass"
    vf = video_filter(style, focus, path=path, span=span, aspect=sw / sh if sh else 16 / 9,
                      keep_bottom=keep_bottom)
    if acct is None:
        write_ass(subs, style, cues, duration=kept, title=h.title, label=h.label,
                  speaker=speaker if (cues or burned is None) else "", bottom=h.bottom,
                  keywords=h.keywords, karaoke=karaoke, pop=pop)
        _add_retention(args, subs, h, keeps, kept, style.font, style)
        media.render(src, keeps, out, video_filter=vf, srt=subs,
                     bgm=bgm, bgm_volume=args.bgm_volume, inserts=cut_ins,
                     insert_bottom=style.sub_bottom - round(style.sub_size * 2.6),
                     voice_enhance=getattr(args, "voice_enhance", False), color=color)
    else:
        from . import draw, fonts

        boxed = style.video_height < 1920  # N-4 (롱폼 잘라 쓴 숏폼)
        ov_path = os.path.splitext(out)[0] + ".overlay.png"
        # 말자막을 데드존 바로 위로 내렸으니 설명자막도 그 바로 위. 원본 자막을 쓸 땐 원래 자리
        from .accounts import SPEAKER_Y, low_speaker_y
        draw.overlay(acct, title=h.title, sub_title=h.sub_title, speaker=speaker,
                     bottom=h.bottom, boxed=boxed,
                     speaker_y=low_speaker_y(acct) if cues else SPEAKER_Y).save(ov_path)
        sub_font, _ = fonts.find_or_fallback(acct.sub.fonts)
        write_account_subs(subs, acct, cues, font_path=sub_font, karaoke=karaoke, pop=pop)
        from . import fonts as _fonts
        _add_retention(args, subs, h, keeps, kept, _fonts.family(sub_font), style)
        try:
            media.render(src, keeps, out, video_filter=vf, srt=subs, overlay=ov_path,
                         font_files=[sub_font], bgm=bgm, bgm_volume=args.bgm_volume,
                         inserts=cut_ins, insert_bottom=low_speaker_y(acct) - 70,
                         voice_enhance=getattr(args, "voice_enhance", False), color=color)
        finally:
            os.remove(ov_path)
    print(f"  저장: {out}")

    # 4) 썸네일: 얼굴이 가장 크게 잡힌 장면 + 제목
    if args.thumbnail and acct is not None:
        _account_thumbnail(src, out, acct, h, samples, keeps, kept, focus,
                           frame_args=dict(span=span, aspect=sw / sh if sh else 16 / 9,
                                           keep_bottom=keep_bottom), center=path)
    elif args.thumbnail:
        t = face.best_frame_time(samples) or (keeps[0][0] + min(1.0, kept / 2))
        x = next((s.x for s in samples if s.t >= t and s.x is not None), None)
        thumb_ass = os.path.splitext(out)[0] + ".thumb.ass"
        write_ass(thumb_ass, style, [], duration=1, title=h.title, label=h.label)
        tvf = video_filter(style, focus, path=[(0.0, x)] if x is not None else None)
        thumb = os.path.splitext(out)[0] + ".jpg"
        try:
            media.snapshot(src, t, thumb, video_filter=tvf, ass=thumb_ass)
            print(f"  썸네일: {thumb}")
        except RuntimeError as e:
            print(f"  (썸네일 만들기 실패: {e})")
        finally:
            os.remove(thumb_ass)


def _account_thumbnail(src, out, acct, h, samples, keeps, kept, focus, frame_args=None,
                       center=None) -> None:
    """계정 가이드의 썸네일(N-1)을 PNG 1080x1920으로 만든다."""
    from PIL import Image

    from . import draw

    t = face.best_frame_time(samples) or (keeps[0][0] + min(1.0, kept / 2))
    ot = _to_output_time(t, keeps)
    if center and ot is not None:  # 영상과 같은 화면 위치
        x = next((x for ct, x in reversed(center) if ct <= ot), center[0][1])
    else:
        x = next((s.x for s in samples if s.t >= t and s.x is not None), None)
    st = account_box_style(vertical=acct.thumb.layout != "box")
    tvf = video_filter(st, focus, path=[(0.0, x)] if x is not None else None,
                       **(frame_args or {}))
    frame = os.path.splitext(out)[0] + ".frame.png"
    thumb = os.path.splitext(out)[0] + "_썸네일.png"
    try:
        media.snapshot(src, t, frame, video_filter=tvf)
        with Image.open(frame) as im:
            draw.thumbnail(acct, im, title=h.title, sub_title=h.sub_title).save(thumb)
        print(f"  썸네일: {thumb}")
    except (RuntimeError, OSError) as e:
        print(f"  (썸네일 만들기 실패: {e})")
    finally:
        if os.path.exists(frame):
            os.remove(frame)


def cmd_silence(args) -> None:
    out = args.output or os.path.splitext(args.input)[0] + "_cut.mp4"
    print("[무음 구간 제거] 무음 구간 찾는 중... (긴 영상은 몇 분 걸려요)")
    _render_clip(args, args.input, 0.0, media.duration(args.input), out, None)


def cmd_subtitle(args) -> None:
    base = os.path.splitext(args.input)[0]
    transcript = _get_transcript(args, args.input, os.path.dirname(os.path.abspath(args.input)))
    srt = args.output or base + ".srt"
    write_srt(build_cues(transcript.words, max_chars=args.max_chars), srt)
    print(f"  자막 저장: {srt}")
    if args.burn:
        print("[자막 입히기]")
        media.render(args.input, [(0.0, media.duration(args.input))], args.burn,
                     srt=srt, font=args.font)
        print(f"  저장: {args.burn}")


def _safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")[:40] or "clip"


def _load_picks(path: str, count) -> list[Highlight] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    if data.get("count") != count:
        return None  # 개수 설정이 바뀌었으면 새로 고른다
    picks = [Highlight(**h) for h in data["highlights"]]
    return picks or None  # 지난번에 못 찾았으면 다시 찾는다


def _save_picks(path: str, count, highlights: list[Highlight]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": count, "highlights": [asdict(h) for h in highlights]},
                  f, ensure_ascii=False, indent=1)


def _frames_for_ai(args, total: float, transcript) -> list[tuple[float, str]] | None:
    """말이 적은 영상(운동·액션)이거나 가이드가 원하면 장면 사진을 뽑아 AI에게 보여 준다."""
    import base64
    import tempfile

    g = guides.get(args.guide)
    words = len(transcript.words) if transcript else 0
    sparse = total > 0 and words / (total / 60) < 40  # 1분에 40단어도 안 되면 말이 적은 영상
    if not (g.get("frames") or sparse) or total <= 0:
        return None
    count = int(min(90, max(12, total / 4)))
    print(f"[장면 보기] 말보다 화면이 중요한 영상이라 장면 {count}장을 AI에게 보여 줘요...")
    shots = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(count):
            t = total * (k + 0.5) / count
            out = os.path.join(tmp, f"f{k}.jpg")
            try:
                media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                           "-i", args.input, "-frames:v", "1",
                           "-vf", f"{media.hdr_to_sdr(args.input)}scale=320:-2", "-q:v", "7", out])
                with open(out, "rb") as f:
                    shots.append((t, base64.b64encode(f.read()).decode()))
            except (RuntimeError, OSError):
                continue
    return shots or None


def _guide_text(args) -> str:
    """영상 종류 가이드 + 지난 숏폼 성과 (있으면)."""
    text = guides.brief(args.guide)
    if getattr(args, "lessons", ""):
        text += "\n\n" + args.lessons
    return text


def _pick_for_accounts(args, transcript, accts) -> list[Highlight]:
    """계정마다 그 컨셉에 맞는 구간을 고른다. 계정끼리 같은 구간은 쓰지 않는다."""
    from .accounts import ACCOUNTS

    picked: list[Highlight] = []
    for n in accts:
        acct = ACCOUNTS[n]
        print(f"[하이라이트 선정] {acct.no}번 {acct.name} ({acct.handle}) 컨셉에 맞는 구간 찾는 중...")
        hs = pick_highlights(transcript.sentences, count=args.per_account,
                             min_len=args.min_len, max_len=args.max_len,
                             context=args.context or "", account=acct,
                             exclude=[(h.start, h.end) for h in picked],
                             words=transcript.words, ref_blocks=args.ref_blocks,
                             guide=_guide_text(args), frames=getattr(args, "frames", None),
                             check=guides.get(args.guide).get("check", True))
        for h in hs:
            h.account = acct.no
        print(f"  {len(hs)}개")
        picked += hs
    return picked


def cmd_shorts(args) -> None:
    from .accounts import ACCOUNTS
    from .accounts import parse as parse_accounts

    accts = parse_accounts(args.accounts or "")
    if guides.get(args.guide).get("silence_cut") is False:
        args.no_silence_cut = True  # 운동처럼 숨소리·동작 소리만 있는 영상은 무음으로 자르지 않는다
    style = load_style(args.style, font=args.font)
    os.makedirs(args.output, exist_ok=True)
    total = media.duration(args.input)
    if total < args.min_len:  # 영상이 숏폼 최소 길이보다 짧으면 영상 길이에 맞춘다
        print(f"[길이] 영상이 {_hms(total)}라 숏폼 길이 {args.min_len:g}~{args.max_len:g}초를 "
              f"만들 수 없어서, 이 영상은 {max(5.0, total * 0.6):.0f}~{total:.0f}초로 맞춰요.")
        args.min_len, args.max_len = max(5.0, total * 0.6), max(total, 6.0)
    vertical = media.is_vertical(args.input)
    from . import performance, progress

    need_transcript = not args.no_subtitles or not args.ranges
    progress.set_range(0.0, 0.4)
    transcript = _get_transcript(args, args.input, args.output) if need_transcript else None
    progress.set_range(0.4, 0.5)

    picks_path = os.path.join(args.output, "highlights.json")
    # 고르는 방식이 바뀌면 앞의 v2를 올려서 예전에 고른 결과를 다시 쓰지 않게 한다
    key = (f"v6:accounts:{','.join(map(str, accts))}:{args.per_account}" if accts
           else f"v6:{args.count}")
    key += f":len:{args.min_len:g}-{args.max_len:g}"
    if args.context:  # 영상 설명(지시)이 바뀌면 다시 고른다
        key += ":ctx:" + hashlib.md5(args.context.encode()).hexdigest()[:8]
    if args.guide != "lecture":  # 영상 종류가 바뀌면 다시 고른다
        key += f":guide:{args.guide}"
    if args.ref:  # 레퍼런스가 바뀌면 다시 고른다
        key += ":ref:" + hashlib.md5("|".join(args.ref).encode()).hexdigest()[:8]
    args.ref_blocks = None
    if args.ranges:
        highlights = parse_ranges(args.ranges)
        for h in highlights:
            h.account = accts[0] if accts else 0
            acct = ACCOUNTS.get(h.account)
            lines = h.title.split("\n")
            if acct and (acct.video.sub_title or acct.thumb.pill) and len(lines) > 1:
                h.sub_title, h.title = lines[0], "\n".join(lines[1:])  # 첫 줄은 부제목
    elif (highlights := _load_picks(picks_path, key)) is not None:
        print(f"[하이라이트] 지난번에 고른 {len(highlights)}개를 다시 써요. "
              f"(새로 고르려면 결과 폴더의 highlights.json을 지우세요)")
    else:
        if args.ref:
            from . import references
            print("[레퍼런스] 참고 자료 읽는 중...")
            args.ref_blocks = references.blocks(args.ref)
        # 성과 학습: 지난 숏폼 중 잘된 것·안된 것을 알려 주고 그 공통점을 반영하게 한다
        if performance.fetch_youtube():
            print("[성과 학습] 유튜브에서 지난 숏폼 조회수를 가져왔어요.")
        args.lessons = performance.lessons(args.guide)
        if args.lessons:
            print("[성과 학습] 지난 숏폼 성과를 반영해서 골라요.")
        args.frames = _frames_for_ai(args, total, transcript)
        if accts:
            highlights = _pick_for_accounts(args, transcript, accts)
        else:
            print("[하이라이트 선정] Claude가 대본을 분석하는 중...")
            highlights = pick_highlights(transcript.sentences, count=args.count,
                                         min_len=args.min_len, max_len=args.max_len,
                                         context=args.context or "", words=transcript.words,
                                         ref_blocks=args.ref_blocks, frames=args.frames,
                                         check=guides.get(args.guide).get("check", True),
                                         guide=_guide_text(args))
        if not highlights and transcript is not None and not accts:
            # 그래도 하나도 못 고르면 빈손으로 끝내지 않는다: 영상 앞부분을 숏폼 하나로
            end = min(total, args.max_len)
            print(f"  고를 만한 구간을 못 찾아서, 영상 처음 {_hms(end)}를 숏폼 1개로 만들어요.")
            highlights = [Highlight(0.0, end, "")]
        if highlights and highlights[0].title:
            _save_picks(picks_path, key, highlights)
    if not highlights:
        sys.exit("하이라이트를 찾지 못했어요. 길이(초) 범위를 넓히거나(예: 15~60) "
                 "[고급 설정]의 영상 설명을 적어 주면 찾기 쉬워져요.")

    numbered = list(enumerate(highlights, 1))
    if args.review:
        chosen = review.review(os.path.join(args.output, "숏폼_고르기.txt"), highlights)
        _save_picks(picks_path, key, highlights)  # 고친 제목·구간도 저장
        numbered = [(i, h) for i, h in numbered if h in chosen]
        if not numbered:
            sys.exit("고른 숏폼이 없어요.")

    made = []
    per_folder: dict[str, int] = {}
    if accts:
        kind = "세로 촬영본(N-3)" if vertical else "롱폼 잘라 쓴 숏폼(N-4)"
        print(f"\n[제작 방식] {kind} 가이드로 만들어요.")
    for n, (i, h) in enumerate(numbered, 1):
        h.start, h.end = max(0.0, h.start), min(total, h.end)
        acct = ACCOUNTS.get(h.account) if h.account else None
        name = h.title.replace("\n", " ").replace("{", "").replace("}", "") or f"clip{i}"
        score = f"  점수 {h.score}/10" if h.score else ""
        where = f" → {acct.no}번 {acct.name}" if acct else ""
        print(f"\n[{n}/{len(numbered)}] {name}  ({_hms(h.start)} ~ {_hms(h.end)}){score}{where}")
        if h.reason:
            print(f"  이유: {h.reason}")
        folder = os.path.join(args.output, acct.folder) if acct else args.output
        os.makedirs(folder, exist_ok=True)
        per_folder[folder] = per_folder.get(folder, 0) + 1
        num = per_folder[folder] if acct else i
        out = os.path.join(folder, f"{num:02}_{_safe_name(name)}.mp4")
        args.clip_index = i - 1
        clip_style = account_box_style(vertical) if acct else style
        progress.set_range(0.5 + 0.5 * (n - 1) / len(numbered), 0.5 + 0.5 * n / len(numbered))
        progress.report(0.1, f"숏폼 {n}/{len(numbered)}")
        _render_clip(args, args.input, h.start, h.end, out,
                     None if args.no_subtitles else transcript, clip_style, h, acct=acct)
        if h.caption or h.title:
            with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as f:
                head = f"[계정] {acct.no}번 {acct.name} ({acct.handle})\n\n" if acct else ""
                f.write(f"{head}[제목]\n{h.title}\n\n[부제목] {h.sub_title}\n"
                        f"[알약 문구] {h.label}\n[설명자막] {h.speaker}\n"
                        f"[하단자막] {h.bottom}\n\n[업로드 설명]\n{h.caption}\n\n"
                        f"[원본 구간] {_hms(h.start)} ~ {_hms(h.end)}\n"
                        f"[선정 이유] {h.reason}\n")
        made.append((out, h))
        from . import music
        performance.record(os.path.abspath(out), title=h.title, hook=h.hook,
                           seconds=h.length(), guide=args.guide,
                           account=f"{acct.no}. {acct.name}" if acct else "",
                           mood=music.mood_for(args.guide, h.bgm_mood))
        progress.report(1.0, f"숏폼 {n}/{len(numbered)}")

    if args.upload != "no":
        _upload_all(args.output, made, args.upload)


def _upload_all(folder: str, made: list[tuple[str, Highlight]], privacy: str) -> None:
    from . import youtube

    log_path = os.path.join(folder, "uploaded.json")
    try:
        with open(log_path, encoding="utf-8") as f:
            done = json.load(f)
    except (FileNotFoundError, ValueError):
        done = {}
    print(f"\n[유튜브 업로드] {len(made)}개 ({privacy})")
    for out, h in made:
        key = os.path.basename(out)
        if key in done:
            print(f"  이미 올림: {key} → {done[key]}")
            continue
        print(f"  {key}")
        try:
            url = youtube.upload(out, title=h.title or key, description=h.caption,
                                 privacy=privacy, thumbnail=os.path.splitext(out)[0] + ".jpg")
        except Exception as e:
            msg = str(e)
            if "quotaExceeded" in msg or "uploadLimitExceeded" in msg:
                print("  오늘 업로드 한도를 다 썼어요. 내일 같은 영상을 다시 끌어다 놓으면 "
                      "남은 것만 올려요.")
                break
            raise RuntimeError(f"유튜브 업로드 실패: {e}") from e
        done[key] = url
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(done, f, ensure_ascii=False, indent=1)
        print(f"  → {url}")


SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "settings.ini")


def cmd_auto(args) -> None:
    """settings.ini를 읽어 shorts를 실행한다 (run.bat 끌어다 놓기·프로그램 창용)."""
    from . import settings
    from .update import tidy_settings

    from . import __version__
    print(f"[시작] 숏폼 준비 중... (v{__version__})", flush=True)
    if os.path.abspath(args.settings) == os.path.abspath(SETTINGS):
        tidy_settings()  # 예전 업데이트가 흐트러뜨린 설정 파일 모양 정리
    video = args.inputs[0]
    out = settings.output_dir(video)
    if len(args.inputs) > 1:
        # 여러 영상을 하나로 합쳐서, 영상마다가 아니라 전체에서 숏폼 개수만큼만 만든다
        out = os.path.join(os.path.dirname(os.path.abspath(video)), "숏폼_영상합침")
        os.makedirs(out, exist_ok=True)
        video = os.path.join(out, "_합친영상.mp4")
        print(f"[영상 합치기] 영상 {len(args.inputs)}개를 하나로 이어 붙이는 중 "
              "(전체에서 고르려고요. 한 번 합치면 다시 쓰지 않아요)...", flush=True)
        from . import progress
        progress.set_range(0.0, 0.1)
        spans = media.merge_videos(args.inputs, video)
        for k, (p, a, b) in enumerate(spans, 1):
            print(f"  영상{k} {os.path.basename(p)}: 합친 영상 {_hms(a)} ~ {_hms(b)}")
    argv = settings.to_argv(video, settings.load(args.settings), out)
    for r in args.ref:
        argv += ["--ref", r]
    shorts_args = build_parser().parse_args(argv)
    shorts_args.func(shorts_args)

    print(f"\n완료! 결과 폴더: {out}")
    if hasattr(os, "startfile") and not os.environ.get("SHORTFORM_GUI"):
        os.startfile(out)  # Windows: 결과 폴더 열기 (프로그램 창에서는 창이 대신 연다)


def cmd_long(args) -> None:
    from . import longform

    out = longform.run(args)
    print(f"\n완료! 결과 폴더: {out}")
    if hasattr(os, "startfile") and not os.environ.get("SHORTFORM_GUI"):
        os.startfile(out)


def cmd_longauto(args) -> None:
    """settings.ini의 [longform] 설정으로 long을 실행한다 (프로그램 창·run_long.bat용)."""
    from . import settings

    from . import __version__
    print(f"[시작] 롱폼 준비 중... (v{__version__})", flush=True)
    c = settings.load_long(args.settings)
    argv = settings.long_argv(args.inputs, c, plan=args.plan, output=args.output,
                              title=args.title, replan=args.replan)
    for r in args.ref:
        argv += ["--ref", r]
    long_args = build_parser().parse_args(argv)
    long_args.func(long_args)


def cmd_style(args) -> None:
    print(dump_style(load_style(args.name)))


def _yesno(v: str) -> bool:
    v = str(v).strip().lower()
    if v in ("yes", "y", "true", "1", "on", "예", "네", "o"):
        return True
    if v in ("no", "n", "false", "0", "off", "아니오", "아니요", "x"):
        return False
    raise argparse.ArgumentTypeError(f"yes 또는 no로 적어 주세요: {v}")


def _focus(v: str) -> str | float:
    if str(v).strip().lower() == "auto":
        return "auto"
    try:
        return min(max(float(v), 0.0), 1.0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"auto 또는 0~1 숫자로 적어 주세요: {v}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("무음 제거")
    g.add_argument("--noise", type=float, default=-35.0,
                   help="이 값(dB)보다 조용하면 무음으로 판단 (기본 -35)")
    g.add_argument("--min-silence", type=float, default=0.5,
                   help="이 길이(초) 이상 이어지는 무음만 자름 (기본 0.5)")
    g.add_argument("--padding", type=float, default=0.15,
                   help="자른 곳 앞뒤로 남길 여유(초) (기본 0.15)")
    g.add_argument("--no-silence-cut", action="store_true", help="무음 제거 안 함")
    g = common.add_argument_group("자막")
    g.add_argument("--model", default="small",
                   help="Whisper 모델: tiny/base/small/medium/large-v3 (기본 small)")
    g.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto",
                   help="음성 인식에 쓸 장치 (기본 auto: GPU가 되면 GPU)")
    g.add_argument("--language", default="ko", help="음성 언어 (기본 ko, 빈 값이면 자동 감지)")
    g.add_argument("--font", help="글꼴 이름 (기본: 맑은 고딕. 예: 'Gmarket Sans TTF Bold')")
    g.add_argument("--max-chars", type=int, default=14, help="자막 한 덩어리 최대 글자 수")

    p = argparse.ArgumentParser(prog="python -m shortform",
                                description="롱폼 영상 → 숏폼 하이라이트 자동 편집기")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("shorts", parents=[common],
                       help="하이라이트를 골라 자막 달린 세로 숏폼 여러 개 만들기")
    s.add_argument("input")
    s.add_argument("-o", "--output", default="shorts_out", help="출력 폴더")
    s.add_argument("-n", "--count", type=int, default=3, help="만들 숏폼 개수")
    s.add_argument("--min-len", type=float, default=20, help="클립 최소 길이(초)")
    s.add_argument("--max-len", type=float, default=60, help="클립 최대 길이(초)")
    s.add_argument("--context",
                   help="영상 설명 (누가, 무슨 내용인지). 하이라이트·제목 품질이 좋아져요")
    s.add_argument("--ranges",
                   help="AI 대신 직접 구간 지정. 예: '1:00-1:45=망하는 사장들의/공통점,5:00-5:40'")
    s.add_argument("--accounts", default="",
                   help="코시 계정 번호 (예: '1,4'). 계정마다 그 가이드대로 만들어 폴더별로 저장")
    s.add_argument("--per-account", type=int, default=3, help="계정당 만들 숏폼 개수 (기본 3)")
    s.add_argument("--style", default="green",
                   help="디자인: " + ", ".join(PRESETS) + " 또는 JSON 파일 (기본 green)")
    s.add_argument("--speaker", help="인물 소개 문구 직접 지정. 예: '권기준 / 꼴통사장 대표'")
    s.add_argument("--focus", type=_focus, default="auto",
                   help="auto: 얼굴 따라가기 (기본) / 0~1: 고정 위치 (0.3이면 왼쪽)")
    s.add_argument("--no-subtitles", action="store_true", help="자막 안 넣음")
    s.add_argument("--fix-subtitles", type=_yesno, default=True,
                   help="Claude로 자막 오타 교정·줄 나누기 yes/no (기본 yes)")
    s.add_argument("--review", type=_yesno, default=False,
                   help="만들기 전에 메모장으로 목록을 보고 고르기 yes/no")
    s.add_argument("--ref", action="append", default=[],
                   help="레퍼런스: 링크, 사진·영상 파일, 또는 설명 글 (여러 번 쓸 수 있어요)")
    s.add_argument("--guide", default="lecture",
                   help="영상 종류: lecture(강의·인터뷰) / vlog(브이로그) / moving(이사 현장) / "
                        "commerce(제품 광고) / custom")
    s.add_argument("--burned-subs", choices=["auto", "yes", "no"], default="auto",
                   help="원본에 박힌 자막: auto(찾으면 새 자막 대신 원본 자막 사용) / yes / no")
    s.add_argument("--bgm", help="배경음악 폴더 (mp3/wav를 숏폼마다 돌아가며 사용)")
    s.add_argument("--bgm-source", choices=["auto", "folder", "none"], default="auto",
                   help="배경음악: auto(분위기에 맞게 직접 만든 곡) / folder(bgm 폴더) / none")
    s.add_argument("--retention", type=_yesno, default=True,
                   help="훅 자막, 중간 한마디, 진행 막대 넣기 yes/no")
    s.add_argument("--bgm-volume", type=float, default=0.15, help="배경음악 볼륨 0~1")
    s.add_argument("--fillers", type=_yesno, default=True,
                   help="'음', '어' 같은 군말 잘라내기 yes/no (기본 yes)")
    s.add_argument("--voice-enhance", type=_yesno, default=True,
                   help="목소리 또렷하게: 잡음 줄이고 소리 크기 맞추기 yes/no (기본 yes)")
    s.add_argument("--inserts", type=_yesno, default=True,
                   help="'짤' 폴더의 사진·짧은 영상을 자막에 맞춰 끼워 넣기 yes/no (기본 yes)")
    s.add_argument("--karaoke", type=_yesno, default=False,
                   help="캡컷 자동 자막처럼 지금 말하는 단어에 색 채우기 yes/no (기본 no)")
    s.add_argument("--sub-pop", type=_yesno, default=True,
                   help="자막이 나올 때 살짝 튀어나오기 yes/no (기본 yes)")
    s.add_argument("--auto-color", type=_yesno, default=True,
                   help="자동 색 보정: 어두우면 밝게, 흐리면 선명하게 yes/no (기본 yes)")
    s.add_argument("--thumbnail", type=_yesno, default=True, help="썸네일 이미지 만들기 yes/no")
    s.add_argument("--upload", choices=["no", "private", "unlisted", "public"], default="no",
                   help="유튜브 업로드: no / private(비공개) / unlisted(일부 공개) / public")
    s.set_defaults(func=cmd_shorts)

    s = sub.add_parser("silence", parents=[common], help="영상 전체의 무음 구간 잘라내기")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_silence)

    s = sub.add_parser("subtitle", parents=[common], help="자동 자막(SRT) 만들기")
    s.add_argument("input")
    s.add_argument("-o", "--output", help="SRT 저장 경로")
    s.add_argument("--burn", metavar="OUT.mp4", help="자막을 영상에 입혀서 저장")
    s.set_defaults(func=cmd_subtitle)
    s = sub.add_parser("auto", help="settings.ini 설정으로 숏폼 만들기 (run.bat이 사용)")
    s.add_argument("inputs", nargs="+",
                   help="영상. 여러 개면 하나로 합쳐서 전체에서 숏폼 개수만큼만 만든다")
    s.add_argument("--ref", action="append", default=[], help="레퍼런스 (링크·파일·설명)")
    s.add_argument("--settings", default=SETTINGS)
    s.set_defaults(func=cmd_auto)

    s = sub.add_parser("long", help="여러 촬영본 + 기획안 → 롱폼 편집 (자막·챕터·썸네일)")
    s.add_argument("inputs", nargs="+", help="촬영본 영상 파일 또는 폴더 (여러 개)")
    s.add_argument("-o", "--output", help="결과 폴더 (기본: 첫 촬영본 옆 '롱폼_결과')")
    s.add_argument("--plan", help="기획안 파일(txt/md/docx/hwp) 또는 기획 내용 글")
    s.add_argument("--ref", action="append", default=[],
                   help="레퍼런스: 링크, 사진·영상 파일, 또는 설명 글 (여러 번 쓸 수 있어요)")
    s.add_argument("--context", help="채널 설명 (세계관, 출연자). 편집·제목 품질이 좋아져요")
    s.add_argument("--minutes", type=float, default=0, help="목표 길이(분). 0이면 AI가 판단")
    s.add_argument("--commerce", type=_yesno, default=False,
                   help="유료광고 포함 영상 yes/no (시작·끝에 '유료광고 포함' 표시)")
    s.add_argument("--review", type=_yesno, default=False, help="만들기 전에 순서표 검토 yes/no")
    s.add_argument("--replan", action="store_true", help="지난 순서표를 버리고 새로 짜기")
    s.add_argument("--frames", type=_yesno, default=True,
                   help="촬영본 장면 사진도 AI에게 보여주기 yes/no (말 없는 장면 판단)")
    s.add_argument("--jumpcut", type=_yesno, default=True,
                   help="말 사이 긴 무음 잘라내기 yes/no (풍경 장면은 그대로)")
    s.add_argument("--subtitles", type=_yesno, default=True, help="자막 넣기 yes/no")
    s.add_argument("--fix-subtitles", type=_yesno, default=True,
                   help="Claude로 자막 오타 교정 yes/no")
    s.add_argument("--chapter-titles", type=_yesno, default=True,
                   help="챕터가 바뀔 때 화면에 챕터 제목 띄우기 yes/no")
    s.add_argument("--bgm", help="배경음악 폴더 (하나를 골라 깔고, 말할 때 자동으로 줄여요)")
    s.add_argument("--bgm-volume", type=float, default=0.10, help="배경음악 볼륨 0~1")
    s.add_argument("--thumbnail", type=_yesno, default=True, help="썸네일 만들기 yes/no")
    s.add_argument("--allow-fallback", action="store_true",
                   help="Claude를 못 쓰면 촬영 순서대로 이어 붙이기")
    s.add_argument("--model", default="small", help="Whisper 모델 (기본 small)")
    s.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    s.add_argument("--language", default="ko")
    s.add_argument("--font", help="자막 글꼴 이름")
    s.add_argument("--min-silence", type=float, default=1.0,
                   help="이 길이(초) 이상 말이 끊기면 잘라냄 (기본 1.0)")
    s.add_argument("--bgm-source", choices=["auto", "folder", "none"], default="auto",
                   help="배경음악: auto(분위기에 맞게 직접 만든 곡) / folder(bgm 폴더) / none")
    s.add_argument("--fillers", type=_yesno, default=True, help="'음', '어' 군말 잘라내기 yes/no")
    s.add_argument("--voice-enhance", type=_yesno, default=True,
                   help="목소리 또렷하게 (잡음 줄이고 소리 크기 맞추기) yes/no")
    s.add_argument("--inserts", type=_yesno, default=True,
                   help="'짤' 폴더의 사진·짧은 영상을 자막에 맞춰 끼워 넣기 yes/no")
    s.add_argument("--auto-color", type=_yesno, default=True,
                   help="자동 색 보정: 어두우면 밝게, 흐리면 선명하게 yes/no")
    s.add_argument("--resolution", choices=["auto", "1080", "2160"], default="auto",
                   help="출력 해상도: auto/1080 = 1920x1080, 2160 = 촬영본이 4K면 4K (오래 걸려요)")
    s.set_defaults(func=cmd_long)

    s = sub.add_parser("longauto", help="settings.ini [longform] 설정으로 롱폼 만들기")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--plan")
    s.add_argument("-o", "--output")
    s.add_argument("--title", help="결과 폴더 이름")
    s.add_argument("--ref", action="append", default=[], help="레퍼런스 (링크·파일·설명)")
    s.add_argument("--replan", action="store_true")
    s.add_argument("--settings", default=SETTINGS)
    s.set_defaults(func=cmd_longauto)

    s = sub.add_parser("style", help="스타일 설정을 JSON으로 출력 (내 스타일 만들기용)")
    s.add_argument("name", nargs="?", default="green")
    s.set_defaults(func=cmd_style)
    return p


def main(argv: list[str] | None = None) -> None:
    import faulthandler
    import traceback

    try:
        faulthandler.enable()  # 프로그램이 갑자기 꺼져도 어디서 멈췄는지 남긴다
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as e:
        sys.exit(f"오류: {e}")
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다. 같은 명령을 다시 실행하면 끝난 부분부터 이어서 진행해요.")
    except Exception as e:  # 예상 못 한 오류도 내용이 보이게
        traceback.print_exc()
        sys.exit(f"\n오류: {type(e).__name__}: {e}\n(위 내용을 캡처해서 보내 주세요)")
