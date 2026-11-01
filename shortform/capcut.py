"""캡컷(CapCut PC) 프로젝트 내보내기: 영상 안의 모든 글자를 캡컷에서 고칠 수 있게.

숏폼을 만들 때 글자 없는 '깨끗한 영상'을 따로 뽑고, 그 위에 제목·훅·자막·인물 소개·중간 한마디·
썸네일 글자를 캡컷 텍스트 조각으로, 짤과 표지(썸네일 바탕)를 이미지 조각으로, 배경음악을 오디오
조각으로 올린 캡컷 초안(draft)을 만든다. 캡컷을 열면 홈 화면 '프로젝트'에 바로 보인다.

pyCapCut(https://github.com/GuanYixuan/pyCapCut, 0.0.4)으로 초안 파일을 쓴다. 캡컷 PC 8~9 버전에서
확인된 형식이다. 글꼴은 캡컷 기본 글꼴로 들어가니 캡컷에서 원하는 글꼴로 바꾸면 된다.
"""
from __future__ import annotations

import os
import re

W, H = 1080, 1920
YELLOW = (1.0, 0.882, 0.302)
WHITE = (1.0, 1.0, 1.0)


def draft_root(fallback: str) -> str:
    """캡컷이 초안을 두는 폴더 (윈도우). 캡컷이 없으면 fallback (결과 폴더 안)."""
    base = os.environ.get("LOCALAPPDATA", "")
    for parts in (("CapCut", "User Data", "Projects", "com.lveditor.draft"),
                  ("CapCut", "User Data", "Projects", "com.lveditor.draft".upper())):
        p = os.path.join(base, *parts)
        if base and os.path.isdir(p):
            return p
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _us(sec: float) -> int:
    return int(round(max(sec, 0) * 1_000_000))


def _plain(text: str) -> str:
    """{강조} 표시와 줄바꿈 표시를 캡컷 글자로."""
    return re.sub(r"[{}]", "", text.replace("\\n", "\n")).strip()


def _y(center_px: float, height: int = H) -> float:
    """화면 y(픽셀, 위가 0) → 캡컷 위치 (가운데 0, 위 +1, 아래 -1)."""
    return (height / 2 - center_px) / (height / 2)


def export(name: str, fallback_dir: str, *, video: str, total: float, cues=(), title: str = "",
           title_y: float = 360, hook: str = "", hook_end: float = 2.2, rehook: str = "",
           rehook_at: float = 0.0, speaker: str = "", bottom: str = "", sub_y: float = 1380,
           bottom_y: float = 1600,
           bgm: str | None = None, bgm_volume: float = 0.15, inserts=(), insert_bottom: float = 1250,
           cover: str | None = None, cover_text: str = "", cover_dur: float = 0.0,
           size: tuple[int, int] = (W, H), extra_texts=()) -> str:
    """캡컷 초안을 만들고 그 폴더 경로를 돌려준다.

    extra_texts: (트랙 이름, 글자, 시작, 끝, 글자 크기, 가운데 y) — 롱폼 챕터 제목 등.
    """
    import pycapcut as cc
    from pycapcut import (ClipSettings, TextBorder, TextSegment, TextShadow, TextStyle,
                          TrackType, VideoSegment, AudioSegment, trange)

    root = draft_root(fallback_dir)
    folder = cc.DraftFolder(root)
    safe = re.sub(r'[\\/:*?"<>|]', "", name).strip()[:60] or "숏폼"
    width, height = size
    script = folder.create_draft(safe, width, height, 30, allow_replace=True)
    main = cc.VideoMaterial(os.path.abspath(video))
    T = min(_us(total), main.duration)  # 영상 파일 길이를 넘지 않게

    def rng(a: float, b: float):
        a_us = min(_us(a), T - 1)
        return trange(a_us, max(min(_us(b), T) - a_us, 1))

    # 글자 트랙: 캡컷에서 트랙마다 한꺼번에 고치기 쉽게 종류별로 나눈다 (쓰는 것만 만든다)
    layers = {"자막": 0, "인물 소개": 1, "하단 문구": 2, "중간 한마디": 3, "훅": 4, "제목": 5,
              "표지 글자": 10}
    for i, extra in enumerate(dict.fromkeys(e[0] for e in extra_texts)):
        layers.setdefault(extra, 6 + i)
    made: set[str] = set()

    def text(track: str, content: str, a: float, b: float, *, size: float, y: float,
             color=WHITE, stroke: float = 40.0, wrap: bool = True):
        content = _plain(content)
        if not content or b - a <= 0.05:
            return
        if track not in made:
            script.add_track(TrackType.text, track, relative_index=layers[track])
            made.add(track)
        script.add_segment(TextSegment(
            content, rng(a, b),
            style=TextStyle(size=size, bold=True, color=color, align=1, auto_wrapping=wrap,
                            max_line_width=0.8),
            clip_settings=ClipSettings(transform_y=_y(y, height)),
            border=TextBorder(width=stroke), shadow=TextShadow(alpha=0.6)), track)

    # 영상·이미지·소리 트랙 (뒤 → 앞)
    script.add_track(TrackType.video)
    script.add_segment(VideoSegment(main, trange(0, T)))
    if inserts:
        script.add_track(TrackType.video, "짤", relative_index=1)
        for path, a, b in inserts:
            script.add_segment(VideoSegment(os.path.abspath(path), rng(a, b), clip_settings=ClipSettings(
                scale_x=0.55, scale_y=0.55, transform_y=_y(insert_bottom - 230, height))), "짤")
    if bgm:
        script.add_track(TrackType.audio, "배경음악")
        script.add_segment(AudioSegment(os.path.abspath(bgm), trange(0, T), volume=bgm_volume),
                           "배경음악")

    for c in cues:
        line = (c.note + " " if getattr(c, "note", "") else "") + c.text
        text("자막", line, c.start, c.end, size=9, y=sub_y,
             color=YELLOW if getattr(c, "who", "main") == "other" else WHITE)
    if speaker:
        text("인물 소개", f"[{speaker}]", 0, total, size=6, y=sub_y - 110, color=YELLOW, stroke=30)
    if bottom:
        text("하단 문구", bottom, 0, total, size=7, y=bottom_y, stroke=30)
    if rehook and rehook_at > 0:
        text("중간 한마디", rehook, rehook_at, min(rehook_at + 2.5, total), size=10, y=700, color=YELLOW)
    if hook:
        text("훅", hook, cover_dur, hook_end, size=13, y=880, color=YELLOW)
    if title:
        text("제목", title, cover_dur, total, size=12, y=title_y)
    for track, content, a, b, sz, y in extra_texts:
        text(track, content, a, b, size=sz, y=y)

    # 표지(썸네일): 영상 첫 화면. 바탕 그림과 글자를 따로 넣어 글자도 고칠 수 있게
    if cover and cover_dur > 0:
        script.add_track(TrackType.video, "표지", relative_index=2)
        script.add_segment(VideoSegment(os.path.abspath(cover), rng(0, cover_dur)), "표지")
        text("표지 글자", cover_text, 0, cover_dur, size=17, y=520, stroke=55)
    script.save()
    return os.path.join(root, safe)
