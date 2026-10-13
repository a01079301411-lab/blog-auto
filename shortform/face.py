"""얼굴 위치를 찾아 세로 화면이 사람을 따라가게 하는 자동 크롭.

사람이 카메라를 잡듯이 움직이게 한다.
- 원본 영상의 장면이 바뀌면(카메라 전환) 그 순간 새 위치로 바로 넘어간다 (패닝 없음)
- 한 장면 안에서는 화면을 고정해 두고, 사람이 화면 가장자리 쪽으로 1.2초 넘게 벗어나
  있을 때만 부드럽게 옮긴다 (작은 움직임, 순간적인 오인식은 무시)
- 두 사람이 한 화면에 다 들어가면 두 사람을 같이 잡고, 안 들어가면 그 장면의
  주인공(가장 크게, 오래 나온 사람)을 계속 잡는다 (사람 사이를 왔다 갔다 하지 않게)
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

import numpy as np

MODEL = os.path.join(os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx")
SAMPLE_FPS = 8
DETECT_W = 640  # 인식용으로 줄인 프레임 가로 크기


@dataclass
class Sample:
    t: float
    faces: list[tuple[float, float]] = field(default_factory=list)  # (가운데 x 비율, 크기 비율)
    cut: bool = False  # 바로 앞 장면과 다른 장면 (카메라 전환)

    @property
    def x(self) -> float | None:
        return max(self.faces, key=lambda f: f[1])[0] if self.faces else None

    @property
    def size(self) -> float:
        return max((f[1] for f in self.faces), default=0.0)


def _frames(src: str, start: float, end: float):
    """[start, end] 구간을 SAMPLE_FPS로 뽑아 (시간, BGR 배열)을 차례로 돌려준다."""
    from . import media

    w, h = media.display_size(src)
    dh = round(h * DETECT_W / w / 2) * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
         "-vf", f"fps={SAMPLE_FPS},scale={DETECT_W}:{dh}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, creationflags=media.NO_WINDOW)
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


def detect(src: str, start: float, end: float) -> list[Sample]:
    """구간의 얼굴들과 장면 전환을 찾는다 (시간은 원본 기준)."""
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # 영어 경고 숨김
    import cv2

    detector = None
    out: list[Sample] = []
    diffs, corrs = [], []
    prev_gray = prev_hist = None
    for t, frame in _frames(src, start, end):
        if detector is None:
            detector = cv2.FaceDetectorYN.create(MODEL, "", (frame.shape[1], frame.shape[0]),
                                                 score_threshold=0.6)
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18)).astype(np.float32)
        small = cv2.resize(frame, (64, 36))
        hist = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 8],
                            [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev_gray is None:
            diffs.append(0.0)
            corrs.append(1.0)
        else:
            diffs.append(float(np.abs(gray - prev_gray).mean()))
            corrs.append(float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)))
        prev_gray, prev_hist = gray, hist
        _, faces = detector.detect(frame)
        fs = []
        area = frame.shape[0] * frame.shape[1]
        for f in faces if faces is not None else []:
            fs.append((float((f[0] + f[2] / 2) / frame.shape[1]), float(f[2] * f[3]) / area))
        out.append(Sample(t, fs))
    # 장면 전환: 앞 장면과 확 달라진 순간 (손에 들고 찍어 계속 흔들리는 영상도 있으니
    # 주변보다 유난히 크게 바뀐 곳만)
    for i in range(1, len(out)):
        around = diffs[max(1, i - SAMPLE_FPS):i] + diffs[i + 1:i + 1 + SAMPLE_FPS]
        base = float(np.median(around)) if around else 0.0
        out[i].cut = corrs[i] < 0.6 or (diffs[i] > 32 and diffs[i] > base * 1.8) or \
            (corrs[i] < 0.85 and diffs[i] > 25)
    return out


# ---------- 카메라 경로 ----------

def _shots(samples: list[Sample]) -> list[list[Sample]]:
    shots: list[list[Sample]] = []
    for s in samples:
        if not shots or s.cut:
            shots.append([])
        shots[-1].append(s)
    # 너무 짧은 장면(0.4초 미만)은 오인식일 수 있어 앞 장면에 붙인다
    merged: list[list[Sample]] = []
    for shot in shots:
        if merged and len(shot) < SAMPLE_FPS * 0.4:
            merged[-1] += shot
        else:
            merged.append(shot)
    return merged


def _targets(shot: list[Sample], view: float) -> list[float | None]:
    """장면 안에서 시간마다 화면 가운데에 둘 위치."""
    # 장면의 주인공: 얼굴 크기 × 나온 횟수가 가장 큰 위치
    weight: dict[int, float] = {}
    for s in shot:
        top = s.size
        for x, size in s.faces:
            if size >= top * 0.3:
                weight[int(x * 10)] = weight.get(int(x * 10), 0.0) + size
    main = (max(weight, key=weight.get) + 0.5) / 10 if weight else None

    out: list[float | None] = []
    prev = main
    for s in shot:
        top = s.size
        faces = [f for f in s.faces if f[1] >= top * 0.3]
        if not faces:
            out.append(None)
            continue
        xs = [x for x, _ in faces]
        face_w = max(np.sqrt(size) for _, size in faces)  # 얼굴 폭 (대략)
        if len(faces) > 1 and max(xs) - min(xs) + face_w * 1.5 <= view * 0.9:
            target = (max(xs) + min(xs)) / 2  # 다 같이 들어가면 같이 잡는다
        else:
            if main is not None:
                # 주인공에서 먼 얼굴(다른 사람)은 무시: 주인공이 잠깐 안 잡혀도 화면은 그대로
                xs = [x for x in xs if abs(x - main) <= view * 0.5]
                if not xs:
                    out.append(None)
                    continue
            ref = prev if prev is not None else main
            target = min(xs, key=lambda x: abs(x - ref)) if ref is not None else xs[0]
        prev = target
        out.append(target)
    return out


def _fill(values: list[float | None], default: float) -> np.ndarray:
    """얼굴을 못 찾은 곳은 직전 위치 그대로 (처음이면 다음 위치), 그리고 튀는 값 제거."""
    known = [v for v in values if v is not None]
    if not known:
        return np.full(len(values), default)
    filled, last = [], known[0]
    for v in values:
        last = v if v is not None else last
        filled.append(last)
    k = max(3, int(SAMPLE_FPS * 0.75)) | 1  # 0.75초 중간값
    arr = np.array(filled)
    return np.array([np.median(arr[max(0, i - k // 2):i + k // 2 + 1]) for i in range(len(arr))])


def _ease(points: list[tuple[float, float]], t0: float, a: float, t1: float, b: float) -> None:
    """t0에 a에서 t1에 b로 부드럽게(천천히 출발해 천천히 멈춤) 움직이는 점들."""
    for k in range(1, 6):
        u = k / 6
        points.append((t0 + (t1 - t0) * u, a + (b - a) * (u * u * (3 - 2 * u))))
    points.append((t1, b))


def smooth_path(samples: list[Sample], view: float = 0.56, default: float = 0.5,
                lo: float | None = None, hi: float | None = None) -> list[tuple[float, float]]:
    """얼굴 위치 → 카메라 경로 [(시간, 화면 가운데 x 비율)].

    view: 원본 가로 중 화면에 보이는 비율. lo, hi: 화면 가운데가 갈 수 있는 범위
    (원본 자막이 잘리지 않게 할 때 사용).
    """
    if not samples:
        return [(0.0, default)]
    lo = view / 2 if lo is None else lo
    hi = 1 - view / 2 if hi is None else hi
    if lo > hi:
        lo = hi = (lo + hi) / 2
    clamp = lambda x: float(min(max(x, lo), hi))
    safe = view * 0.22          # 이만큼 벗어나도 화면은 그대로
    wait = int(SAMPLE_FPS * 1.2)  # 1.2초 넘게 벗어나 있어야 움직인다
    rest = int(SAMPLE_FPS * 1.5)  # 한 번 움직이면 1.5초는 그대로

    points: list[tuple[float, float]] = []
    cam = None
    for shot in _shots(samples):
        xs = _fill(_targets(shot, view), cam if cam is not None else default)
        ts = [s.t for s in shot]
        first = clamp(float(np.median(xs[:SAMPLE_FPS])))
        if cam is None:
            points.append((ts[0], first))
        elif abs(first - cam) > 0.005:  # 장면 전환: 그 순간 바로 넘어간다
            at = max(ts[0] - 0.5 / SAMPLE_FPS, points[-1][0] + 0.002)
            points += [(at - 0.001, cam), (at, first)]
        cam = first
        i = 0
        while i < len(ts):
            ahead = xs[i:i + wait]
            if len(ahead) >= wait and all(abs(x - cam) > safe for x in ahead) and \
                    (all(x > cam for x in ahead) or all(x < cam for x in ahead)):
                new = clamp(float(np.median(xs[i:i + int(SAMPLE_FPS * 1.5)])))
                if abs(new - cam) > 0.01:
                    dur = min(max(abs(new - cam) / view * 1.6, 0.6), 1.4)
                    points.append((ts[i], cam))
                    _ease(points, ts[i], cam, ts[i] + dur, new)
                    cam = new
                    i += int(dur * SAMPLE_FPS) + rest
                    continue
            i += 1
    points.append((samples[-1].t, cam))
    # 시간 순서가 꼬인 점 정리
    out: list[tuple[float, float]] = []
    for t, x in points:
        if out and t <= out[-1][0]:
            if t < out[-1][0]:
                continue
            out[-1] = (t, x)
        else:
            out.append((t, x))
    return out


def best_frame_time(samples: list[Sample]) -> float | None:
    """썸네일용: 얼굴이 가장 크게 잡힌 시간."""
    faces = [(s.size, s.t) for s in samples if s.faces]
    return max(faces)[1] if faces else None
