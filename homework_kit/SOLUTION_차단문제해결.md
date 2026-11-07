# 숙제 프로그램 차단 문제 분석 + 해결 설계 (코드 세션에 그대로 전달)
# 작성 2026-11-07 · 대상: 3-1-1처럼 레퍼런스 실측이 필요한 모든 퀘스트

## 1. 문제 진단 — "프로그램이 어디서 접속하느냐"가 원인
| 보고된 문제 | 진짜 원인 | 증거 |
|---|---|---|
| 인스타 로그인 벽 | 클라우드 서버는 성민 로그인이 없음 | 2026-11-07 성민 노트북 크롬(로그인 상태)에서 같은 방식 요청 → salim_station 릴스 조회 2,452,198 / 좋아요 16,385 정상 수신 |
| 유튜브 로봇 차단(/sorry) | 데이터센터 IP를 구글이 봇으로 분류 | 같은 날 노트북 크롬에서 /watch?v=znj8v8XY5js 요청 → 조회 963,701 정상 수신 |
| 시간 두고 재시도해도 반복 | IP 성격이 안 바뀌기 때문 | — |
| 로그인 정보 넣을 방법 없음 | 쿠키를 서버로 옮기려 했기 때문 | 로그인을 '옮기는' 게 아니라 '로그인된 PC에서 실행'하면 불필요 |
| 우회 금지 | 맞음. 우회로 얻은 인스타 2건은 폐기하고 재측정 | — |

결론: 수집 단계만 성민 PC(가정용 인터넷 + 본인이 직접 로그인한 브라우저)에서 돌리면 5개 문제가 모두 사라진다. 분석·양식 채우기·검증은 지금 코드 그대로 어디서 돌려도 된다.

## 2. 해결 구조 (2단 분리)
```
[성민 PC] collector.py  ──results.json + shots/──▶  [어디서든] 숙제 프로그램
  - 정식 크롬 + 전용 프로필(성민이 1회 직접 로그인)     - quests.json 셀 맵 읽기
  - 읽기 전용, 요청 간격 6~10초                        - results.json으로 수치·평소대비 계산
  - 유튜브는 실패 시 공식 API 자동 보조                  - AI가 분석 문장 작성 → openpyxl 채우기
  - 중간에 끊겨도 이어서 수집                           - 렌더·검증(빈칸 0, 금지표현 0, 출처 재확인)
```

## 3. 실행 방법 3가지 (위가 우선)
### A. Claude Code를 성민 PC에서 실행 (권장)
- PC에 Claude Code 설치 → Claude 구독 계정으로 로그인 (API 키 별도 불필요 여부는 로그인 화면에서 확인)
- 프로젝트 폴더에 homework_kit 풀기 → `python collector/collector.py login` → `check` → `collect`
- 수집부터 엑셀 완성까지 한 대에서 끝남
### B. 클라우드 세션 + 성민 크롬 확장(Claude in Chrome)
- 2026-11-07 이 방식으로 인스타·유튜브 정상 수집 확인됨
- 조건: 노트북 켜짐 + 크롬 실행 + 확장 연결. 코드 세션에서 이 확장 도구가 보이는지 먼저 확인
### C. 유튜브만 공식 API
- 구글 클라우드 콘솔에서 YouTube Data API v3 키(무료 할당량) → 환경변수 YOUTUBE_API_KEY
- 인스타·틱톡은 남의 계정 조회수를 주는 일반 공개 API가 없어 A/B 필요

## 4. collector.py 사용법
```
pip install playwright openpyxl
python -m playwright install chromium     # 정식 크롬이 있으면 그걸 우선 사용
python collector/collector.py login       # 열린 창에서 인스타(필수)·유튜브·틱톡 직접 로그인, 각각 Enter
python collector/collector.py check       # 3개 플랫폼 실제 요청 1건씩 → OK/실패 원인 출력
python collector/collector.py collect urls.txt results.json
```
urls.txt: 게시물 링크 또는 계정 링크(계정이면 최근 게시물 조회수 목록 = '평소 대비' 계산용)

results.json 항목 예:
- 유튜브 영상: title, views, seconds, date, desc, channel, likes, comments, paid_promo
- 인스타 게시물: user, date, views, likes, comments, reposts, seconds, type, caption
- 인스타 계정: recent_reels[{href, views}] (앞 3개 고정 게시물일 수 있음)
- 틱톡 게시물: user, date, views, likes, comments, shares, saves, seconds, music, desc
- 틱톡 계정: recent[{id, views, desc}] (최근 10~12개)
- 공통: collected_at, 실패 시 err / shots/{코드}_0.5s.jpg = 첫 3초 후킹 캡처

## 5. 코드 세션에 넣을 수정 지시 (복사해서 전달)
1. 클라우드에서 인스타·유튜브에 직접 접속하는 수집 코드를 제거하고, 입력을 results.json으로 바꿔라.
2. 공유 미리보기 봇 흉내 등 우회 코드와 그걸로 얻은 수치(인스타 2건)를 삭제하고 '재측정 필요'로 표시해라.
3. results.json에 없는 수치는 절대 추정하지 말고, 빠진 링크 목록(missing_urls.txt)을 출력해 PC에서 다시 collect 하게 해라.
4. '평소 대비'는 계정 링크 수집 결과(recent)에서 고정 게시물·대상 게시물을 빼고 최근 5~10개 평균으로 배수를 계산해라.
5. 첫 3초 후킹 칸은 shots/의 0.5초 캡처를 보고 화면 자막 그대로 쓰게 해라. 캡처가 없으면 '캡처 필요'로 남겨라.
6. 실행 시작 시 results.json의 collected_at이 3일 넘게 지났으면 경고를 띄워라 (수치 최신성).
7. 최종 검증: 빈칸 0, 금지 표현 0, 모든 수치에 출처 URL과 수집 시각 연결.

## 6. 안전 수칙 (계정 보호)
- 읽기만: 좋아요·댓글·팔로우·DM 자동화 금지
- 속도: 요청 사이 6~10초, 한 번에 50건 이하, 하루 수십~100건 이내
- 인스타가 '이상 활동' 경고를 띄우면 즉시 중단하고 24시간 쉰다
- 로그인 정보는 PC의 browser_profile 폴더에만 존재. 이 폴더는 공유·업로드·깃 커밋 금지(.gitignore에 추가)
- 인스타 자동 수집은 인스타 이용약관상 허용되지 않는 행위일 수 있음 → 숙제 분량(수십 건)으로만, 사람이 보는 속도로 사용

## 7. 아직 확인 안 된 것 (실행하며 확인)
- collector.py는 클라우드에서 실제 사이트 테스트 불가 → 문법 검사만 통과. PC에서 urls_example.txt로 먼저 시험
- 유튜브 채널 최근 영상 목록 파싱(JS_YT_CHANNEL)은 유튜브 화면 구조 변경에 약함 → 실패 시 개별 영상 링크로 수집
- Claude Code를 구독 계정으로 쓸 때 사용량 한도
