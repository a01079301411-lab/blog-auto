"""명령줄 진입점: python -m shortform <명령> ..."""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys
from dataclasses import asdict

from . import media
from . import face, review
from .highlights import Highlight, parse_ranges, pick_highlights
from .silence import detect_silences, keep_segments
from .styles import (PRESETS, account_box_style, dump_style, load_style, video_filter,
                     write_account_subs, write_ass)
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


def _zoom_times(cues, keywords: list[str], *, gap: float = 3.0, limit: int = 4) -> list[float]:
    """핵심 단어가 나오는 자막 시작 시간. 너무 자주 확대하지 않게 간격을 둔다."""
    kws = [k.replace(" ", "") for k in keywords if k.strip()]
    times: list[float] = []
    for c in cues:
        if any(k in c.text.replace(" ", "") for k in kws):
            if c.start >= 0.3 and (not times or c.start - times[-1] >= gap):
                times.append(c.start)
        if len(times) == limit:
            break
    return times


def _render_clip(args, src, start, end, out, transcript, style=None,
                 highlight: Highlight | None = None, acct=None) -> None:
    """style이 None이면 원본 비율 그대로, 있으면 세로 숏폼으로 만든다.

    acct(코시 계정)가 있으면 그 계정 가이드의 글꼴·색·배치로 만든다.
    """
    keeps = _cut_ranges(args, src, start, end)
    if not keeps:
        raise RuntimeError("남길 구간이 없습니다. --noise 값을 낮춰 보세요 (예: -45).")
    kept = sum(e - s for s, e in keeps)
    print(f"  {_hms(end - start)} → {_hms(kept)} (무음 {_hms(end - start - kept)} 제거, "
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

    # 1) 자막: Claude로 오타 고치고 자연스럽게 끊기 (실패하면 기존 방식)
    cues = None
    if words and args.fix_subtitles:
        print("  자막 다듬는 중 (오타 교정·줄 나누기)...")
        cues = fix_cues(words, max_chars=max_chars,
                        context=" ".join(filter(None, [args.context, speaker])))
    if cues is None:
        cues = build_cues(words, max_chars=max_chars)

    # 2) 얼굴 따라가기
    samples, path = [], None
    if args.focus == "auto" and style.video_fit == "fill":
        print("  얼굴 위치 찾는 중...")
        try:
            samples = face.detect(src, start, end)
        except Exception as e:  # 얼굴 인식이 안 되면 가운데로
            print(f"  (얼굴 따라가기 건너뜀: {e})")
        mapped = [(ot, x, size) for t, x, size in samples
                  if (ot := _to_output_time(t, keeps)) is not None]
        if any(x is not None for _, x, _ in mapped):
            path = face.smooth_path(mapped)
    focus = 0.5 if args.focus == "auto" else float(args.focus)

    # 3) 핵심 단어에서 확대 + 효과음
    zooms = _zoom_times(cues, h.keywords) if args.zoom else []
    sfx = None
    if zooms and args.sfx:
        mine = _audio_files(os.path.join(ROOT, "sfx"))
        sfx = random.choice(mine) if mine else os.path.join(ROOT, "shortform", "assets", "whoosh.wav")

    # 4) 배경음악
    bgm = None
    tracks = _audio_files(args.bgm)
    if tracks:
        bgm = tracks[args.clip_index % len(tracks)]  # 숏폼마다 돌아가며 사용
        print(f"  배경음악: {os.path.basename(bgm)}")

    subs = os.path.splitext(out)[0] + ".ass"
    vf = video_filter(style, focus, path=path, zooms=zooms, fps=media.frame_rate(src))
    if acct is None:
        write_ass(subs, style, cues, duration=kept, title=h.title, label=h.label,
                  speaker=speaker, bottom=h.bottom, keywords=h.keywords)
        media.render(src, keeps, out, video_filter=vf, srt=subs,
                     bgm=bgm, bgm_volume=args.bgm_volume, sfx=sfx, sfx_times=zooms)
    else:
        from . import draw, fonts

        boxed = style.video_height < 1920  # N-4 (롱폼 잘라 쓴 숏폼)
        ov_path = os.path.splitext(out)[0] + ".overlay.png"
        draw.overlay(acct, title=h.title, sub_title=h.sub_title, speaker=speaker,
                     bottom=h.bottom, boxed=boxed).save(ov_path)
        sub_font, _ = fonts.find_or_fallback(acct.sub.fonts)
        write_account_subs(subs, acct, cues, font_path=sub_font)
        try:
            media.render(src, keeps, out, video_filter=vf, srt=subs, overlay=ov_path,
                         font_files=[sub_font], bgm=bgm, bgm_volume=args.bgm_volume,
                         sfx=sfx, sfx_times=zooms)
        finally:
            os.remove(ov_path)
    print(f"  저장: {out}")

    # 5) 썸네일: 얼굴이 가장 크게 잡힌 장면 + 제목
    if args.thumbnail and acct is not None:
        _account_thumbnail(src, out, acct, h, samples, keeps, kept, focus)
    elif args.thumbnail:
        t = face.best_frame_time(samples) or (keeps[0][0] + min(1.0, kept / 2))
        x = next((x for st, x, _ in samples if st >= t and x is not None), None)
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


def _account_thumbnail(src, out, acct, h, samples, keeps, kept, focus) -> None:
    """계정 가이드의 썸네일(N-1)을 PNG 1080x1920으로 만든다."""
    from PIL import Image

    from . import draw

    t = face.best_frame_time(samples) or (keeps[0][0] + min(1.0, kept / 2))
    x = next((x for st, x, _ in samples if st >= t and x is not None), None)
    st = account_box_style(vertical=acct.thumb.layout != "box")
    tvf = video_filter(st, focus, path=[(0.0, x)] if x is not None else None)
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
    return [Highlight(**h) for h in data["highlights"]]


def _save_picks(path: str, count, highlights: list[Highlight]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": count, "highlights": [asdict(h) for h in highlights]},
                  f, ensure_ascii=False, indent=1)


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
                             words=transcript.words)
        for h in hs:
            h.account = acct.no
        print(f"  {len(hs)}개")
        picked += hs
    return picked


def cmd_shorts(args) -> None:
    from .accounts import ACCOUNTS
    from .accounts import parse as parse_accounts

    accts = parse_accounts(args.accounts or "")
    style = load_style(args.style, font=args.font)
    os.makedirs(args.output, exist_ok=True)
    total = media.duration(args.input)
    vertical = media.is_vertical(args.input)
    need_transcript = not args.no_subtitles or not args.ranges
    transcript = _get_transcript(args, args.input, args.output) if need_transcript else None

    picks_path = os.path.join(args.output, "highlights.json")
    # 고르는 방식이 바뀌면 앞의 v2를 올려서 예전에 고른 결과를 다시 쓰지 않게 한다
    key = (f"v2:accounts:{','.join(map(str, accts))}:{args.per_account}" if accts
           else f"v2:{args.count}")
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
        if accts:
            highlights = _pick_for_accounts(args, transcript, accts)
        else:
            print("[하이라이트 선정] Claude가 대본을 분석하는 중...")
            highlights = pick_highlights(transcript.sentences, count=args.count,
                                         min_len=args.min_len, max_len=args.max_len,
                                         context=args.context or "", words=transcript.words)
        _save_picks(picks_path, key, highlights)
    if not highlights:
        sys.exit("하이라이트를 찾지 못했습니다.")

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

    if os.path.abspath(args.settings) == os.path.abspath(SETTINGS):
        tidy_settings()  # 예전 업데이트가 흐트러뜨린 설정 파일 모양 정리
    out = settings.output_dir(args.input)
    shorts_args = build_parser().parse_args(
        settings.to_argv(args.input, settings.load(args.settings), out))
    shorts_args.func(shorts_args)

    print(f"\n완료! 결과 폴더: {out}")
    if hasattr(os, "startfile") and not os.environ.get("SHORTFORM_GUI"):
        os.startfile(out)  # Windows: 결과 폴더 열기 (프로그램 창에서는 창이 대신 연다)


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
    s.add_argument("--zoom", type=_yesno, default=False, help="핵심 단어에서 화면 확대 yes/no")
    s.add_argument("--sfx", type=_yesno, default=False, help="확대할 때 효과음 yes/no")
    s.add_argument("--bgm", help="배경음악 폴더 (mp3/wav를 숏폼마다 돌아가며 사용)")
    s.add_argument("--bgm-volume", type=float, default=0.15, help="배경음악 볼륨 0~1")
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
    s.add_argument("input")
    s.add_argument("--settings", default=SETTINGS)
    s.set_defaults(func=cmd_auto)

    s = sub.add_parser("style", help="스타일 설정을 JSON으로 출력 (내 스타일 만들기용)")
    s.add_argument("name", nargs="?", default="green")
    s.set_defaults(func=cmd_style)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as e:
        sys.exit(f"오류: {e}")
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다. 같은 명령을 다시 실행하면 끝난 부분부터 이어서 진행해요.")
