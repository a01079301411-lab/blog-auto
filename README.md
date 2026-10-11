# blog-auto

## shortform: 롱폼 영상 → 숏폼 자동 편집기

긴 영상을 넣으면 다음 작업을 자동으로 해요.

1. **자동 자막**: Whisper로 음성을 인식하고 단어 단위 타이밍으로 자막을 만들어요.
2. **하이라이트 선정**: 대본을 Claude에게 보내 숏폼으로 쓰기 좋은 구간을 골라요. 제목, 강조 단어, 인물 소개, 하단 문구, 업로드 설명도 같이 만들어요.
3. **무음 구간 제거**: 말 없는 부분을 잘라 템포를 빠르게 만들어요.
4. **세로 숏폼 렌더링**: 레퍼런스 템플릿 디자인으로 1080x1920 영상을 만들어요.

---

## Windows 설치 (처음 한 번만)

### 1. 프로그램 내려받기

1. https://github.com/a01079301411-lab/blog-auto 에 접속해요.
2. 왼쪽 위 브랜치 선택에서 `claude/ecstatic-lamport-5i53ft`를 고르고, 초록색 **Code → Download ZIP**을 눌러요.
3. 압축을 풀어서 원하는 곳(예: `C:\shortform`)에 둬요.

### 2. install.bat 실행

압축 푼 폴더의 **`install.bat`을 더블클릭**해요. 이 파일이 다음을 자동으로 해요.

- Python과 FFmpeg이 없으면 설치해요 (Windows 기본 `winget` 사용).
- 필요한 파이썬 패키지를 설치해요.
- Claude API 키를 물어보고 저장해요.

> Python이나 FFmpeg을 새로 설치했다면 창을 닫고 `install.bat`을 **한 번 더** 실행해야 해요.
>
> "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.

**Claude API 키**는 https://console.anthropic.com 에서 가입한 뒤 **API Keys → Create Key**로 만들어요. 결제 수단 등록이 필요해요. 1시간 영상 한 편을 분석하는 데 몇백 원 정도 들어요.

### 3. 글꼴 (선택)

기본 글꼴은 Windows에 있는 **맑은 고딕(굵게)**이에요. 레퍼런스처럼 더 굵고 임팩트 있는 글꼴을 쓰려면 무료 글꼴을 설치하세요.

- G마켓 산스: https://corp.gmarket.com/fonts
- Pretendard: https://github.com/orioncactus/pretendard/releases

설치한 뒤 스타일 파일에 `"font": "Gmarket Sans TTF Bold"`처럼 글꼴 이름을 적으면 돼요.

### 수동 설치 (install.bat이 안 될 때)

1. https://www.python.org/downloads/ 에서 Python을 설치해요. 설치 첫 화면에서 **"Add python.exe to PATH" 체크**를 꼭 해야 해요.
2. 명령 프롬프트(cmd)에서 아래를 실행해요.
   ```bat
   winget install Gyan.FFmpeg
   cd C:\shortform
   python -m pip install -r requirements.txt
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
3. cmd 창을 닫았다가 다시 열어요.

---

## 사용법

### 가장 쉬운 방법: 끌어다 놓기

**영상 파일을 `run.bat` 위로 끌어다 놓으면** 끝이에요. 다 되면 결과 폴더(`영상이름_shorts`)가 자동으로 열려요.

설정은 **`settings.ini`를 메모장으로 열어서** 바꾸면 돼요.

```ini
style = green
count = 7
context = 꼴통사장 권기준 대표의 사업 강의. 창업, 매출, 사장 마인드, 크리에이터로 돈 버는 법
speaker = 권기준 / 꼴통사장 대표
focus = 0.5
model = small
```

### 결과물

숏폼마다 파일이 세 개씩 나와요.

- `01_제목.mp4`: 완성된 숏폼
- `01_제목.txt`: 제목, 알약 문구, 인물, 하단 문구, **업로드 설명과 해시태그**, 원본 구간, 선정 이유
- `01_제목.ass`: 자막 파일. 메모장으로 고칠 수 있어요.

### 명령어로 쓰기

```bat
:: 하이라이트 숏폼 7개
python -m shortform shorts 영상.mp4 -n 7 --style green --context "영상 설명"

:: 구간과 제목을 직접 지정 (AI 안 씀). /로 줄 바꿈, {}로 강조
python -m shortform shorts 영상.mp4 --ranges "12:30-13:15=사장님 속터지는/{진상 직원}의 한마디"

:: 영상 전체의 무음만 잘라내기
python -m shortform silence 영상.mp4

:: 자막(SRT)만 만들기
python -m shortform subtitle 영상.mp4
```

---

## 디자인 (스타일)

| 스타일 | 모양 |
|---|---|
| `green` (기본) | 검은 배경. 위에 제목(첫 줄 작게, 강조는 초록), 가운데 확대 영상, 영상 안 노란 `[인물 소개]`와 말자막, 맨 아래 초록 `<반응 문구>` |
| `magenta` | 위와 같고 강조가 분홍색, 하단 문구 없음 |
| `overlay` | 영상이 화면 전체. 위에 보라색 알약 문구와 굵은 테두리 제목 |
| `basic` | 16:9 영상 전체가 보이고, 위 제목과 아래 자막 |

### 내 스타일 만들기 (제작 가이드에 맞추기)

```bat
python -m shortform style green > 내스타일.json
```

`내스타일.json`을 메모장으로 열어 숫자와 색을 바꾸고 `--style 내스타일.json`으로 쓰면 돼요. 바꿀 항목만 남겨도 돼요.

```json
{
  "base": "green",
  "font": "Gmarket Sans TTF Bold",
  "title_highlight": "#FF3B30",
  "video_top": 480,
  "sub_size": 80
}
```

좌표는 1080x1920 화면 기준 픽셀이에요. 주요 항목은 이래요.

- `video_top`, `video_height`: 영상 상자의 위치와 높이
- `title_*`: 제목 크기, 색, 강조색, 위치
- `speaker_*`: 노란 인물 소개 줄
- `sub_*`: 말자막
- `bottom_*`: 하단 반응 문구
- `label_*`: 알약 문구

---

## 옵션

| 옵션 | 설명 |
|---|---|
| `--style` | 디자인 (위 표 참고) |
| `--context "..."` | 영상 설명. 하이라이트와 제목이 더 정확해져요 |
| `--speaker "..."` | 인물 소개 문구 고정 |
| `--focus 0.5` | 영상을 확대해서 좌우를 자를 때 남길 위치. 0은 왼쪽, 1은 오른쪽. 말하는 사람이 왼쪽에 있으면 `0.3` |
| `-n 7` | 숏폼 개수 |
| `--min-len 20 --max-len 60` | 숏폼 길이 범위(초) |
| `--model small` | 음성 인식 모델. `medium`, `large-v3`가 더 정확하지만 느려요 |
| `--noise -35 --min-silence 0.5` | 무음 판단 기준. 배경음악이 있으면 `--noise -30` |
| `--padding 0.15` | 자른 부분 앞뒤에 남길 여유. 말이 뚝뚝 끊기면 늘리세요 |
| `--device cpu` | GPU 문제가 생길 때 CPU로 강제 |

---

## 긴 영상 (몇 시간짜리)

- **음성 인식**: 약 10분 단위로, 가능하면 무음 지점에서 잘라 인식하고 남은 예상 시간을 보여줘요.
- **이어하기**: 중간에 멈추거나 `Ctrl+C`로 끊어도, **같은 명령을 다시 실행하면 끝난 부분부터 이어서** 해요.
- **재사용**: 음성 인식 결과는 저장돼요. 개수나 스타일만 바꿔 다시 돌리면 금방 끝나요.
- **걸리는 시간**: CPU만 쓰면 음성 인식에 영상 길이의 1/3에서 2/3 정도 걸려요. NVIDIA GPU가 있으면 자동으로 쓰고, 안 되면 알아서 CPU로 바꿔요.

## 구조

```
install.bat / run.bat   Windows 설치·실행
settings.ini            run.bat 설정
shortform/
  cli.py          명령줄 인터페이스
  transcribe.py   음성 인식 (faster-whisper, 조각 단위 + 이어하기)
  highlights.py   하이라이트·제목·문구 생성 (Claude API)
  styles.py       디자인 템플릿 (영상 배치 + ASS 자막)
  silence.py      무음 탐지
  subtitles.py    자막 묶기, 컷 편집 후 시간 재계산
  media.py        FFmpeg 렌더링
```
