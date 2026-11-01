"""스크롤을 멈추게 하는 숏폼 썸네일 (표지) 만들기.

요즘 잘되는 숏폼·유튜브 썸네일의 공통 방식을 따른다.
1) 장면 고르기: 얼굴이 크고, 표정이 살아 있고(크게 웃거나 놀란 입), 흔들리지 않고, 어둡지 않은 장면.
   AI가 고른 '썸네일 순간'(thumb_time)이 있으면 그 근처를 먼저 본다.
2) 화면 만들기: 얼굴이 화면의 30% 정도가 되게 확대해 세로로 자르고, 밝기·대비·채도·선명도를 올린다.
3) 글자: 2줄, 아주 크고 굵게(검은고딕), 흰 글자 + 두꺼운 검은 테두리 + 그림자, 핵심 단어만 노란색.
   플랫폼 메뉴에 가리지 않게 위쪽 안전 영역(위에서 300px 아래)에 두고, 얼굴은 그 아래에 오게 자른다.

거짓 장면을 그려 넣지 않는다: 영상에 실제로 있는 장면만 쓰고, 글자는 AI가 영상 내용 안에서 쓴다
(정도를 키우는 표현은 되지만 없는 일을 지어내지 않게 지시한다).
"""
from __future__ import annotations

import os
import re
import subprocess

import numpy as np

from . import media
from .face import MODEL

W, H = 1080, 1920
TOP = 300                    # 플랫폼 위쪽 메뉴를 피한 글자 시작 높이
ACCENT = (255, 225, 77)      # 노란 강조
FONT = os.path.join(os.path.dirname(__file__), "assets", "fonts", "BlackHanSans.ttf")


def _grab(src: str, t: float) -> np.ndarray | None:
    """t초 장면 (RGB). HDR이면 일반 색으로 바꿔서."""
    w, h = media.display_size(src)
    scale = min(1.0, 1920 / max(w, h))
    w2, h2 = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", src, "-frames:v", "1",
         "-vf", f"{media.hdr_to_sdr(src)}scale={w2}:{h2}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, creationflags=media.NO_WINDOW).stdout
    if len(raw) < w2 * h2 * 3:
        return None
    return np.frombuffer(raw[:w2 * h2 * 3], np.uint8).reshape(h2, w2, 3)


_DET = {}


def _faces(img: np.ndarray):
    """[(x, y, w, h, 표정 점수)] — 표정 점수: 입꼬리 사이가 눈 사이보다 넓을수록(크게 웃음) 높다."""
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    import cv2

    small = 640 / img.shape[1]
    bgr = cv2.cvtColor(cv2.resize(img, (640, int(img.shape[0] * small))), cv2.COLOR_RGB2BGR)
    key = (bgr.shape[1], bgr.shape[0])
    if key not in _DET:
        _DET[key] = cv2.FaceDetectorYN.create(MODEL, "", key, score_threshold=0.6)
    _, faces = _DET[key].detect(bgr)
    out = []
    for f in faces if faces is not None else []:
        x, y, w, h = (float(v) / small for v in f[:4])
        eyes = np.hypot(f[4] - f[6], f[5] - f[7])
        mouth = np.hypot(f[10] - f[12], f[11] - f[13])
        out.append((x, y, w, h, float(mouth / eyes) if eyes > 0 else 0.0))
    return out


def pick_frame(src: str, times: list[float], prefer: float | None = None, limit: int = 18):
    """후보 시간들 중 썸네일로 가장 좋은 장면. (시간, RGB, 얼굴)

    큰 얼굴 + 크게 웃는 입 + (후보들 중에서) 덜 흔들린 장면 + 너무 어둡지 않은 장면.
    """
    cands = sorted(dict.fromkeys(round(t, 2) for t in times))
    if len(cands) > limit:  # 고르게 줄인다 (AI가 고른 순간 근처는 꼭 넣는다)
        step = len(cands) / limit
        keep = [cands[int(i * step)] for i in range(limit)]
        if prefer is not None:
            keep += [min(cands, key=lambda t: abs(t - prefer))]
        cands = sorted(set(keep))
    shots = []
    for t in cands:
        img = _grab(src, t)
        if img is None:
            continue
        gray = img.mean(axis=2)
        sharp = float(np.abs(np.diff(gray, axis=0)).mean() + np.abs(np.diff(gray, axis=1)).mean())
        faces = _faces(img)
        face = max(faces, key=lambda f: f[2] * f[3], default=None)
        shots.append((t, img, face, sharp, float(gray.mean() / 255)))
    if not shots:
        return None, None, None
    top_sharp = max(x[3] for x in shots) or 1.0
    best, best_s = None, -1e9
    for t, img, face, sharp, bright in shots:
        s = 1.2 * sharp / top_sharp - max(0.0, 0.3 - bright) * 3
        if face:
            area = face[2] * face[3] / (img.shape[0] * img.shape[1])
            s += min(area * 25, 2.0) + max(0.0, face[4] - 0.75) * 3
        if prefer is not None and abs(t - prefer) < 1.5:
            s += 0.8  # AI가 고른 순간
        if s > best_s:
            best, best_s = (t, img, face), s
    return best


def _canvas(img: np.ndarray, face):
    """얼굴을 화면 30% 크기로 키워 세로(9:16)로 자르고 보정한다. (그림, 얼굴 가운데 y 비율)"""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    ih, iw = img.shape[:2]
    # 자를 창 크기: 기본은 원본에서 9:16이 되는 가장 큰 창, 얼굴이 작으면 더 좁게(확대)
    cw = min(iw, ih * 9 / 16)
    if face:
        cw = min(cw, max(face[2] / 0.30, cw * 0.55))
    ch = cw * 16 / 9
    if face:
        fx, fy = face[0] + face[2] / 2, face[1] + face[3] / 2
        x0 = fx - cw / 2
        y0 = fy - ch * 0.62  # 얼굴은 화면 가운데보다 아래 (위에는 글자)
    else:
        x0, y0 = (iw - cw) / 2, (ih - ch) / 2
    x0 = min(max(x0, 0), iw - cw)
    y0 = min(max(y0, 0), ih - ch)
    face_y = ((face[1] + face[3] / 2) - y0) / ch if face else 0.6
    im = Image.fromarray(img).crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
    im = im.resize((W, H), Image.LANCZOS)
    im = ImageOps.autocontrast(im, cutoff=1)
    mean = np.asarray(im.convert("L")).mean() / 255
    if mean < 0.45:  # 어두운 장면은 밝게
        im = ImageEnhance.Brightness(im).enhance(min(1.0 + (0.45 - mean) * 1.6, 1.45))
    im = ImageEnhance.Color(im).enhance(1.25)
    im = ImageEnhance.Contrast(im).enhance(1.1)
    return im.filter(ImageFilter.UnsharpMask(radius=3, percent=90, threshold=2)), face_y


def _lines(text: str) -> list[list[tuple[str, bool]]]:
    """'첫 줄\\n{강조} 둘째 줄' → 줄마다 (글자, 강조 여부) 조각들."""
    out = []
    for ln in [x.strip() for x in text.replace("\\n", "\n").split("\n") if x.strip()][:3]:
        parts = re.split(r"(\{[^}]*\})", ln)
        out.append([(p.strip("{}"), p.startswith("{")) for p in parts if p])
    if out and not any(hl for line in out for _, hl in line):
        out[-1] = [(t, True) for t, _ in out[-1]]  # 강조가 없으면 마지막 줄을 강조
    return out


BOTTOM = 1260  # 아래쪽에 둘 때 글자 묶음의 아래 끝 (설명란·버튼을 피해서)


def draw_text(im, text: str, label: str = "", where: str = "top"):
    """썸네일 글자: 안전 영역 안에 아주 크게. where: top(위) / bottom(얼굴이 위에 있을 때 아래)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    lines = _lines(text)
    if not lines:
        return im
    plain = ["".join(t for t, _ in ln) for ln in lines]
    size = 200
    while size > 90:
        font = ImageFont.truetype(FONT, size)
        if max(font.getlength(p) for p in plain) <= W - 140:
            break
        size -= 6
    font = ImageFont.truetype(FONT, size)
    gap = int(size * 0.18)
    stroke = max(8, size // 11)
    top = TOP
    lab_h = 0
    if label:
        lf = ImageFont.truetype(FONT, 64)
        lab_h = 64 + 40
    block = lab_h + len(lines) * size + (len(lines) - 1) * gap
    if where == "bottom":
        top = BOTTOM - block
    # 글자 뒤를 어둡게 (읽기 쉽게): 위면 위에서부터, 아래면 글자 둘레만
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    if where == "bottom":
        a, b = top - 160, BOTTOM + 200
        for y in range(max(a, 0), min(b, H)):
            k = 1 - abs((y - (a + b) / 2) / ((b - a) / 2))
            sd.line([(0, y), (W, y)], fill=int(150 * max(0.0, k) ** 0.6))
    else:
        for y in range(0, top + block + 160):
            sd.line([(0, y), (W, y)], fill=int(150 * max(0.0, 1 - y / (top + block + 160)) ** 0.8))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, shade)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = top
    if label:  # 빨간 알약 꼬리표
        tw = lf.getlength(label)
        x0 = (W - tw) / 2 - 28
        d.rounded_rectangle([x0, y, x0 + tw + 56, y + 84], radius=42, fill=(235, 40, 50, 255))
        d.text((W / 2, y + 42), label, font=lf, fill="white", anchor="mm")
        y += lab_h
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdw = ImageDraw.Draw(shadow)
    for ln, text_line in zip(lines, plain):
        x = (W - font.getlength(text_line)) / 2
        for t, hl in ln:
            sdw.text((x + 10, y + 12), t, font=font, fill=(0, 0, 0, 200))
            d.text((x, y), t, font=font, fill=ACCENT if hl else (255, 255, 255),
                   stroke_width=stroke, stroke_fill=(0, 0, 0))
            x += font.getlength(t)
        y += size + gap
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    out = im.convert("RGBA")
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    return out.convert("RGB")


def make(src: str, out_jpg: str, *, text: str, times: list[float], prefer: float | None = None,
         label: str = "", base_png: str | None = None) -> float | None:
    """썸네일을 만들고 고른 장면 시간을 돌려준다. base_png를 주면 글자 없는 바탕도 저장(캡컷용)."""
    t, img, face = pick_frame(src, times, prefer)
    if img is None:
        return None
    base, face_y = _canvas(img, face)
    if base_png:
        base.save(base_png)
    # 얼굴이 화면 맨 위쪽에 있을 때만 글자를 아래로 (그 밖에는 위: 이마·머리는 가려져도
    # 표정이 사는 눈·입은 보이게)
    where = "bottom" if face and face_y < 0.36 else "top"
    draw_text(base, text, label, where).save(out_jpg, quality=92)
    return t
