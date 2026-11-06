# 프로토 데이터룸 수집기

해외축구·NBA·NHL·MLB 경기 데이터를 무료 공개 데이터로 모으고, 경기별 SEO 페이지를 자동으로 만들어 GitHub Pages에 올립니다. 비용은 0원입니다.

## 하는 일

| 단계 | 내용 |
|---|---|
| 수집 | ESPN 공개 JSON: EPL·라리가·분데스리가·세리에A·리그1·챔피언스리그·유로파리그·J리그·NBA·NHL·MLB |
| 국내 | API-Sports 무료 플랜(종목별 하루 100회): K리그1·2(라인업·부상 포함), KBL, WKBL, V리그 남녀, KBO. 키 없으면 CSV 입력 |
| 시즌 기록 | 팀별 시즌 일정으로 이번 시즌 전체 경기 + 지난 시즌(한 번만 받음) |
| 승률 분석 | Elo(지난 시즌 70% 이어받기, 승격팀 보정) + 홈·원정 성적, 휴식일·연전, 부상(주축 선수 가중), 최근 흐름, 요일별 성적, 상대전적. 축구·하키는 포아송 득점 모델과 결합(예상 스코어·오버/언더·양팀득점) |
| 분석 코멘트 | 영향이 큰 요인 순서로 한국어 문장 자동 생성 |
| 적중 기록 | 경기 전 시점 예측을 채점해 리그별 적중률·브라이어 점수 공개 (`record.html`) |
| 팀 페이지 | 팀마다 전력 순위, 홈·원정 승률, 다음 경기 승률, 부상자, 최근 10경기 |
| 상세 | 36시간 안에 열리는 경기, 진행 중인 경기, 12시간 안에 끝난 경기만 라인업·부상·최근 5경기·맞대결 조회 |
| 프로토 | `data/manual/proto.csv`에 베트맨 공식 배당 입력 → `proto.html` 회차 페이지 |
| 감지 | 직전 상태와 비교해 **선발 확정 · 새 부상 · 경기 종료**만 속보로 기록 |
| 알림 | 텔레그램 채널 자동 발송 (무료, 토큰 등록 시) |
| 사이트 | 경기별 페이지(FAQ·구조화 데이터 포함), 리그별·속보·프로토 페이지, 소개·개인정보처리방침, sitemap, robots, ads.txt |

해외 업체 배당과 티켓 링크는 수집 단계에서 버립니다.

## 실행

```bash
cd sports-data
python -m collector.run              # 1회 실행 (파이썬 3.10+, 외부 패키지 없음)
python -m collector.run --watch      # 상시 실행: 경기 90분 전·경기 중에는 30초, 그 외에는 10분 간격
python -m collector.run --no-notify --no-publish
```

## 처음 한 번 설정

1. **GitHub Pages 켜기**: 저장소 Settings → Pages → Source를 `GitHub Actions`로 선택
2. **자동 실행**: `.github/workflows/sports-data.yml`이 10분마다 실행됩니다. Actions 탭에서 `Run workflow`로 바로 실행할 수도 있습니다.
3. **텔레그램 채널(회원 모집용)**
   - 텔레그램에서 채널 생성 → @BotFather로 봇 생성 → 봇을 채널 관리자로 추가
   - 저장소 Settings → Secrets and variables → Actions에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`(예: `@채널아이디`) 등록
4. **국내 리그 (API-Sports 무료 키)**: dashboard.api-football.com 가입 → API 키 복사 → 저장소 Secrets에 `APISPORTS_KEY` 등록. 한 키로 축구·농구·배구·야구 모두 사용
5. **`config/site.json` 채우기**
   - `telegram_channel_url`, `kakao_channel_url`, `google_form_url`: 채우면 모든 페이지에 "무료 알림 받기" 버튼이 나타납니다
   - `adsense_client`: 애드센스 승인 후 `ca-pub-...` 입력 → 광고 자리와 ads.txt가 자동 생성됩니다
   - `base_url`: 개인 도메인을 연결하면 그 주소로 바꿉니다

## 애드센스 주의

- `github.io` 주소로는 애드센스 승인을 받을 수 없습니다. 도메인을 연결해야 합니다.
- 기존 승인 도메인(cuppang.com)의 하위 도메인(예: `sports.cuppang.com`)을 쓰면 추가 비용이 없습니다. 다만 같은 애드센스 계정이라, 이 사이트가 정책 위반을 받으면 기존 사이트 수익에도 영향을 줄 수 있습니다.
- 페이지 문구는 정보 전달만 합니다. 구매 권유, 픽, 적중 보장, 사설 사이트 링크는 넣지 않습니다.

## 파일 구조

```
collector/espn.py     ESPN 수집·정리
collector/model.py    시즌 성적 기반 기본 확률 (참고용)
collector/manual.py   국내 경기·프로토 회차 CSV
collector/run.py      수집 → 감지 → 알림 → 생성
collector/publish.py  정적 사이트 생성
collector/notify.py   텔레그램 발송
config/               리그 목록, 팀 한글명, 사이트 설정
data/manual/          수동 입력 CSV
```

## 국내 데이터를 직접 긁지 않는 이유

- KBO 공식 사이트 robots.txt: "본 사이트의 데이터를 사전 승인 없이 자동 수집·크롤링·복제하는 행위를 금지합니다", 전체 수집 차단
- 국내 리그 기록은 공식 데이터 공급사(스포츠투아이)가 관리 → 무단 수집 시 데이터베이스권 침해 위험
- 네이버 스포츠·베트맨은 해외 서버 접속 차단
- 그래서 라이선스를 받은 API-Sports(무료 플랜)를 쓰고, 사업이 커지면 스포츠투아이 등 공식 데이터 계약으로 옮깁니다
