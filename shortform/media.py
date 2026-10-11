"""FFmpeg 호출 헬퍼."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

Segment = tuple[float, float]

SHORTS_W, SHORTS_H = 1080, 1920


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd[:4])}...\n{proc.stderr[-2000:]}")
    return proc


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]).stdout
    return json.loads(out)


def duration(path: str) -> float:
    return float(probe(path)["format"]["duration"])


def _escape_filter_path(path: str) -> str:
    # 필터 그래프 안에서 쓰는 파일 경로 이스케이프 (Windows 경로의 ':' 포함)
    path = os.path.abspath(path).replace("\\", "/")
    return path.replace(":", r"\:").replace("'", r"\'")


def layout_filter(layout: str) -> str:
    """[v] 입력을 받아 [vl]을 출력하는 레이아웃 필터."""
    if layout == "original":
        return "[v]null[vl]"
    if layout == "crop":
        return (f"[v]crop='min(iw,ih*9/16)':ih,"
                f"scale={SHORTS_W}:{SHORTS_H},setsar=1[vl]")
    if layout == "blur":
        return (f"[v]split[bg0][fg0];"
                f"[bg0]scale={SHORTS_W}:{SHORTS_H}:force_original_aspect_ratio=increase,"
                f"crop={SHORTS_W}:{SHORTS_H},boxblur=20:5[bg];"
                f"[fg0]scale={SHORTS_W}:-2[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vl]")
    raise ValueError(f"알 수 없는 레이아웃: {layout}")


def subtitle_style(layout: str, font: str | None) -> str:
    vertical = layout != "original"
    style = [
        f"Fontsize={14 if vertical else 18}",
        "PrimaryColour=&H00FFFFFF", "OutlineColour=&H00000000",
        "BorderStyle=1", "Outline=2", "Shadow=0", "Bold=1",
        "Alignment=2", f"MarginV={70 if vertical else 25}",
    ]
    if font:
        style.append(f"FontName={font}")
    return ",".join(style)


def render(
    src: str,
    segments: list[Segment],
    out: str,
    *,
    layout: str = "original",
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
    parts.append(layout_filter(layout))
    if srt:
        style = subtitle_style(layout, font)
        parts.append(f"[vl]subtitles=filename='{_escape_filter_path(srt)}'"
                     f":force_style='{style}'[vout]")
    else:
        parts.append("[vl]null[vout]")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(";\n".join(parts))
        script = f.name
    try:
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{base:.3f}", "-to", f"{end:.3f}", "-i", src,
            "-filter_complex_script", script,
            "-map", "[vout]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            out,
        ])
    finally:
        os.unlink(script)
