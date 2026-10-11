"""명령줄 진입점: python -m shortform <명령> ..."""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile

from . import media
from .highlights import Highlight, parse_ranges, pick_highlights
from .silence import detect_silences, keep_segments
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
    return transcribe(path, model=args.model, language=args.language or None, cache=cache)


def _render_clip(args, src, start, end, out, transcript, layout) -> None:
    keeps = _cut_ranges(args, src, start, end)
    kept = sum(e - s for s, e in keeps)
    if not keeps:
        raise RuntimeError("남길 구간이 없습니다. --noise 값을 낮춰 보세요 (예: -45).")
    print(f"  {_hms(end - start)} → {_hms(kept)} (무음 {_hms(end - start - kept)} 제거, "
          f"{len(keeps)}개 조각)")
    srt = None
    if transcript is not None:
        words = remap(words_in_range(transcript.words, start, end), keeps)
        srt = os.path.splitext(out)[0] + ".srt"
        write_srt(build_cues(words, max_chars=args.max_chars), srt)
    media.render_long(src, keeps, out, layout=layout, srt=srt, font=args.font)
    print(f"  저장: {out}")


def cmd_silence(args) -> None:
    out = args.output or os.path.splitext(args.input)[0] + "_cut.mp4"
    print("[무음 구간 제거] 무음 구간 찾는 중... (긴 영상은 몇 분 걸려요)")
    _render_clip(args, args.input, 0.0, media.duration(args.input), out, None, "original")


def cmd_subtitle(args) -> None:
    base = os.path.splitext(args.input)[0]
    transcript = _get_transcript(args, args.input, os.path.dirname(os.path.abspath(args.input)))
    srt = args.output or base + ".srt"
    write_srt(build_cues(transcript.words, max_chars=args.max_chars), srt)
    print(f"  자막 저장: {srt}")
    if args.burn:
        print("[자막 입히기]")
        media.render(args.input, [(0.0, media.duration(args.input))], args.burn,
                     layout="original", srt=srt, font=args.font)
        print(f"  저장: {args.burn}")


def _safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")[:40] or "clip"


def cmd_shorts(args) -> None:
    os.makedirs(args.output, exist_ok=True)
    total = media.duration(args.input)
    need_transcript = not args.no_subtitles or not args.ranges
    transcript = _get_transcript(args, args.input, args.output) if need_transcript else None

    if args.ranges:
        highlights = parse_ranges(args.ranges)
    else:
        print("[하이라이트 선정] Claude가 대본을 분석하는 중...")
        highlights = pick_highlights(transcript.sentences, count=args.count,
                                     min_len=args.min_len, max_len=args.max_len)
    if not highlights:
        sys.exit("하이라이트를 찾지 못했습니다.")

    for i, h in enumerate(highlights, 1):
        h.start, h.end = max(0.0, h.start), min(total, h.end)
        score = f"  점수 {h.score}/10" if h.score else ""
        print(f"\n[{i}/{len(highlights)}] {h.title}  ({_hms(h.start)} ~ {_hms(h.end)}){score}")
        if h.reason:
            print(f"  이유: {h.reason}")
        out = os.path.join(args.output, f"{i:02}_{_safe_name(h.title)}.mp4")
        _render_clip(args, args.input, h.start, h.end, out,
                     None if args.no_subtitles else transcript, args.layout)


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
    g.add_argument("--language", default="ko", help="음성 언어 (기본 ko, 빈 값이면 자동 감지)")
    g.add_argument("--font", help="자막 폰트 이름 (예: 'NanumGothic', 'Malgun Gothic')")
    g.add_argument("--max-chars", type=int, default=16, help="자막 한 줄 최대 글자 수")

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
    s.add_argument("--ranges", help="AI 대신 직접 구간 지정. 예: '60-120,5:00-5:45'")
    s.add_argument("--layout", choices=["blur", "crop", "original"], default="blur",
                   help="blur: 흐린 배경 위에 원본 / crop: 가운데 잘라 꽉 채움")
    s.add_argument("--no-subtitles", action="store_true", help="자막 안 넣음")
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
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as e:
        sys.exit(f"오류: {e}")
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다. 같은 명령을 다시 실행하면 끝난 부분부터 이어서 진행해요.")
