"""FFmpeg 호출 헬퍼."""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import tempfile

Segment = tuple[float, float]



# 프로그램 창(콘솔 없음)에서 실행할 때 FFmpeg 등의 검은 창이 뜨지 않게 한다
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    # FFmpeg 출력은 UTF-8이다. Windows 기본 인코딩(cp949)으로 읽으면 한글에서 깨진다
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=cwd, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd[:4])}...\n{proc.stderr[-2000:]}")
    return proc


@functools.cache
def _ffmpeg_major() -> int:
    out = run(["ffmpeg", "-hide_banner", "-version"]).stdout
    m = re.search(r"ffmpeg version n?(\d+)\.", out)
    return int(m.group(1)) if m else 7  # git 빌드 등 버전을 못 읽으면 최신으로 간주


def filter_script_args(path: str) -> list[str]:
    """필터를 파일에서 읽는 옵션. FFmpeg 7부터 '-/filter_complex 파일'로 바뀌었다."""
    if _ffmpeg_major() >= 7:
        return ["-/filter_complex", path]
    return ["-filter_complex_script", path]


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]).stdout
    return json.loads(out)


def frame_rate(path: str) -> str:
    """원본 영상의 프레임레이트 (예: '30000/1001'). 확대 효과 필터에 넘긴다."""
    for st in probe(path)["streams"]:
        if st.get("codec_type") == "video":
            rate = st.get("avg_frame_rate") or st.get("r_frame_rate") or "30"
            if rate not in ("0/0", "0"):
                return rate
    return "30"


def snapshot(src: str, t: float, out: str, *, video_filter: str, ass: str | None = None) -> None:
    """t초 장면 한 장을 숏폼 화면 구성으로 저장한다 (썸네일용)."""
    with tempfile.TemporaryDirectory() as work:
        graph = video_filter.replace("[v]", "[0:v]", 1)
        if ass:
            shutil.copyfile(ass, os.path.join(work, "subs.ass"))
            graph += ";[vl]subtitles=filename=subs.ass[vout]"
        else:
            graph += ";[vl]null[vout]"
        with open(os.path.join(work, "filter.txt"), "w", encoding="utf-8") as f:
            f.write(graph)
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", f"{max(t, 0):.3f}", "-i", os.path.abspath(src),
             *filter_script_args("filter.txt"), "-map", "[vout]",
             "-frames:v", "1", "-q:v", "2", os.path.abspath(out)], cwd=work)


def display_size(path: str) -> tuple[int, int]:
    """화면에 보이는 가로·세로 크기 (휴대폰 회전 정보까지 고려). 영상이 없으면 (0, 0)."""
    for st in probe(path)["streams"]:
        if st.get("codec_type") == "video":
            w, h = int(st.get("width", 0)), int(st.get("height", 0))
            rot = 0
            for sd in st.get("side_data_list", []) or []:
                rot = int(sd.get("rotation", 0) or 0) or rot
            rot = rot or int((st.get("tags") or {}).get("rotate", 0) or 0)
            if abs(rot) in (90, 270):
                w, h = h, w
            return w, h
    return 0, 0


def is_vertical(path: str) -> bool:
    """세로로 찍은 영상인지 (휴대폰 회전 정보까지 고려)."""
    w, h = display_size(path)
    return h > w


@functools.cache
def has_filter(name: str) -> bool:
    out = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


def is_hdr(path: str) -> bool:
    """아이폰·갤럭시 HDR 영상(HLG, PQ)인지. 그냥 변환하면 색이 뿌옇고 회색빛이 된다."""
    for st in probe(path)["streams"]:
        if st.get("codec_type") == "video":
            return st.get("color_transfer") in ("arib-std-b67", "smpte2084") or \
                st.get("color_primaries") == "bt2020"
    return False


def hdr_to_sdr(path: str) -> str:
    """HDR 영상이면 일반(SDR) 색으로 바꾸는 필터 (끝에 쉼표 포함). 아니면 빈 글자."""
    if not is_hdr(path):
        return ""
    if has_filter("zscale") and has_filter("tonemap"):
        return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    return "colorspace=all=bt709:fast=1,"  # zscale이 없는 FFmpeg: 대충이라도 맞춘다


def fps_value(path: str) -> float:
    rate = frame_rate(path)
    try:
        a, _, b = rate.partition("/")
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return 30.0


# 출력 파일에 색 정보를 적어 둔다 (플레이어마다 색이 다르게 보이지 않게)
COLOR_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
              "-color_range", "tv"]


def has_audio(path: str) -> bool:
    return any(st.get("codec_type") == "audio" for st in probe(path)["streams"])


def duration(path: str) -> float:
    return float(probe(path)["format"]["duration"])


def subtitle_style(font: str | None) -> str:
    """가로 원본 영상에 SRT 자막을 입힐 때의 스타일."""
    style = [
        "Fontsize=18", "PrimaryColour=&H00FFFFFF", "OutlineColour=&H00000000",
        "BorderStyle=1", "Outline=2", "Shadow=0", "Bold=1", "Alignment=2", "MarginV=25",
    ]
    if font:
        style.append(f"FontName={font}")
    return ",".join(style)


def render(
    src: str,
    segments: list[Segment],
    out: str,
    *,
    video_filter: str | None = None,
    srt: str | None = None,
    font: str | None = None,
    bgm: str | None = None,
    bgm_volume: float = 0.15,
    sfx: str | None = None,
    sfx_times: list[float] | None = None,
    sfx_volume: float = 0.6,
    overlay: str | None = None,
    font_files: list[str] | None = None,
) -> None:
    """src에서 segments 구간만 이어붙여 out으로 렌더링한다.

    segments의 시간은 원본 기준(초)이다. 필요한 범위만 디코딩하도록
    전체 구간 앞뒤로 입력 시킹을 건다.
    """
    if not segments:
        raise ValueError("남길 구간이 없습니다.")
    base = max(0.0, segments[0][0] - 1.0)
    end = segments[-1][1] + 1.0

    parts, labels = [], []
    for i, (s, e) in enumerate(segments):
        s, e = s - base, e - base
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[vc][a]")
    parts.append(f"[vc]{hdr_to_sdr(src)}null[v]")  # 아이폰 HDR 영상은 색을 일반 영상에 맞춘다
    parts.append(video_filter or "[v]null[vl]")

    # 배경음악·효과음 섞기
    inputs: list[str] = []
    n_inputs = 1  # 0번은 원본 영상
    duration = sum(e - s for s, e in segments)
    mix = ["[a]"]
    if bgm:
        idx, n_inputs = n_inputs, n_inputs + 1
        inputs += ["-stream_loop", "-1", "-i", os.path.abspath(bgm)]
        fade = max(duration - 1.5, 0)
        parts.append("[a]asplit[voice][key]")
        parts.append(f"[{idx}:a]aresample=48000,volume={bgm_volume:.3f},atrim=0:{duration:.3f},"
                     f"afade=t=in:d=0.5,afade=t=out:st={fade:.3f}:d=1.5[bg0]")
        # 말할 때 배경음악을 자동으로 줄인다 (사이드체인 덕킹)
        parts.append("[bg0][key]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=500[bg]")
        mix = ["[voice]", "[bg]"]
    if sfx and sfx_times:
        idx, n_inputs = n_inputs, n_inputs + 1
        inputs += ["-i", os.path.abspath(sfx)]
        n = len(sfx_times)
        outs = "".join(f"[sx{k}]" for k in range(n))
        parts.append(f"[{idx}:a]aresample=48000,volume={sfx_volume:.3f},asplit={n}{outs}" if n > 1
                     else f"[{idx}:a]aresample=48000,volume={sfx_volume:.3f}[sx0]")
        for k, t in enumerate(sfx_times):
            ms = max(int(t * 1000) - 150, 0)  # 확대 직전에 '휙'
            parts.append(f"[sx{k}]adelay=delays={ms}:all=1[sd{k}]")
            mix.append(f"[sd{k}]")
    if len(mix) > 1:
        parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[aout]")
        audio_label = "[aout]"
    else:
        audio_label = "[a]"
    with tempfile.TemporaryDirectory() as work:
        if overlay:  # 제목 등 영상 내내 고정인 글자 (투명 PNG)
            idx, n_inputs = n_inputs, n_inputs + 1
            inputs += ["-i", os.path.abspath(overlay)]
            parts.append(f"[vl][{idx}:v]overlay=0:0:format=auto[vo]")
            parts.append("[vo]null[vl2]")
        else:
            parts.append("[vl]null[vl2]")
        fontsdir = ""
        if font_files:  # 자막 글꼴을 작업 폴더에 모아 libass가 이름으로 찾게 한다
            os.makedirs(os.path.join(work, "fonts"), exist_ok=True)
            for k, ff in enumerate(dict.fromkeys(font_files)):
                shutil.copyfile(ff, os.path.join(work, "fonts", f"f{k}{os.path.splitext(ff)[1]}"))
            fontsdir = ":fontsdir=fonts"
        if srt:
            # 자막 경로를 필터 안에 쓰면 Windows 드라이브 문자(C:)·한글·따옴표 이스케이프가
            # 까다로우므로, 영문 이름으로 복사해 두고 그 폴더에서 FFmpeg을 실행한다
            ext = os.path.splitext(srt)[1]
            shutil.copyfile(srt, os.path.join(work, "subs" + ext))
            sub = f"[vl2]subtitles=filename=subs{ext}{fontsdir}"
            if ext != ".ass":  # ASS는 파일 안에 스타일이 있다
                sub += f":force_style='{subtitle_style(font)}'"
            parts.append(sub + "[vout]")
        else:
            parts.append("[vl2]null[vout]")

        script = os.path.join(work, "filter.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(";\n".join(parts))
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{base:.3f}", "-to", f"{end:.3f}", "-i", os.path.abspath(src),
            *inputs,
            *filter_script_args("filter.txt"),
            "-map", "[vout]", "-map", audio_label,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-profile:v", "high", *COLOR_TAGS,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            os.path.abspath(out),
        ], cwd=work)


def _group(segments: list[Segment], max_span: float,
           max_count: int) -> list[list[Segment]]:
    groups: list[list[Segment]] = [[]]
    for seg in segments:
        g = groups[-1]
        if g and (seg[1] - g[0][0] > max_span or len(g) >= max_count):
            groups.append([])
        groups[-1].append(seg)
    return groups


def render_long(
    src: str,
    segments: list[Segment],
    out: str,
    *,
    group_minutes: float = 3,
    group_count: int = 40,
    **kwargs,
) -> None:
    """수천 개의 조각이 나오는 긴 영상용 render.

    조각이 많을수록 한 번의 FFmpeg 호출이 급격히 느려지므로, 원본 기준
    group_minutes 분량 / group_count 조각씩 나눠 렌더링한 뒤 이어붙인다.
    조각 파일을 남겨두므로 중간에 멈춰도 다시 실행하면 이어서 진행한다.
    """
    groups = _group(segments, group_minutes * 60, group_count)
    if len(groups) == 1:
        render(src, segments, out, **kwargs)
        return

    parts_dir = out + ".parts"
    os.makedirs(parts_dir, exist_ok=True)
    parts = []
    for i, group in enumerate(groups, 1):
        part = os.path.join(parts_dir, f"{i:04}_{group[0][0]:.2f}_{group[-1][1]:.2f}.mp4")
        parts.append(part)
        if os.path.exists(part):
            print(f"  [{i}/{len(groups)}] 저장된 조각 사용")
            continue
        print(f"  [{i}/{len(groups)}] 렌더링 중... ({len(group)}개 조각)")
        tmp = part + ".tmp.mp4"
        render(src, group, tmp, **kwargs)
        os.replace(tmp, part)

    listing = os.path.join(parts_dir, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '{}'\n".format(os.path.abspath(p).replace("'", r"'\''")))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listing,
         "-c", "copy", "-movflags", "+faststart", out])
    shutil.rmtree(parts_dir, ignore_errors=True)
