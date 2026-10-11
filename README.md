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
# 하이라이트 숏폼 5개 만들기 (상단 제목 + 키워드 강조 자막 + 무음 제거 + 세로 화면)
python -m shortform shorts video.mp4 -o shorts_out -n 5 \
  --context "꼴통사장 권기준의 사업 강의. 창업, 매출, 사장 마인드에 대한 이야기"

# 구간과 제목을 직접 지정 (AI 안 씀). '/'로 제목 두 줄을 나눠요
python -m shortform shorts video.mp4 --ranges "1:20-2:05=망하는 사장들의/공통점 1가지,10:00-10:40"

# 영상 전체의 무음만 잘라내기
python -m shortform silence video.mp4 -o video_cut.mp4

# 자막(SRT)만 만들기 / 영상에 입히기
python -m shortform subtitle video.mp4 --burn video_sub.mp4
```

자주 쓰는 옵션:

| 옵션 | 설명 |
|---|---|
| `--context "..."` | 영상 설명 (누가, 무슨 내용인지). 하이라이트와 제목이 더 정확해져요 |
| `--layout title\|blur\|crop\|original` | title: 검은 배경 + 위 제목 + 아래 자막 (기본값) / blur: 같은 구성에 흐린 배경 / crop: 가운데를 잘라 화면 꽉 채움 |
| `--model small` | Whisper 모델. `medium`이나 `large-v3`가 더 정확하지만 느려요 |
| `--font "NanumGothic"` | 자막 폰트 (기본: Windows는 맑은 고딕) |
| `--noise -35 --min-silence 0.5` | 무음 판단 기준. 배경음이 있는 영상이면 `--noise -30` 정도로 올려 보세요 |
| `--padding 0.15` | 자른 부분 앞뒤에 남길 여유. 말이 뚝뚝 끊기면 늘려 보세요 |
| `--min-len 20 --max-len 60` | 숏폼 길이 범위(초) |

숏폼마다 결과물이 이렇게 나와요.

- `01_제목.mp4`: 완성된 숏폼 영상
- `01_제목.txt`: 제목, 업로드 설명과 해시태그, 원본 구간, 선정 이유
- `01_제목.ass`: 자막 파일 (직접 고쳐서 다시 입힐 수 있어요)

음성 인식 결과는 `출력폴더/<영상이름>.<모델>.transcript.json`에 저장되고, 다시 실행하면 재사용해요.

### 아주 긴 영상 (몇 시간짜리)

몇 시간짜리 영상도 처리할 수 있게 작업을 조각 단위로 나눠서 해요.

- **음성 인식**: 약 10분 단위로, 가능하면 무음 지점에서 잘라서 인식해요. 오디오 전체를 메모리에 올리지 않고, 남은 예상 시간도 보여줘요.
- **무음 제거 렌더링**: 몇 분 단위 조각으로 나눠 렌더링한 뒤 이어붙여요. 조각 수천 개를 한 번에 처리하는 것보다 훨씬 빨라요.
- **이어하기**: 끝난 조각은 저장해 둬요. 중간에 멈추거나 `Ctrl+C`로 끊어도 **같은 명령을 다시 실행하면 이어서** 진행해요.
- **하이라이트 선정**: 대본이 아주 길면(대략 10시간 이상) 나눠서 분석한 뒤 점수가 높은 순서로 골라요.

참고로 걸리는 시간은 대략 이 정도예요.

- 음성 인식이 가장 오래 걸려요. CPU에서 `small` 모델은 영상 길이의 절반 정도 걸릴 수 있어요. NVIDIA GPU가 있으면 자동으로 사용해서 훨씬 빨라요.
- 처음엔 `--model small`로 결과를 확인해 보세요. 자막 품질이 아쉬우면 `medium`이나 `large-v3`로 바꾸면 돼요. 모델마다 결과 파일을 따로 저장해요.
- 2~3시간 영상이면 `-n 10`처럼 숏폼 개수를 넉넉히 뽑아 보세요.

```bash
# 3시간 영상에서 숏폼 10개
python -m shortform shorts long_video.mp4 -o shorts_out -n 10
```

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
