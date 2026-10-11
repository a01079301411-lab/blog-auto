"""faster-whisper로 음성 인식 (단어 단위 타임스탬프 포함)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

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

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"sentences": [asdict(s) for s in self.sentences],
                       "words": [asdict(w) for w in self.words]},
                      f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "Transcript":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls([Sentence(**s) for s in data["sentences"]],
                   [Word(**w) for w in data["words"]])


def transcribe(
    path: str,
    *,
    model: str = "small",
    language: str | None = "ko",
    cache: str | None = None,
) -> Transcript:
    """영상의 음성을 텍스트로 변환한다. cache 경로가 있으면 결과를 재사용한다."""
    if cache and os.path.exists(cache):
        print(f"  기존 음성 인식 결과 사용: {cache}")
        return Transcript.load(cache)

    from faster_whisper import WhisperModel  # 무거운 import는 필요할 때만

    whisper = WhisperModel(model, device="auto", compute_type="auto")
    segments, info = whisper.transcribe(
        path, language=language, word_timestamps=True, vad_filter=True,
    )
    sentences: list[Sentence] = []
    words: list[Word] = []
    for seg in segments:  # 제너레이터: 순회하면서 인식이 진행된다
        sentences.append(Sentence(seg.start, seg.end, seg.text.strip()))
        words.extend(Word(w.start, w.end, w.word) for w in seg.words or [])
        print(f"\r  인식 중... {seg.end:7.1f}s / {info.duration:.1f}s", end="", flush=True)
    print()

    result = Transcript(sentences, words)
    if cache:
        result.save(cache)
    return result
