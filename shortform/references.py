"""레퍼런스(참고 자료) 읽기: 링크, 스크린샷, 짧은 영상 → Claude에게 보낼 내용.

사용자가 "이런 느낌으로" 만들고 싶은 예시를 넣으면, 하이라이트·제목·편집을 고를 때
Claude가 그 스타일(훅, 제목 말투, 자막 느낌, 구성, 템포)을 참고한다.

- 링크: 유튜브는 제목·채널·썸네일 이미지를 가져온다. 다른 사이트는 페이지 제목과 설명.
  (인스타그램처럼 로그인이 필요한 곳은 주소만 전달)
- 사진(png/jpg/webp): 그대로 (크기만 줄여서)
- 영상: 장면 4장을 뽑아서
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from html import unescape

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
MAX_IMAGES = 12
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

GUIDE = (
    "The creator attached the references below as examples of the style they want. Study "
    "them: hook style, title wording and length, subtitle tone, pacing, structure and mood. "
    "Follow that style in your choices and in everything you write, but never copy their "
    "content and only use moments that really exist in this footage.")


def _jpeg(data: bytes, max_side: int = 1024) -> str | None:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def _get(url: str, limit: int = 2_000_000) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read(limit)


def _youtube(url: str) -> tuple[str, str | None] | None:
    if not re.search(r"(youtube\.com|youtu\.be)/", url):
        return None
    api = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
    info = json.loads(_get(api).decode("utf-8", "replace"))
    text = f"YouTube video: \"{info.get('title', '')}\" by {info.get('author_name', '')}"
    if "/shorts/" in url:
        text += " (Shorts)"
    image = None
    if info.get("thumbnail_url"):
        image = _jpeg(_get(info["thumbnail_url"]))
    return text, image


def _page(url: str) -> tuple[str, str | None]:
    html = _get(url, 400_000).decode("utf-8", "replace")

    def meta(name: str) -> str:
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]+content=["\']([^"\']*)',
                      html, re.I)
        return unescape(m.group(1)).strip() if m else ""

    title = meta("og:title") or unescape(
        (re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S) or [None, ""])[1]).strip()
    desc = meta("og:description") or meta("description")
    image = None
    if meta("og:image"):
        try:
            image = _jpeg(_get(urllib.parse.urljoin(url, meta("og:image"))))
        except Exception:
            pass
    text = f"Web page: {title}" + (f" — {desc[:300]}" if desc else "")
    return text, image


def _video_frames(path: str, count: int = 4) -> list[str]:
    from . import media

    try:
        dur = media.duration(path)
    except Exception:
        return []
    shots = []
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(count):
            out = os.path.join(tmp, f"{k}.jpg")
            try:
                media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                           "-ss", f"{dur * (k + 0.5) / count:.2f}", "-i", path,
                           "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", out])
                with open(out, "rb") as f:
                    img = _jpeg(f.read(), 720)
                if img:
                    shots.append(img)
            except (RuntimeError, OSError):
                continue
    return shots


def blocks(refs: list[str] | None) -> list[dict]:
    """Claude 메시지에 넣을 내용 블록. 레퍼런스가 없으면 빈 목록."""
    refs = [r.strip() for r in refs or [] if r and r.strip()]
    if not refs:
        return []
    content: list[dict] = [{"type": "text", "text": f"<references>\n{GUIDE}"}]
    images = 0

    def add_image(data: str | None) -> None:
        nonlocal images
        if data and images < MAX_IMAGES:
            content.append({"type": "image", "source": {"type": "base64",
                                                        "media_type": "image/jpeg", "data": data}})
            images += 1

    for i, ref in enumerate(refs, 1):
        label = f"Reference {i}: "
        if re.match(r"https?://", ref):
            try:
                found = _youtube(ref) or _page(ref)
                content.append({"type": "text", "text": f"{label}{found[0]} ({ref})"})
                add_image(found[1])
            except Exception:  # 로그인이 필요하거나 막힌 사이트: 주소만
                content.append({"type": "text", "text": f"{label}link {ref}"})
            print(f"  레퍼런스 {i}: 링크")
        elif os.path.isfile(ref) and ref.lower().endswith(IMAGE_EXT):
            content.append({"type": "text", "text": f"{label}screenshot"})
            with open(ref, "rb") as f:
                add_image(_jpeg(f.read()))
            print(f"  레퍼런스 {i}: 사진 {os.path.basename(ref)}")
        elif os.path.isfile(ref) and ref.lower().endswith(VIDEO_EXT):
            content.append({"type": "text", "text": f"{label}short video (frames in order)"})
            for img in _video_frames(ref):
                add_image(img)
            print(f"  레퍼런스 {i}: 영상 {os.path.basename(ref)}")
        else:  # 글로 적은 설명
            content.append({"type": "text", "text": f"{label}{ref}"})
    content.append({"type": "text", "text": "</references>"})
    return content
