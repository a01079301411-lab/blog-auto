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

### 업데이트

**`update.bat`을 더블클릭**하면 최신 버전을 받아서 덮어써요. `settings.ini`는 그대로 둬요.

또 `run.bat`을 실행할 때마다 GitHub에서 최신 버전을 확인하고 바뀐 파일만 자동으로 받아와요. 따로 다시 내려받을 필요가 없어요.

- `settings.ini`는 덮어쓰지 않아요.
- 인터넷이 안 되면 업데이트를 건너뛰고 지금 버전으로 실행해요.
- 영상 없이 `run.bat`을 더블클릭하면 업데이트만 해요.

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

## 자동으로 해 주는 것들

`settings.ini`에서 각각 켜고 끌 수 있어요(`yes`/`no`).

| 기능 | 설정 | 설명 |
|---|---|---|
| 얼굴 따라가기 | `focus = auto` | 사람이 움직여도 화면이 얼굴을 부드럽게 따라가요. 숫자를 넣으면 고정 위치 |
| 자막 다듬기 | `fix_subtitles = yes` | Claude가 음성 인식 오타를 문맥으로 고치고, 자연스러운 곳에서 줄을 나눠요 |
| 만들기 전에 고르기 | `review = yes` | 메모장으로 숏폼 목록이 열려요. `[O]`를 `[X]`로 바꾸면 빼고, 제목·문구·구간도 고칠 수 있어요. 저장하고 닫으면 시작해요 |
| 핵심 단어 확대 | `zoom = yes` | 강조 단어가 나올 때 화면을 살짝 확대해요 |
| 효과음 | `sfx = yes` | 확대할 때 '휙' 소리를 넣어요. `sfx` 폴더에 소리 파일을 넣으면 그걸 써요 |
| 배경음악 | `bgm_volume = 0.15` | `bgm` 폴더에 음악 파일을 넣으면 숏폼마다 돌아가며 깔아요. 말할 때는 음악이 자동으로 작아져요 |
| 썸네일 | `thumbnail = yes` | 얼굴이 가장 잘 나온 장면에 제목을 얹은 이미지(`.jpg`)를 만들어요 |
| 유튜브 업로드 | `upload = no` | 아래 설정을 마치면 자동으로 올려요 |

같은 영상을 다시 끌어다 놓으면, 지난번에 고른 하이라이트와 음성 인식 결과를 다시 써서 금방 끝나요. 하이라이트를 새로 고르게 하려면 결과 폴더의 `highlights.json`을 지우세요.

배경음악은 저작권 걱정 없는 곡을 쓰세요. 유튜브 스튜디오 → **오디오 보관함**에서 무료 음악을 받을 수 있어요.

### 유튜브 자동 업로드 설정 (선택)

> **먼저 알아둘 점**: 구글 정책상, 구글 심사를 받지 않은 개인 API 프로젝트로 올린 영상은 **비공개로 고정**돼요. 공개로 바꾸려면 구글에 [심사 신청](https://support.google.com/youtube/contact/yt_api_form)을 해야 해요. 그 전까지는 "비공개로 올려두고 휴대폰 유튜브 앱에서 확인하는 용도"로 쓰거나, 직접 올리는 게 나아요.
>
> 또 하루에 올릴 수 있는 개수가 **약 6개**로 제한돼요. 남은 건 다음 날 다시 실행하면 이어서 올려요.

1. https://console.cloud.google.com 에 접속해 **새 프로젝트**를 만들어요.
2. **API 및 서비스 → 라이브러리**에서 `YouTube Data API v3`를 찾아 **사용**을 눌러요.
3. **OAuth 동의 화면**에서 다음을 해요.
   - 사용자 유형은 **외부**로 골라요.
   - 앱 이름과 이메일을 적어요.
   - **테스트 사용자**에 내 구글 계정을 추가해요.
4. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**로 들어가요.
   - 유형은 **데스크톱 앱**으로 골라요.
   - 만든 뒤 **JSON 다운로드**를 눌러요.
5. 받은 파일 이름을 `client_secret.json`으로 바꿔서 프로그램 폴더(`run.bat`이 있는 곳)에 넣어요.
6. `settings.ini`에서 `upload = private`으로 바꿔요.
7. 처음 실행할 때 브라우저가 열리면, 유튜브 채널의 구글 계정으로 로그인해서 **허용**을 눌러요.
   - "확인되지 않은 앱" 화면이 나오면 **고급 → 이동**을 누르세요.

테스트 모드에서는 로그인이 7일마다 풀려요. 다시 브라우저가 열리면 한 번 더 허용해 주세요.

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
| `--focus auto` | `auto`는 얼굴 따라가기. 숫자를 넣으면 좌우 고정 위치(0은 왼쪽, 1은 오른쪽) |
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
shortform/launcher.py   run.bat 실행기 (업데이트 → 숏폼 만들기)
shortform/update.py     GitHub 자동 업데이트
shortform/
  cli.py          명령줄 인터페이스
  transcribe.py   음성 인식 (faster-whisper, 조각 단위 + 이어하기)
  highlights.py   하이라이트·제목·문구 생성 (Claude API)
  styles.py       디자인 템플릿 (영상 배치, 얼굴 따라가기·확대 필터, ASS 자막)
  face.py         얼굴 인식 (OpenCV YuNet) → 따라가기 경로, 썸네일 장면
  subfix.py       자막 다듬기 (Claude)
  review.py       메모장으로 숏폼 고르기
  youtube.py      유튜브 업로드
  models/         얼굴 인식 모델 (YuNet, MIT 라이선스)
  assets/         기본 효과음
  silence.py      무음 탐지
  subtitles.py    자막 묶기, 컷 편집 후 시간 재계산
  media.py        FFmpeg 렌더링
```
