"""배경음악을 직접 만든다 (저작권 걱정 없는 자작곡).

음원을 가져다 쓰지 않고, 화음 진행·베이스·멜로디·드럼을 이 코드가 매번 새로 합성한다.
그래서 유튜브·인스타 저작권 신고(Content ID)에 걸릴 일이 없다.

분위기(mood)마다 빠르기, 장조/단조, 화음 진행, 악기 구성이 다르다.
- bright(밝음): 브이로그, 일상, 데이트
- calm(잔잔): 감동, 진지한 이야기
- tension(긴장): 강의, 정보, 반전
- funny(유쾌): 웃긴 장면, 코믹

같은 seed면 같은 곡, seed가 다르면 다른 곡이 나온다. 앞뒤가 자연스럽게 이어지게 만들어
영상이 곡보다 길면 반복해서 깔 수 있다.
"""
from __future__ import annotations

import hashlib
import os
import wave

import numpy as np

SR = 44100
MOODS = {
    #           빠르기  장/단조  화음 진행(도수)                악기
    "bright":  (104, "major", [[1, 5, 6, 4], [6, 4, 1, 5], [1, 4, 6, 5]], "pluck"),
    "calm":    (78, "major", [[1, 6, 4, 5], [4, 5, 3, 6], [1, 3, 4, 4]], "piano"),
    "tension": (92, "minor", [[1, 6, 3, 7], [1, 7, 6, 7], [6, 7, 1, 1]], "pulse"),
    "funny":   (116, "major", [[1, 4, 5, 4], [1, 6, 2, 5], [4, 5, 1, 1]], "bounce"),
}
MOOD_NAMES = {"bright": "밝음", "calm": "잔잔", "tension": "긴장", "funny": "유쾌"}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]


def _freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    """앞은 attack초 동안 커지고 끝은 release초 동안 작아지는 볼륨 곡선."""
    e = np.ones(n)
    a, r = min(int(attack * SR), n), min(int(release * SR), n)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[n - r:] *= np.linspace(1, 0, r)
    return e


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """부드러운 소리를 위해 높은 소리를 깎는다 (주파수 영역에서, 추가 설치 없이)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def _pad(freqs: list[float], dur: float, rng) -> np.ndarray:
    """부드러운 화음 바탕 (살짝 어긋난 톱니파 두 개를 겹쳐 따뜻하게)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for detune in (-0.12, 0.12):
            ph = rng.random() * 2 * np.pi
            ff = f * 2 ** (detune / 12)
            saw = 2 * ((t * ff + ph / (2 * np.pi)) % 1) - 1
            out += saw
    return out / (len(freqs) * 2) * _env(n, 0.35, 0.4)


def _sine_note(f: float, dur: float, decay: float, harmonics=(1.0, 0.35, 0.15)) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(harmonics))
    return tone * np.exp(-t / decay) * _env(n, 0.005, 0.05)


def _pluck(f: float, dur: float, rng) -> np.ndarray:
    """기타 줄 퉁기는 소리 (Karplus-Strong)."""
    n = int(dur * SR)
    period = max(2, int(SR / f))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(0, n, period):
        k = min(period, n - i)
        out[i:i + k] = buf[:k]
        buf = 0.996 * 0.5 * (buf + np.roll(buf, -1))
    return out * _env(n, 0.002, 0.05)


def _kick(dur=0.35) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 50 + 70 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _noise_hit(dur: float, decay: float, rng, bright: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = rng.uniform(-1, 1, n)
    if bright > 0.5:  # 하이햇: 고음만
        x = x - np.concatenate([[0], x[:-1]])
    return x * np.exp(-t / decay)


def _add(track: np.ndarray, sound: np.ndarray, at: float, gain: float) -> None:
    i = int(at * SR) % len(track)
    k = min(len(sound), len(track) - i)
    track[i:i + k] += sound[:k] * gain
    if k < len(sound):  # 곡 끝을 넘으면 앞쪽으로 이어 붙인다 (반복할 때 자연스럽게)
        rest = sound[k:]
        track[:len(rest)] += rest[:len(track)] * gain


def compose(mood: str = "bright", seconds: float = 60, seed: int | str = 0) -> np.ndarray:
    """(샘플 수, 2) 스테레오 배열. 4마디 단위로 seconds 이상이 되게 만든다."""
    if isinstance(seed, str):
        seed = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    bpm, mode, progs, lead = MOODS.get(mood, MOODS["bright"])
    bpm += int(rng.integers(-4, 5))
    beat = 60 / bpm
    bar = beat * 4
    bars = max(8, int(np.ceil(seconds / bar / 4)) * 4)
    total = bars * bar
    n = int(total * SR)
    scale = MAJOR if mode == "major" else MINOR
    root = 57 + int(rng.choice([0, 2, 3, 5, 7]))  # A3 근처에서 조를 고른다
    prog = progs[int(rng.integers(len(progs)))]

    def chord(degree: int) -> list[int]:
        i = degree - 1
        return [root + scale[(i + k) % 7] + 12 * ((i + k) // 7) for k in (0, 2, 4)]

    pad = np.zeros(n)
    bass = np.zeros(n)
    lead_t = np.zeros(n)
    drums = np.zeros(n)
    swing = 0.04 if mood in ("bright", "calm") else 0.0

    for b in range(bars):
        t0 = b * bar
        notes = chord(prog[b % len(prog)])
        if mood != "funny" or b % 2 == 0:
            _add(pad, _pad([_freq(m) for m in notes], bar * (2 if mood == "funny" else 1), rng),
                 t0, 1.0)
        # 베이스
        bf = _freq(notes[0] - 24)
        pattern = {"bright": [0, 2, 2.5], "calm": [0], "tension": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
                   "funny": [0, 1, 2, 3]}[mood]
        for p in pattern:
            length = beat * (4 if mood == "calm" else 0.9)
            _add(bass, _sine_note(bf, length, 0.6 if mood == "calm" else 0.25, (1.0, 0.25)),
                 t0 + p * beat, 1.0)
        # 멜로디 악기: 화음 음을 돌아가며
        arp = notes + [notes[1] + 12]
        if lead == "pluck":
            for k in range(8):
                if rng.random() < 0.8:
                    f = _freq(arp[int(rng.integers(len(arp)))] + 12)
                    _add(lead_t, _pluck(f, beat * 1.5, rng), t0 + k * beat / 2 + (swing if k % 2 else 0), 0.9)
        elif lead == "piano":
            for k in (0, 1.5, 2, 3) if b % 2 == 0 else (0, 2):
                f = _freq(arp[int(rng.integers(len(arp)))] + 12)
                _add(lead_t, _sine_note(f, beat * 3, 1.2), t0 + k * beat, 0.7)
        elif lead == "pulse":
            for k in range(8):
                f = _freq(notes[k % 3] + 12)
                _add(lead_t, _sine_note(f, beat * 0.45, 0.12, (1.0, 0.5, 0.3, 0.2)), t0 + k * beat / 2, 0.5)
        else:  # bounce: 통통 튀는 짧은 음
            for k in range(8):
                if k % 2 == 0 or rng.random() < 0.5:
                    f = _freq(arp[k % len(arp)] + 12)
                    _add(lead_t, _sine_note(f, beat * 0.3, 0.07, (1.0, 0.6, 0.2)), t0 + k * beat / 2, 0.8)
        # 드럼 (잔잔은 아주 약하게)
        if mood == "calm":
            if b % 2 == 0:
                _add(drums, _kick(), t0, 0.35)
            for k in range(4):
                _add(drums, _noise_hit(0.08, 0.02, rng, 1), t0 + k * beat + beat / 2, 0.05)
            continue
        kicks = {"bright": [0, 2, 2.5], "tension": [0, 1.5, 2, 3.5], "funny": [0, 1, 2, 3]}[mood]
        for p in kicks:
            _add(drums, _kick(), t0 + p * beat, 0.8)
        for p in (1, 3):
            _add(drums, _noise_hit(0.2, 0.06, rng, 0), t0 + p * beat, 0.35)
        for k in range(8):
            _add(drums, _noise_hit(0.06, 0.015, rng, 1), t0 + k * beat / 2 + (swing if k % 2 else 0),
                 0.12 if k % 2 else 0.08)

    pad = lowpass(pad, 1400 if mood != "tension" else 900)
    lead_t = lowpass(lead_t, 4500)
    mix_l = 0.30 * pad + 0.55 * bass + 0.35 * lead_t + 0.45 * drums
    # 오른쪽은 패드와 멜로디를 살짝 늦춰서 넓게 들리게
    shift = int(0.012 * SR)
    mix_r = 0.30 * np.roll(pad, shift) + 0.55 * bass + 0.35 * np.roll(lead_t, shift) + 0.45 * drums
    stereo = np.stack([mix_l, mix_r], axis=1)
    stereo -= stereo.mean(axis=0)
    stereo /= max(np.abs(stereo).max(), 1e-6)
    rms = np.sqrt((stereo ** 2).mean())
    stereo *= min(0.18 / max(rms, 1e-6), 0.95)  # 소리 크기를 일정하게
    return np.clip(stereo, -0.98, 0.98)


def write_wav(path: str, audio: np.ndarray) -> None:
    data = (audio * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def make(path: str, mood: str = "bright", seconds: float = 60, seed: int | str = 0) -> str:
    """배경음악 파일을 만들어 경로를 돌려준다. 이미 같은 곡이 있으면 그대로 쓴다."""
    if not os.path.exists(path):
        tmp = path + ".tmp.wav"
        write_wav(tmp, compose(mood, seconds, seed))
        os.replace(tmp, path)
    return path


def mood_for(guide: str = "", hint: str = "") -> str:
    """영상 종류와 AI가 고른 분위기로 곡 분위기를 정한다."""
    hint = (hint or "").lower()
    for key, name in MOOD_NAMES.items():
        if hint in (key, name):
            return key
    return {"vlog": "bright", "lecture": "tension", "moving": "bright",
            "commerce": "bright", "funny": "funny", "story": "calm",
            "howto": "bright", "workout": "tension"}.get(guide, "bright")
