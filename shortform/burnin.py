"""원본 영상에 이미 자막이 박혀 있는지(하드 자막) 찾는다.

자막 글자는 '밝은 글자 + 바로 옆의 어두운 테두리'이고, 화면 아래쪽의 같은 높이에
나오며, 말에 따라 계속 바뀐다. 구간 안에서 장면 몇 장을 뽑아 이 특징을 세어 보고,
자막이 있으면 자막이 나오는 높이와 가로 범위(원본 비율 0~1)를 돌려준다.
그러면 숏폼을 만들 때 새 자막을 넣지 않고, 화면을 원본 자막이 다 보이게 자른다.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np

DETECT_W = 640
SAMPLES = 16


@dataclass
class Burned:
    x0: float   # 자막이 나오는 가로 범위 (원본 비율)
    x1: float
    y0: float   # 자막이 나오는 높이 범위 (원본 비율)
    y1: float
    ratio: float  # 장면 중 자막이 보인 비율


def _frames(src: str, start: float, end: float, n: int):
    from . import media

    w, h = media.display_size(src)
    if not w:
        return
    dh = round(h * DETECT_W / w / 2) * 2
    span = max(end - start, 0.1)
    for k in range(n):
        t = start + span * (k + 0.5) / n
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", src,
             "-frames:v", "1", "-vf", f"scale={DETECT_W}:{dh}", "-f", "rawvideo",
             "-pix_fmt", "bgr24", "-"],
            capture_output=True, creationflags=media.NO_WINDOW)
        if len(proc.stdout) == DETECT_W * dh * 3:
            yield np.frombuffer(proc.stdout, np.uint8).reshape(dh, DETECT_W, 3)


def text_mask(frame: np.ndarray) -> np.ndarray:
    """자막 글자처럼 보이는 픽셀: 아주 밝은(흰색·노란색) 픽셀 중 바로 옆에 어두운 테두리가 있는 것."""
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v, s, hue = hsv[..., 2], hsv[..., 1], hsv[..., 0]
    white = (v > 215) & (s < 60)
    yellow = (v > 200) & (s > 90) & (hue > 18) & (hue < 38)
    dark = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) < 60).astype(np.uint8)
    near_dark = cv2.dilate(dark, np.ones((3, 3), np.uint8), iterations=2) > 0
    return (white | yellow) & near_dark


def _band(mask: np.ndarray) -> tuple[int, int, int] | None:
    """아래쪽 절반에서 글자 픽셀이 가장 몰린 줄 띠 (위, 아래, 픽셀 수)."""
    h, w = mask.shape
    top = int(h * 0.5)
    rows = mask[top:].sum(axis=1)
    on = rows >= max(4, w * 0.006)
    best, k = None, 0
    while k < len(on):
        if not on[k]:
            k += 1
            continue
        a = k
        while k < len(on) and (on[k] or (k + 2 < len(on) and on[k + 1:k + 3].any())):
            k += 1
        size = int(rows[a:k].sum())
        if best is None or size > best[2]:
            best = (top + a, top + k, size)
    if best is None:
        return None
    a, b, size = best
    # 자막 한두 줄 높이(화면의 2~20%)이고 글자 픽셀이 충분해야 한다
    if not (h * 0.02 <= b - a <= h * 0.2) or size < w * 0.25:
        return None
    return best


def detect(src: str, start: float, end: float) -> Burned | None:
    """구간에 원본 자막이 있으면 그 위치, 없으면 None."""
    hits, masks = [], []
    frames = 0
    for frame in _frames(src, start, end, SAMPLES):
        frames += 1
        mask = text_mask(frame)
        band = _band(mask)
        if band is None:
            continue
        a, b, _ = band
        prof = mask[a:b].sum(axis=0).astype(float)
        if prof.sum() < 20:
            continue
        # 글자 픽셀의 왼쪽 3%~오른쪽 97% 지점 (띠에 걸친 배경 밝은 점은 무시)
        cum = np.cumsum(prof) / prof.sum()
        h, w = mask.shape
        left, right = int(np.searchsorted(cum, 0.03)), int(np.searchsorted(cum, 0.97))
        hits.append((a / h, b / h, left / w, right / w))
        masks.append(mask[a:b])
    if frames == 0 or len(hits) < max(3, frames * 0.4):
        return None
    ys = np.array([(a + b) / 2 for a, b, _, _ in hits])
    same_row = np.abs(ys - np.median(ys)) < 0.06
    if same_row.sum() < max(3, frames * 0.4):
        return None  # 매번 다른 높이: 자막이 아니라 화면 속 글씨
    hits = [hit for hit, ok in zip(hits, same_row) if ok]
    masks = [m for m, ok in zip(masks, same_row) if ok]
    # 내용이 바뀌어야 자막이다 (늘 같은 모양이면 로고·워터마크)
    widths = [x1 - x0 for _, _, x0, x1 in hits]
    if max(widths) - min(widths) < 0.03:
        return None
    y0 = float(np.percentile([a for a, _, _, _ in hits], 10))
    y1 = float(np.percentile([b for _, b, _, _ in hits], 90))
    x0 = float(np.percentile([x0 for _, _, x0, _ in hits], 10))
    x1 = float(np.percentile([x1 for _, _, _, x1 in hits], 90))
    return Burned(x0, x1, y0, y1, len(hits) / frames)
