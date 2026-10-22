"""짤·사진 끼워 넣기: 프로그램 폴더의 '짤' 폴더에 모아 둔 이미지·짧은 영상 중에서
AI가 자막 줄에 맞는 것을 골라 잠깐 띄운다.

AI는 그림을 보지 않고 파일 이름만 보고 고른다. 그래서 파일 이름을 내용대로 지어 두면 된다.
예: '놀람_눈 커지는 고양이.png', '아내와 남편 사진.jpg', '퇴사하는 직장인.gif'
저작권 걱정이 없도록 직접 찍었거나 써도 되는 것만 넣는다.
"""
from __future__ import annotations

import os

from .media import IMAGE_EXTS, VIDEO_EXTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "짤")
MAX_FILES = 80
GUIDE = """짤·사진 폴더

여기에 넣은 사진(png, jpg, webp)과 짧은 영상(mp4, mov, gif)을 AI가 숏폼 자막에 맞춰 잠깐 띄워요.
AI는 그림을 보지 않고 파일 이름만 보고 골라요. 그래서 이름을 내용대로 지어 주세요.
  예) 놀람_눈 커지는 고양이.png / 아내와 남편 사진.jpg / 퇴사하는 직장인.gif
하위 폴더에 넣어도 돼요 (폴더 이름도 설명으로 써요).
저작권 문제가 없도록 직접 찍었거나 써도 되는 사진만 넣어 주세요.
"""


def ensure_folder() -> str:
    os.makedirs(FOLDER, exist_ok=True)
    guide = os.path.join(FOLDER, "읽어주세요.txt")
    if not os.path.exists(guide):
        with open(guide, "w", encoding="utf-8-sig") as f:
            f.write(GUIDE)
    return FOLDER


def files() -> dict[str, str]:
    """AI에게 보여 줄 이름 → 파일 경로. 이름은 '하위폴더/파일이름' (확장자 포함)."""
    out: dict[str, str] = {}
    if not os.path.isdir(FOLDER):
        return out
    for dirpath, _dirs, names in os.walk(FOLDER):
        for n in sorted(names):
            if os.path.splitext(n)[1].lower() in IMAGE_EXTS + VIDEO_EXTS:
                path = os.path.join(dirpath, n)
                out[os.path.relpath(path, FOLDER).replace(os.sep, "/")] = path
                if len(out) >= MAX_FILES:
                    return out
    return out


def timeline(cues, chosen: dict[str, str]) -> list[tuple[str, float, float]]:
    """자막 줄에 고른 짤 → (파일, 시작, 끝). 1.2~2초 보여 주고 서로 겹치지 않게."""
    out: list[tuple[str, float, float]] = []
    for c in cues:
        path = chosen.get(c.image) if c.image else None
        if not path:
            continue
        start = c.start
        if out and start < out[-1][2] + 0.3:
            continue
        end = min(max(c.end, start + 1.2), start + 2.0)
        out.append((path, start, end))
    return out[:8]
