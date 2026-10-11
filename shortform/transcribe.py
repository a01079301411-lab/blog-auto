"""faster-whisper로 음성 인식 (단어 단위 타임스탬프 포함).

긴 영상은 오디오 전체를 한 번에 메모리에 올리지 않도록 약 10분 단위
(가능하면 무음 지점에서) 조각으로 나눠 인식한다. 조각마다 결과를 저장하므로
중간에 멈춰도 다시 실행하면 이어서 진행한다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import warnings
import wave
from dataclasses import asdict, dataclass

import numpy as np

from . import media
from .silence import detect_silences, split_points
from .subtitles import Word


@dataclass
class Sentence:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    sentences: list[Sentence]
    words: list[Word]
    language: str | None = None

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"language": self.language,
                       "sentences": [asdict(s) for s in self.sentences],
                       "words": [asdict(w) for w in self.words]},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)  # 쓰다가 중단돼도 깨진 파일이 남지 않게

    @classmethod
    def load(cls, path: str) -> "Transcript":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls([Sentence(**s) for s in data["sentences"]],
                   [Word(**w) for w in data["words"]],
                   data.get("language"))


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}"


def _extract_audio(src: str, start: float, end: float, out: str) -> None:
    media.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src,
               "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out])


def _read_wav(path: str) -> np.ndarray:
    """16kHz 모노 16비트 WAV → Whisper가 받는 float32 배열."""
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def _load_model(model: str, device: str):
    # Windows에서 모델을 내려받을 때 나오는 영어 경고(심볼릭 링크, 비로그인 다운로드)는
    # 동작에 문제가 없으므로 숨긴다
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    warnings.filterwarnings("ignore", module="huggingface_hub")

    from faster_whisper import WhisperModel  # 무거운 import는 필요할 때만

    print(f"  Whisper 모델 불러오는 중: {model} (처음엔 모델 내려받기로 몇 분 걸려요)", flush=True)
    try:
        return WhisperModel(model, device=device,
                            compute_type="int8" if device == "cpu" else "auto")
    except Exception as e:
        raise RuntimeError(
            f"Whisper 모델 '{model}'을 불러오지 못했습니다. 첫 실행 때는 모델을 "
            f"내려받으므로 인터넷 연결이 필요해요.\n  ({type(e).__name__}: {e})"
        ) from e


def _transcribe_chunk(whisper, path: str, s: float, e: float,
                      language: str | None, label: str) -> Transcript:
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "chunk.wav")
        _extract_audio(path, s, e, wav)
        # 파일 경로 대신 오디오 데이터를 넘긴다. 경로를 주면 faster-whisper가 PyAV로
        # 파일을 여는데, PyAV 16 이상과 faster-whisper 1.2.1이 서로 맞지 않아 실패한다
        segs, info = whisper.transcribe(
            _read_wav(wav), language=language, word_timestamps=True, vad_filter=True)
        chunk = Transcript([], [], info.language)
        for seg in segs:  # 제너레이터: 순회하면서 인식이 진행된다
            chunk.sentences.append(Sentence(seg.start + s, seg.end + s, seg.text.strip()))
            chunk.words.extend(Word(w.start + s, w.end + s, w.word) for w in seg.words or [])
            print(f"\r{label}  {_fmt(seg.end + s)}", end="", flush=True)
    return chunk


def transcribe(
    path: str,
    *,
    model: str = "small",
    language: str | None = "ko",
    cache: str | None = None,
    chunk_minutes: float = 10,
    device: str = "auto",
) -> Transcript:
    """영상의 음성을 텍스트로 변환한다. cache 경로가 있으면 결과를 재사용한다."""
    if cache and os.path.exists(cache):
        print(f"  기존 음성 인식 결과 사용: {cache}")
        return Transcript.load(cache)

    total = media.duration(path)
    chunk_len = chunk_minutes * 60
    if total > chunk_len * 1.5:
        print("  긴 영상이라 무음 지점을 기준으로 나눠서 인식합니다.")
        print(f"  오디오 전체를 훑는 중... (영상 {_fmt(total)} 기준 몇 분 걸려요. "
              "화면이 멈춰 보여도 진행 중이에요)", flush=True)
        cuts = split_points(detect_silences(path, min_silence=0.3), total, chunk_len)
    else:
        cuts = []
    bounds = list(zip([0.0] + cuts, cuts + [total]))

    parts_dir = (cache or os.path.join(tempfile.gettempdir(), "shortform")) + ".parts"
    os.makedirs(parts_dir, exist_ok=True)

    whisper = None
    sentences: list[Sentence] = []
    words: list[Word] = []
    began = time.time()
    done_secs = 0.0  # 이번 실행에서 실제로 인식한 길이 (남은 시간 예측용)
    for i, (s, e) in enumerate(bounds, 1):
        part = os.path.join(parts_dir, f"{i:04}_{s:.2f}_{e:.2f}.json")
        label = f"  [{i}/{len(bounds)}] {_fmt(s)} ~ {_fmt(e)}"
        if os.path.exists(part):
            chunk = Transcript.load(part)
            print(f"{label} (저장된 결과 사용)")
        else:
            for attempt in range(2):
                if whisper is None:
                    whisper = _load_model(model, device)
                try:
                    chunk = _transcribe_chunk(whisper, path, s, e, language, label)
                    break
                except RuntimeError as err:
                    # NVIDIA 그래픽카드는 있는데 CUDA 라이브러리가 없으면 여기서 실패한다
                    msg = str(err).lower()
                    if attempt or device == "cpu" or not any(
                            k in msg for k in ("cuda", "cublas", "cudnn")):
                        raise
                    print(f"\n  GPU를 쓸 수 없어 CPU로 바꿔서 다시 시도합니다 ({err})")
                    device, whisper = "cpu", None
            chunk.save(part)
            done_secs += e - s
            remaining = sum(b - a for a, b in bounds[i:])
            eta = (time.time() - began) / done_secs * remaining
            print(f"\r{label}  완료 (남은 예상 시간 {_fmt(eta)})")
        if language is None and chunk.language:
            language = chunk.language  # 첫 조각에서 감지한 언어를 계속 사용
        sentences += chunk.sentences
        words += chunk.words

    result = Transcript(sentences, words, language)
    if cache:
        result.save(cache)
        shutil.rmtree(parts_dir, ignore_errors=True)
    return result
