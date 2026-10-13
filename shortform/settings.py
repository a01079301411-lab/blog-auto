"""settings.ini 읽기·쓰기. run.bat(auto 명령)과 프로그램 창(gui)이 같이 쓴다."""
from __future__ import annotations

import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "settings.ini")

DEFAULTS = {
    "accounts": "", "per_account": "3",
    "style": "green", "count": "10", "min_len": "20", "max_len": "60",
    "context": "", "speaker": "", "focus": "auto", "model": "small", "font": "",
    "subtitles": "yes", "review": "no", "review_wait": "3", "fix_subtitles": "yes", "burned_subs": "auto",
    "bgm_volume": "0.15", "thumbnail": "yes", "upload": "no",
}


# [longform] 칸. update.py가 이름만 보고 병합하므로 숏폼 설정과 겹치지 않게 long_ 을 붙인다
LONG_DEFAULTS = {
    "long_context": "", "long_minutes": "0", "long_commerce": "no", "long_review": "no",
    "long_frames": "yes", "long_jumpcut": "yes", "long_subtitles": "yes",
    "long_fix_subtitles": "yes", "long_chapter_titles": "yes", "long_bgm_volume": "0.10",
    "long_thumbnail": "yes", "long_model": "small", "long_font": "",
}


def load(path: str = PATH) -> dict[str, str]:
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(path, encoding="utf-8-sig"):  # 메모장이 붙이는 BOM 처리
        raise RuntimeError(f"설정 파일을 찾을 수 없어요: {path}")
    section = cfg["shorts"] if cfg.has_section("shorts") else {}
    return {k: section.get(k, v).strip() for k, v in DEFAULTS.items()}


def load_long(path: str = PATH) -> dict[str, str]:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(path, encoding="utf-8-sig")
    section = cfg["longform"] if cfg.has_section("longform") else {}
    return {k: section.get(k, v).strip() for k, v in LONG_DEFAULTS.items()}


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
            "--burned-subs", c["burned_subs"] if c["burned_subs"] in ("auto", "yes", "no") else "auto",
            "--bgm", os.path.join(ROOT, "bgm"), "--bgm-volume", c["bgm_volume"],
            "--thumbnail", c["thumbnail"], "--upload", c["upload"],
            *(["--no-subtitles"] if c["subtitles"].lower() == "no" else []),
            "--accounts", c["accounts"], "--per-account", c["per_account"]]
    for key in ("context", "speaker", "font"):
        if c.get(key, "").strip():
            argv += [f"--{key}", c[key].strip()]
    return argv


def output_dir(video: str) -> str:
    return os.path.splitext(os.path.abspath(video))[0] + "_shorts"


def long_output_dir(inputs: list[str], title: str = "") -> str:
    first = os.path.abspath(inputs[0])
    base = first if os.path.isdir(first) else os.path.dirname(first)
    name = "".join(ch for ch in (title or "").strip() if ch not in '\\/:*?"<>|').strip()
    return os.path.join(base, f"롱폼_{name}" if name else "롱폼_결과")


def long_argv(inputs: list[str], c: dict[str, str], *, plan: str | None = None,
              output: str | None = None, title: str = "", replan: bool = False) -> list[str]:
    """[longform] 설정 값 → `python -m shortform long ...` 인자."""
    argv = ["long", *inputs, "-o", output or long_output_dir(inputs, title),
            "--minutes", c["long_minutes"] or "0", "--commerce", c["long_commerce"],
            "--review", c["long_review"], "--frames", c["long_frames"],
            "--jumpcut", c["long_jumpcut"], "--subtitles", c["long_subtitles"],
            "--fix-subtitles", c["long_fix_subtitles"],
            "--chapter-titles", c["long_chapter_titles"],
            "--bgm", os.path.join(ROOT, "bgm"), "--bgm-volume", c["long_bgm_volume"],
            "--thumbnail", c["long_thumbnail"], "--model", c["long_model"] or "small"]
    if plan:
        argv += ["--plan", plan]
    if c.get("long_context", "").strip():
        argv += ["--context", c["long_context"].strip()]
    if c.get("long_font", "").strip():
        argv += ["--font", c["long_font"].strip()]
    if replan:
        argv.append("--replan")
    return argv
