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



def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    # FFmpeg 출력은 UTF-8이다. Windows 기본 인코딩(cp949)으로 읽으면 한글에서 깨진다
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=cwd)
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
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=1[v][a]")
    parts.append(video_filter or "[v]null[vl]")
    with tempfile.TemporaryDirectory() as work:
        if srt:
            # 자막 경로를 필터 안에 쓰면 Windows 드라이브 문자(C:)·한글·따옴표 이스케이프가
            # 까다로우므로, 영문 이름으로 복사해 두고 그 폴더에서 FFmpeg을 실행한다
            ext = os.path.splitext(srt)[1]
            shutil.copyfile(srt, os.path.join(work, "subs" + ext))
            sub = f"[vl]subtitles=filename=subs{ext}"
            if ext != ".ass":  # ASS는 파일 안에 스타일이 있다
                sub += f":force_style='{subtitle_style(font)}'"
            parts.append(sub + "[vout]")
        else:
            parts.append("[vl]null[vout]")

        script = os.path.join(work, "filter.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(";\n".join(parts))
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{base:.3f}", "-to", f"{end:.3f}", "-i", os.path.abspath(src),
            *filter_script_args("filter.txt"),
            "-map", "[vout]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
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
