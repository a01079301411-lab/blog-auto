"""영상 렌더: video/render2.py → audio.py → ffmpeg 합치기 (기존 렌더 코드는 그대로 호출)."""
from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from . import qa
from .config import OUT, ROOT, VIDEO


def render_one(key: str, v: str, stills: bool = False) -> list[qa.Issue]:
    d = OUT / f"{key}_{v}"
    d.mkdir(parents=True, exist_ok=True)
    cfg = f"data/products/{key}.json"
    run = lambda *a: subprocess.run(list(a), cwd=ROOT, check=True)  # noqa: E731
    if stills:
        run(sys.executable, str(VIDEO / "render2.py"), cfg, v, str(d), "stills")
        return []
    run(sys.executable, str(VIDEO / "render2.py"), cfg, v, str(d))
    run(sys.executable, str(VIDEO / "audio.py"), str(d / "bgm.wav"), str(d / "plan.json"))
    final = d / f"insaengtem_{key}_{v}.mp4"
    part = d / "final.part.mp4"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(d / "video_silent.mp4"), "-i", str(d / "bgm.wav"),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(part))
    part.replace(final)
    for tmp in d.glob("*.mp4"):
        if tmp != final:
            tmp.unlink()
    return qa.check_video(final)


def render_many(keys: list[str], variants: list[str], stills: bool = False, jobs: int = 3) -> dict:
    out = {}
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {(k, v): ex.submit(render_one, k, v, stills) for k in keys for v in variants}
        for kv, f in futs.items():
            try:
                out[kv] = f.result()
                print(f"[render] {kv[0]} {kv[1]} {'OK' if not out[kv] else out[kv]}")
            except Exception as e:  # noqa: BLE001
                out[kv] = [qa.Issue("error", "RENDER", str(e), f"{kv}")]
                print(f"[render] {kv} 실패: {e}")
    return out
