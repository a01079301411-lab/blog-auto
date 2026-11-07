# homework_kit — COSY 숙제 프로그램

COSY 가이드 스크린샷과 양식 xlsx를 넣으면 프로그램이 숙제를 끝까지 합니다. 가이드 학습 → 최신순 레퍼런스 실측 → 빈칸 없이 작성 → 렌더 확인 → 자체 검증 → 성민용 보고서 순서입니다.
성민은 `보고서.md`를 보고 학습한 뒤, 결과 xlsx를 COSY에 제출하면 됩니다.

## 1. 구조: 수집은 성민 PC, 작성은 어디서든 (SOLUTION_차단문제해결.md)
인스타는 로그인 없이는 수치를 안 보여주고, 유튜브는 클라우드 서버를 로봇으로 막습니다. 그래서 **실측 수집만 성민 PC(가정용 인터넷 + 성민이 직접 로그인한 브라우저)**에서 하고, 프로그램은 그 결과(`collector/results.json`)만 씁니다. 결과에 없는 수치는 절대 추정하지 않습니다.

```
[1단계] hw.py plan   가이드 → 레퍼런스 후보·계정·랜딩 링크 → collector/urls_퀘스트.txt
[2단계] 성민 PC      collector.py collect → collector/results.json + collector/shots/(0.5초 후킹·표지 캡처)
[3단계] hw.py run    results.json 실측만으로 양식 작성 → 검증 → 렌더 → 보고서
                     실측이 빠진 링크는 collector/missing_urls_퀘스트.txt → 2단계 재실행
```

## 2. 성민 PC 준비 (한 번)
```bash
pip install -r requirements.txt
```
```bash
pip install -r collector/requirements.txt
```
```bash
python -m playwright install chromium
```
```bash
python collector/collector.py login
```
```bash
python collector/collector.py check
```
- `login`: 열린 창에서 인스타(필수)·유튜브·틱톡에 **직접** 로그인한 뒤 각각 Enter. 로그인은 `collector/browser_profile/`에만 남고 git에 올라가지 않습니다
- `check`: 인스타·유튜브·틱톡에 실제 요청 1건씩 → OK 또는 실패 원인
- 읽기만 합니다(좋아요·댓글·팔로우·DM 없음). 요청 사이 6~10초, 한 번에 50건 이하, 인스타가 '이상 활동' 경고를 띄우면 즉시 중단하고 24시간 쉽니다
- (선택) 유튜브 공식 API 키를 `YOUTUBE_API_KEY`에 넣으면 유튜브 페이지 방식이 실패할 때 자동으로 씁니다

## 3. 숙제 시키기 (3-1-1 예시)
```bash
python hw.py plan --quest 3-1-1 --guide docs\3-1-1_퀘스트가이드.md
```
```bash
python collector/collector.py collect collector/urls_3-1-1.txt collector/results.json
```
```bash
python hw.py run --quest 3-1-1 --guide docs\3-1-1_퀘스트가이드.md
```
- `plan`·`run`은 Claude API(`ANTHROPIC_API_KEY`)를 씁니다. **Claude Code를 PC에서 실행하면** 세 단계를 Claude Code에 맡길 수도 있습니다
- 수집 결과(`results.json`, `shots/`)를 git에 커밋·푸시하면 클라우드 세션에서도 3단계를 할 수 있습니다
- `python hw.py results --quest 3-1-1`: 수집 성공·실패, 3일 넘은 수치, 양식 지정 레퍼런스 수집 여부
- `run`은 시작할 때 3일 넘은 수치를 경고하고, 데이터 행의 SNS 링크가 results.json에 없으면 검증 실패로 처리합니다

결과는 `output/{퀘스트}_{날짜시각}/`에 생깁니다: `{퀘스트}_{내용}_성민.xlsx`, `보고서.md`(성민 할 일·가이드 분석·배울 점·칸별 내용·출처와 수집 시각·수집 필요 목록), `render/*.png`, `log.jsonl`

## 3-1. 보조 명령
```bash
python hw.py inspect 양식.xlsx
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

## 4. 프로그램이 지키는 규칙 (HOMEWORK_SPEC.md 그대로)
- 빈칸 0. '없음/모름/안됨/부족함'으로 칸을 때우면 검증 실패. 문장 안의 근거 서술("링크가 없음")은 통과본 기준대로 허용
- 금지 표현: 재밌어서, 알고리즘 탄 듯, 퀄리티 좋음, 무료임, 다들 쓰니까 괜찮을 듯
- 수치는 results.json(성민 PC 실측)에서만: 1만 이상 '3.4만', 미만 '9,627'. 평소 대비는 계정 수집 결과에서 고정·대상 게시물을 빼고 최근 5~10개 평균 대비 배수
- 모든 수치에 출처 링크와 수집 시각을 연결하고, 없는 수치는 추정하지 않고 수집 필요 목록으로 넘김
- 후킹은 shots/의 0.5초 캡처를 보고 화면 자막 그대로 인용(없으면 '캡처 필요'). 라이선스·정책은 공식 페이지를 직접 확인
- 양식에 이미 들어 있는 1번 지정 레퍼런스는 바꾸지 않음. 드롭다운은 목록 값 그대로
- 검증에 실패하면 AI가 스스로 고쳐서 다시 제출하고, 통과하면 렌더 이미지까지 보고 마무리
- 업로드·앱 화면 확인·캡처·COSY 제출은 성민이 직접 함 → 보고서 1장에 순서대로 정리

## 5. 폴더 구성
- `hw.py`, `cosyhw/`: 프로그램 (template 양식 분석 · metrics results.json 읽기 · agent Claude 루프(plan/run) · writer 작성 · checks 검증 · render 렌더 · report 보고서)
- `collector/`: 성민 PC 전용 수집기(collector.py, 정식 크롬 + 직접 로그인한 전용 프로필). `browser_profile/`은 절대 공유·커밋 금지
- `SOLUTION_차단문제해결.md`: 클라우드 차단 원인과 2단 구조 설계
- `HOMEWORK_SPEC.md`: 마스터 스펙. 프로그램 시스템 프롬프트에 그대로 들어감
- `quests.json`: 퀘스트별 양식 셀 맵 · `templates/`: COSY 원본 양식 · `submitted/`: 실제 제출본 + `submitted_cells.json`(말투·길이 예시로 사용)
- `scripts/`: 예전 퀘스트를 손으로 채운 스크립트. `2-1 q1q2`는 인자 4개를 `2-1_q2_template.xlsx 2-1_q1_template.xlsx 결과_q2.xlsx 결과_q1.xlsx` 순서로 넣어야 함 (q1·q2 순서를 바꾸면 MergedCell 오류)
- `docs/`: 회사·퀘스트 부가자료
- `tests/test_offline.py`: API 없이 돌리는 테스트 (`python tests/test_offline.py`)

## 6. 비용
기본 모델은 claude-opus-5-5, effort는 high입니다. 웹 검색은 최대 60회, 웹 페치는 최대 80회까지 씁니다. 퀘스트 1개(레퍼런스 9~20개)에 보통 수십만 토큰이 들고, 끝나면 사용량이 화면에 표시됩니다. 거절 응답이 오면 서버 측 대체 모델(`fallbacks: "default"`)로 자동 재시도합니다.
