"""settings.ini 읽기·쓰기. run.bat(auto 명령)과 프로그램 창(gui)이 같이 쓴다."""
from __future__ import annotations

import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "settings.ini")

DEFAULTS = {
    "style": "green", "count": "10", "min_len": "20", "max_len": "60",
    "context": "", "speaker": "", "focus": "auto", "model": "small", "font": "",
    "review": "yes", "fix_subtitles": "yes", "zoom": "yes", "sfx": "yes",
    "bgm_volume": "0.15", "thumbnail": "yes", "upload": "no",
}


def load(path: str = PATH) -> dict[str, str]:
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(path, encoding="utf-8-sig"):  # 메모장이 붙이는 BOM 처리
        raise RuntimeError(f"설정 파일을 찾을 수 없어요: {path}")
    section = cfg["shorts"] if cfg.has_section("shorts") else {}
    return {k: section.get(k, v).strip() for k, v in DEFAULTS.items()}


def save(values: dict[str, str], path: str = PATH) -> None:
    """주석과 순서는 그대로 두고 값만 바꾼다."""
    from .update import _render, _values, _write_if_changed

    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    current = _values(text)
    merged = {**current, **{k: str(v) for k, v in values.items()}}
    extra = {k: v for k, v in merged.items() if k not in current}
    _write_if_changed(path, text, _render(text, merged, extra))


def to_argv(video: str, c: dict[str, str], out: str) -> list[str]:
    """설정 값 → `python -m shortform shorts ...` 인자."""
    argv = ["shorts", video, "-o", out,
            "--style", c["style"], "-n", c["count"],
            "--min-len", c["min_len"], "--max-len", c["max_len"],
            "--focus", c["focus"], "--model", c["model"],
            "--fix-subtitles", c["fix_subtitles"], "--review", c["review"],
            "--zoom", c["zoom"], "--sfx", c["sfx"],
            "--bgm", os.path.join(ROOT, "bgm"), "--bgm-volume", c["bgm_volume"],
            "--thumbnail", c["thumbnail"], "--upload", c["upload"]]
    for key in ("context", "speaker", "font"):
        if c.get(key, "").strip():
            argv += [f"--{key}", c[key].strip()]
    return argv


def output_dir(video: str) -> str:
    return os.path.splitext(os.path.abspath(video))[0] + "_shorts"
