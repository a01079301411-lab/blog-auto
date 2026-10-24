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


def run_progress(total: float, cmd: list[str], cwd: str | None = None) -> None:
    """오래 걸리는 FFmpeg 작업: 진행률을 프로그램 창에 알리면서 실행한다."""
    from . import progress

    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=cwd, creationflags=NO_WINDOW)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and total > 0:
            try:
                progress.report(int(line.split("=")[1]) / 1e6 / total, "최종 영상")
            except ValueError:
                pass
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd[:4])}...\n{err[-2000:]}")


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


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".gif")


def voice_chain() -> str:
    """캡컷 '음성 향상'처럼: 웅웅거리는 저음을 걷어내고, 잡음을 조금 줄이고, 소리 크기를
    숏폼 기준(-14 LUFS)에 맞춘다."""
    chain = ["highpass=f=70"]
    if has_filter("afftdn"):
        chain.append("afftdn=nr=10:nf=-30")
    chain += ["loudnorm=I=-14:TP=-1.5:LRA=11", "aresample=48000"]
    return ",".join(chain)


def insert_graph(inserts: list[tuple[str, float, float]], first_idx: int, label: str,
                 bottom: int, max_w: int = 600, max_h: int = 440) -> tuple[list[str], list[str], str]:
    """짤·사진을 label 영상의 가운데, 아래쪽이 bottom(y)인 자리에 정해진 시간만 띄운다.

    돌려주는 것: (추가할 입력 인자, 필터 줄들, 마지막 영상 이름)"""
    inputs: list[str] = []
    parts: list[str] = []
    cur = label
    for k, (path, t0, t1) in enumerate(inserts):
        idx = first_idx + k
        still = os.path.splitext(path)[1].lower() in IMAGE_EXTS
        if still:
            inputs += ["-loop", "1", "-t", f"{t1 + 0.5:.3f}", "-i", os.path.abspath(path)]
            src_v = f"[{idx}:v]"
        else:  # 짧은 영상·움짤: 소리 없이 그 시각부터 재생
            inputs += ["-t", f"{t1 - t0 + 0.5:.3f}", "-i", os.path.abspath(path)]
            src_v = f"[{idx}:v]setpts=PTS-STARTPTS+{t0:.3f}/TB,"
        parts.append(f"{src_v}scale=w={max_w}:h={max_h}:force_original_aspect_ratio=decrease,"
                     f"format=rgba[im{k}]")
        nxt = f"[vi{k}]"
        parts.append(f"{cur}[im{k}]overlay=x=(W-w)/2:y={bottom}-h:"
                     f"enable='between(t,{t0:.3f},{t1:.3f})':"
                     f"eof_action={'repeat' if still else 'pass'}{nxt}")
        cur = nxt
    return inputs, parts, cur


def auto_color(src: str, start: float = 0.0, end: float | None = None, samples: int = 6) -> str:
    """캡컷 '자동 조정'처럼: 장면 몇 장을 보고 어두우면 밝게, 흐리멍덩하면 대비를,
    색이 바래 보이면 채도를 조금 올리는 필터. 손볼 게 없으면 빈 글자. (뒤에 쉼표가 붙는다)"""
    import numpy as np

    end = end if end is not None else duration(src)
    if end - start < 0.5:
        return ""
    lum, sat = [], []
    for k in range(samples):
        t = start + (end - start) * (k + 0.5) / samples
        try:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                 "-vf", f"{hdr_to_sdr(src)}scale=96:54", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                capture_output=True, creationflags=NO_WINDOW, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if len(raw) < 96 * 54 * 3:
            continue
        px = np.frombuffer(raw[:96 * 54 * 3], np.uint8).reshape(-1, 3) / 255.0
        lum.append(px @ np.array([0.2126, 0.7152, 0.0722]))
        sat.append(px.max(axis=1) - px.min(axis=1))
    if not lum:
        return ""
    y = np.concatenate(lum)
    mean, lo, hi = float(y.mean()), float(np.percentile(y, 2)), float(np.percentile(y, 98))
    chroma = float(np.concatenate(sat).mean())
    gamma = 1.0
    if mean < 0.42:  # 어두운 실내: 중간 밝기를 올린다 (밝은 곳은 덜 날아가게 감마로)
        gamma = min(1.0 + (0.42 - mean) * 1.6, 1.35)
    contrast = 1.0
    if hi - lo < 0.75:  # 뿌옇게 떠 보이면 대비를 조금
        contrast = min(1.0 + (0.75 - (hi - lo)) * 0.5, 1.12)
    saturation = 1.0
    if chroma < 0.22:  # 색이 바래 보이면 채도를 조금
        saturation = min(1.0 + (0.22 - chroma) * 1.2, 1.15)
    if gamma == contrast == saturation == 1.0:
        return ""
    return f"eq=gamma={gamma:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f},"


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
    inserts: list[tuple[str, float, float]] | None = None,
    insert_bottom: int = 1250,
    voice_enhance: bool = False,
    color: str = "",
) -> None:
    """src에서 segments 구간만 이어붙여 out으로 렌더링한다.

    segments의 시간은 원본 기준(초)이다. 필요한 범위만 디코딩하도록
    전체 구간 앞뒤로 입력 시킹을 건다.
    """
    if not segments:
        raise ValueError("남길 구간이 없습니다.")
    # 여러 장면을 이어 붙이면 시간 순서가 아닐 수 있어서 가장 이른·늦은 시간으로 범위를 잡는다
    base = max(0.0, min(s for s, _ in segments) - 1.0)
    end = max(e for _, e in segments) + 1.0

    parts, labels = [], []
    for i, (s, e) in enumerate(segments):
        s, e = s - base, e - base
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[vc][a0]")
    parts.append(f"[a0]{voice_chain() if voice_enhance else 'anull'}[a]")
    # 아이폰 HDR 영상은 색을 일반 영상에 맞추고, 자동 색 보정(color)이 있으면 그다음에
    parts.append(f"[vc]{hdr_to_sdr(src)}{color}null[v]")
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
        # 짤·사진 끼워 넣기: 자막 바로 위 가운데에 잠깐 띄운다 (자막은 그 위에 그려진다)
        ins_in, ins_parts, cur = insert_graph(inserts or [], n_inputs, "[vl2]", insert_bottom)
        inputs += ins_in
        n_inputs += len(inserts or [])
        parts += ins_parts
        parts.append(f"{cur}null[vl3]")
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
            sub = f"[vl3]subtitles=filename=subs{ext}{fontsdir}"
            if ext != ".ass":  # ASS는 파일 안에 스타일이 있다
                sub += f":force_style='{subtitle_style(font)}'"
            parts.append(sub + "[vout]")
        else:
            parts.append("[vl3]null[vout]")

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


def merge_videos(inputs: list[str], out: str) -> list[tuple[str, float, float]]:
    """여러 영상을 하나로 이어 붙인다 (전체에서 숏폼 몇 개만 고를 때). 이미 같은 영상이 있으면 그대로.

    크기·초당 프레임은 첫 영상에 맞춘다. 돌려주는 것: (원본 파일, 합친 영상에서 시작, 끝)들.
    """
    spans, t = [], 0.0
    for p in inputs:
        d = duration(p)
        spans.append((p, t, t + d))
        t += d
    stamp = out + ".json"
    sig = [[os.path.abspath(p), os.path.getmtime(p)] for p in inputs]
    try:
        with open(stamp, encoding="utf-8") as f:
            if json.load(f) == sig and os.path.exists(out):
                return spans
    except (OSError, ValueError):
        pass
    w, h = display_size(inputs[0])
    w, h = w - w % 2, h - h % 2
    fps = round(fps_value(inputs[0])) or 30
    args, parts, labels = [], [], []
    for i, p in enumerate(inputs):
        args += ["-i", os.path.abspath(p)]
    n = len(inputs)
    for i, p in enumerate(inputs):
        parts.append(f"[{i}:v]{hdr_to_sdr(p)}scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
        if has_audio(p):
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            args += ["-f", "lavfi", "-t", f"{duration(p):.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            parts.append(f"[{n}:a]anull[a{i}]")
            n += 1
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(inputs)}:v=1:a=1[v][a]")
    tmp = out + ".tmp.mp4"
    with tempfile.TemporaryDirectory() as work:
        with open(os.path.join(work, "filter.txt"), "w", encoding="utf-8") as f:
            f.write(";\n".join(parts))
        run_progress(t, ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args,
                         *filter_script_args("filter.txt"), "-map", "[v]", "-map", "[a]",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "15",
                         "-pix_fmt", "yuv420p", *COLOR_TAGS, "-c:a", "aac", "-b:a", "192k",
                         os.path.abspath(tmp)], cwd=work)
    os.replace(tmp, out)
    with open(stamp, "w", encoding="utf-8") as f:
        json.dump(sig, f)
    return spans
