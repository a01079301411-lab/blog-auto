"""얼굴 위치를 찾아 세로 화면이 사람을 따라가게 하는 자동 크롭.

원본 영상에서 1초에 몇 장씩 프레임을 뽑아 YuNet(OpenCV) 얼굴 인식으로 가장 큰
얼굴의 가로 위치를 찾고, 흔들리지 않게 부드럽게 만든 뒤 시간에 따른 위치
목록으로 돌려준다. 렌더링할 때 이 목록으로 crop의 x 위치를 움직인다.
"""
from __future__ import annotations

import os
import subprocess

import numpy as np

MODEL = os.path.join(os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx")
SAMPLE_FPS = 5
DETECT_W = 640  # 인식용으로 줄인 프레임 가로 크기


def _frames(src: str, start: float, end: float):
    """[start, end] 구간을 SAMPLE_FPS로 뽑아 (시간, BGR 배열)을 차례로 돌려준다."""
    from . import media

    info = next(s for s in media.probe(src)["streams"] if s["codec_type"] == "video")
    w, h = int(info["width"]), int(info["height"])
    rot = info.get("side_data_list", [{}])[0].get("rotation", 0) if info.get("side_data_list") else 0
    if abs(int(rot or 0)) in (90, 270):  # 세로로 찍은 폰 영상
        w, h = h, w
    dh = round(h * DETECT_W / w / 2) * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
         "-vf", f"fps={SAMPLE_FPS},scale={DETECT_W}:{dh}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE)
    size = DETECT_W * dh * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / SAMPLE_FPS, np.frombuffer(buf, np.uint8).reshape(dh, DETECT_W, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def detect(src: str, start: float, end: float) -> list[tuple[float, float | None, float]]:
    """(원본 시간, 얼굴 가운데 x 비율 0~1 또는 None, 얼굴 크기 비율) 목록."""
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # 영어 경고 숨김
    import cv2

    cv2.setLogLevel(2) if hasattr(cv2, "setLogLevel") else None

    detector = None
    out = []
    prev_x = None
    for t, frame in _frames(src, start, end):
        if detector is None:
            detector = cv2.FaceDetectorYN.create(MODEL, "", (frame.shape[1], frame.shape[0]),
                                                 score_threshold=0.6)
        _, faces = detector.detect(frame)
        if faces is None or len(faces) == 0:
            out.append((t, None, 0.0))
            continue
        # 가장 큰 얼굴. 비슷한 크기면 직전 위치에 가까운 얼굴 (화면이 사람 사이를 오가지 않게)
        def score(f):
            area = f[2] * f[3]
            cx = (f[0] + f[2] / 2) / frame.shape[1]
            near = 1.0 if prev_x is None else 1.0 - min(abs(cx - prev_x), 0.5)
            return area * (0.7 + 0.3 * near)
        f = max(faces, key=score)
        cx = float((f[0] + f[2] / 2) / frame.shape[1])
        prev_x = cx
        out.append((t, cx, float(f[2] * f[3]) / (frame.shape[0] * frame.shape[1])))
    return out


def smooth_path(samples: list[tuple[float, float | None, float]],
                default: float = 0.5) -> list[tuple[float, float]]:
    """얼굴 위치를 카메라가 움직이듯 부드럽게 만든다.

    - 얼굴을 못 찾은 프레임은 앞뒤 값으로 채운다
    - 중간값 필터로 순간적인 오인식을 없앤다
    - 작은 흔들림은 무시하고(데드존), 크게 움직일 때만 천천히 따라간다
    """
    if not samples:
        return [(0.0, default)]
    ts = [t for t, _, _ in samples]
    xs = [x for _, x, _ in samples]
    known = [i for i, x in enumerate(xs) if x is not None]
    if not known:
        return [(ts[0], default), (ts[-1], default)]
    filled = np.interp(range(len(xs)), known, [xs[i] for i in known])

    k = SAMPLE_FPS  # 1초 창 중간값
    med = np.array([np.median(filled[max(0, i - k // 2):i + k // 2 + 1])
                    for i in range(len(filled))])

    out = []
    cam = med[0]
    for t, target in zip(ts, med):
        if abs(target - cam) > 0.06:  # 데드존: 얼굴이 조금 움직이는 건 무시
            cam += (target - cam) * 0.25  # 천천히 따라감
        out.append((t, float(cam)))
    return out


def best_frame_time(samples: list[tuple[float, float | None, float]]) -> float | None:
    """썸네일용: 얼굴이 가장 크게 잡힌 시간."""
    faces = [(size, t) for t, x, size in samples if x is not None]
    return max(faces)[1] if faces else None
