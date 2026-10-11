# blog-auto

## shortform: 롱폼 영상 → 숏폼 자동 편집기

긴 영상을 넣으면 다음 작업을 자동으로 해요.

1. **자동 자막**: Whisper(faster-whisper)로 음성을 인식하고 단어 단위 타이밍으로 자막을 만들어요.
2. **하이라이트 선정**: 대본을 Claude에게 보내서 숏폼으로 쓰기 좋은 구간을 골라요.
3. **무음 구간 제거**: FFmpeg `silencedetect`로 말 없는 부분을 잘라 템포를 빠르게 만들어요.
4. **세로 숏폼 렌더링**: 1080x1920 영상에 자막을 입혀서 저장해요.

### 설치

```bash
# FFmpeg 필요 (Windows: winget install ffmpeg / macOS: brew install ffmpeg)
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # 하이라이트 자동 선정에만 필요
```

### 사용법

```bash
# 하이라이트 숏폼 3개 만들기 (자막 + 무음 제거 + 세로 화면)
python -m shortform shorts video.mp4 -o shorts_out -n 3

# 구간을 직접 지정 (AI 안 씀)
python -m shortform shorts video.mp4 --ranges "1:20-2:05,10:00-10:40"

# 영상 전체의 무음만 잘라내기
python -m shortform silence video.mp4 -o video_cut.mp4

# 자막(SRT)만 만들기 / 영상에 입히기
python -m shortform subtitle video.mp4 --burn video_sub.mp4
```

자주 쓰는 옵션:

| 옵션 | 설명 |
|---|---|
| `--layout blur\|crop\|original` | blur: 흐린 배경 위에 원본 영상 (기본값) / crop: 가운데를 잘라 화면 꽉 채움 |
| `--model small` | Whisper 모델. `medium`이나 `large-v3`가 더 정확하지만 느려요 |
| `--font "NanumGothic"` | 자막 폰트 (한글 폰트 권장) |
| `--noise -35 --min-silence 0.5` | 무음 판단 기준. 배경음이 있는 영상이면 `--noise -30` 정도로 올려 보세요 |
| `--padding 0.15` | 자른 부분 앞뒤에 남길 여유. 말이 뚝뚝 끊기면 늘려 보세요 |
| `--min-len 20 --max-len 60` | 숏폼 길이 범위(초) |

음성 인식 결과는 `출력폴더/<영상이름>.<모델>.transcript.json`에 저장되고, 다시 실행하면 재사용해요.

### 구조

```
shortform/
  cli.py          명령줄 인터페이스
  transcribe.py   음성 인식 (faster-whisper)
  highlights.py   하이라이트 선정 (Claude API)
  silence.py      무음 탐지 → 남길 구간 계산
  subtitles.py    자막 묶기, 컷 편집 후 시간 재계산, SRT 저장
  media.py        FFmpeg 렌더링 (구간 이어붙이기, 세로 레이아웃, 자막 입히기)
```
