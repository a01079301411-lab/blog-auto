# homework_kit — COSY 숙제 프로그램

COSY 가이드 스크린샷과 양식 xlsx를 넣으면 프로그램이 숙제를 끝까지 합니다. 가이드 학습 → 최신순 레퍼런스 실측 → 빈칸 없이 작성 → 렌더 확인 → 자체 검증 → 성민용 보고서 순서입니다.
성민은 `보고서.md`를 보고 학습한 뒤, 결과 xlsx를 COSY에 제출하면 됩니다.

## 1. 처음 한 번만 설치 (Windows 기준)
```bash
pip install -r requirements.txt
```
- **Claude API 키**: 환경변수 `ANTHROPIC_API_KEY` 설정 (또는 `ant auth login`)
- **LibreOffice**: 렌더(잘림 확인)용. 기본 설치 경로는 자동으로 찾음. 다른 경로면 `SOFFICE` 환경변수에 지정
- **ffmpeg**: 후킹 0.5초 프레임 캡처용 (PATH 등록)
- **인스타 실측(선택)**: 크롬에서 instagram.com 로그인 → 개발자도구 → 쿠키 `sessionid` 값을 `IG_SESSIONID` 환경변수에 넣기. 프로그램은 GET 조회만 하고 좋아요·댓글·팔로우는 하지 않음

## 2. 숙제 시키기
```bash
python hw.py run --quest 2-4-q1 --template "C:\Users\...\Downloads\2-4_양식.xlsx" --guide "C:\Users\...\Downloads\가이드\*.png"
```
- `--guide`: 가이드 스크린샷을 여러 장 넣거나 폴더째로 지정 (png/jpg/pdf/md/txt)
- `--note "인스타 위주로, 육아템 중심"`: 추가 지시
- `--effort xhigh`: 더 꼼꼼하게 (기본 high)
- `--dry-run`: API 호출 없이 프로그램이 이해한 양식·지시만 출력
- 이미 등록된 퀘스트(`python hw.py list`)는 `--template`를 생략해도 됨

결과는 `output/{퀘스트}_{날짜시각}/` 폴더에 생깁니다.
| 파일 | 내용 |
|---|---|
| `{퀘스트}_{내용}_성민.xlsx` | 제출할 완성본 |
| `보고서.md` | 성민 할 일, 가이드 분석, 배울 점, 칸별 작성 내용, 출처·실측 기록, 미확인 항목 |
| `render/*.png` | 양식 렌더 미리보기 |
| `log.jsonl` | 수집·검증 전 과정 기록 |

새 퀘스트는 끝나면 자동으로 `quests.json`에 등록되고, 템플릿은 `templates/`로, 가이드 분석은 `docs/퀘스트_자동학습.md`로 쌓입니다. 다음 퀘스트부터는 이 학습 내용도 같이 참고합니다.

## 3. 보조 명령
```bash
python hw.py inspect 양식.xlsx
```
```bash
python hw.py collect https://www.youtube.com/watch?v=znj8v8XY5js https://www.tiktok.com/@계정/video/123
```
```bash
python hw.py check 결과.xlsx --template 양식.xlsx
```
```bash
python hw.py fill --template 양식.xlsx --cells cells.json --out 결과.xlsx
```
```bash
python hw.py render 결과.xlsx
```
- `inspect`: 이름·작성일 칸, 데이터 행, 최종 칸, 드롭다운, 채워야 할 빈칸 목록
- `collect`: 유튜브·틱톡·인스타 실측 수치(JSON)
- `check`: 빈칸·금지 표현·드롭다운·이름·날짜·수치 형식 검증
- `fill`: 직접 고친 cells.json(`{"D12":"값"}`)을 AI 없이 다시 채우기

## 4. 프로그램이 지키는 규칙 (HOMEWORK_SPEC.md 그대로)
- 빈칸 0. '없음/모름/안됨/부족함'으로 칸을 때우면 검증 실패. 문장 안의 근거 서술("링크가 없음")은 통과본 기준대로 허용
- 금지 표현: 재밌어서, 알고리즘 탄 듯, 퀄리티 좋음, 무료임, 다들 쓰니까 괜찮을 듯
- 수치는 원본에서 실측: 1만 이상 '3.4만', 미만 '9,627'. 평소 대비는 최근 5~10개 평균 대비 배수로 계산
- 후킹은 0.5초 프레임을 직접 보고 인용. 라이선스·정책은 공식 페이지를 직접 확인
- 양식에 이미 들어 있는 1번 지정 레퍼런스는 바꾸지 않음. 드롭다운은 목록 값 그대로
- 검증에 실패하면 AI가 스스로 고쳐서 다시 제출하고, 통과하면 렌더 이미지까지 보고 마무리
- 업로드·앱 화면 확인·캡처·COSY 제출은 성민이 직접 함 → 보고서 1장에 순서대로 정리

## 5. 폴더 구성
- `hw.py`, `cosyhw/`: 프로그램 (template 양식 분석 · collectors 실측 · agent Claude 루프 · writer 작성 · checks 검증 · render 렌더 · report 보고서)
- `HOMEWORK_SPEC.md`: 마스터 스펙. 프로그램 시스템 프롬프트에 그대로 들어감
- `quests.json`: 퀘스트별 양식 셀 맵 · `templates/`: COSY 원본 양식 · `submitted/`: 실제 제출본 + `submitted_cells.json`(말투·길이 예시로 사용)
- `scripts/`: 예전 퀘스트를 손으로 채운 스크립트. `2-1 q1q2`는 인자 4개를 `2-1_q2_template.xlsx 2-1_q1_template.xlsx 결과_q2.xlsx 결과_q1.xlsx` 순서로 넣어야 함 (q1·q2 순서를 바꾸면 MergedCell 오류)
- `docs/`: 회사·퀘스트 부가자료
- `tests/test_offline.py`: API 없이 돌리는 테스트 (`python tests/test_offline.py`)

## 6. 비용
기본 모델은 claude-opus-5-5, effort는 high입니다. 웹 검색은 최대 60회, 웹 페치는 최대 80회까지 씁니다. 퀘스트 1개(레퍼런스 9~20개)에 보통 수십만 토큰이 들고, 끝나면 사용량이 화면에 표시됩니다. 거절 응답이 오면 서버 측 대체 모델(`fallbacks: "default"`)로 자동 재시도합니다.
