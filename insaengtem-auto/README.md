# 인생템연구소 인스타·스레드 자동 운영 프로그램

COSY 오픈딜 제품 → 실측 → 단가 계산 → 원고(Claude) → 15초 릴스 6버전 렌더 → 검수 → **주 1회 사람 승인** → 인스타·스레드 게시 → 성과 수집 → 다음 주 반영.

> **처음이면 → [docs/START_HERE.md](docs/START_HERE.md)** · Windows: `설치.bat` 더블클릭 → 바탕화면에 **'인생템연구소 자동발행'** 아이콘 생성 → 관리 화면(시작하기·다음 주 준비·일정·승인·**링크샵·제품**·성과·답글함·설정) · 제품 무제한 판매: [docs/SHOP.md](docs/SHOP.md)

- 설계 원본: [docs/DESIGN.md](docs/DESIGN.md) (11/3 Chrome 수동 운영 기록)
- 검수 결과·지금 고칠 것: [docs/REVIEW_2026-11-03.md](docs/REVIEW_2026-11-03.md)
- 트렌드 조사·반영 근거: [docs/TRENDS_2026-11.md](docs/TRENDS_2026-11.md)

## 1. 설치 (Windows PC 기준, 1회)

```bash
cd insaengtem-auto
```

```bash
pip install -r requirements.txt
```

```bash
playwright install chrome
```

ffmpeg 설치 후 PATH 등록(`ffmpeg -version`으로 확인). 한글 폰트는 맑은 고딕 자동 사용.

```bash
copy .env.example .env
```

`.env`에 토큰 입력. 제휴 링크(`sl=` 토큰)는 **원본 zip의 _catalog.json에서 비공개 폴더로 이동**:

```bash
python -m insaengtem links import "C:/Users/<나>/Downloads/insaengtem-auto/data/products/_catalog.json"
```

전용 크롬 프로필에 1회 로그인(스레드·비즈니스 스위트·YOGO). 비밀번호는 프로그램이 입력하지 않음:

```bash
python -m insaengtem login
```

## 2. 주간 루프

| 순서 | 명령 | 하는 일 |
|---|---|---|
| 1 | `python -m insaengtem scrape` | YOGO 상세페이지 → 가격·옵션·배송비·품절 (품절 자동 제외) |
| 2 | `python -m insaengtem trends` | 최근 30일 상위 게시물 수집(공식 API) → 패턴 가중치 |
| 3 | `python -m insaengtem generate` | 제품별 v1~v6 영상 JSON + 인스타 캡션 + 스레드 본문/링크칸 + 공감글 (숫자는 계산값만) |
| 4 | `python -m insaengtem render` | 15초 릴스 렌더 + 영상 검수(길이·해상도·오디오) |
| 5 | `python -m insaengtem plan --save` | 다음 주 일정(규칙 자동 적용) |
| 6 | `python -m insaengtem approve --week 2026-W46` | 검토 페이지 생성 → 확인 후 `--yes` |
| 7a | `python -m insaengtem run-due` | [API 모드] 5분마다 실행, 시각 된 건 게시 |
| 7b | `python -m insaengtem schedule-web --week 2026-W46 --platform threads` | [웹 모드] 각 서비스 예약 기능으로 일괄 예약 |
| 8 | `python -m insaengtem sync` → `insights` → `weekly` | 성과 수집 → 승자 버전 2배·액션 목록 |
| 수시 | `python -m insaengtem inbox` | 새 답글·댓글(스레드는 1시간 내 답글이 확산에 중요) |
| 수시 | `python -m insaengtem dashboard` | `out/dashboard.html` 관리 화면 |
| 일괄 | `python -m insaengtem auto` | 1~6을 한 번에(일요일 밤 예약 실행용). 승인만 사람이 |

**자동발행**: 관리 화면 [자동발행 켜기] → Windows 작업 스케줄러에 `run-due` 5분마다 / `inbox` 매시 / `weekly`(=auto + 스레드 토큰 갱신) 일요일 21:00 등록. 결과는 풍선 알림·`logs/`.

## 3. 자동 적용되는 규칙 (`config/settings.json`)

| 규칙 | 값 | 출처 |
|---|---|---|
| 스레드 | 08·12·16·20·24시, 24시는 무광고 공감글 | 사용자 확정 |
| 인스타 | 12:30·18:30·21:30 | 사용자 확정 |
| 같은 제품 | 플랫폼별 하루 1회 | 사용자 확정 |
| 같은 영상 | 플랫폼별 14일 재사용 금지 | 원본성 |
| 광고 표기 | 영상 좌상단 `광고` + 첫 줄 `[광고]` | 공정위 지침 |
| 해시태그 | **최대 5개**, 마지막 `#사기전에` | 인스타 제한(2025-12) |
| 캡션 꼬리 | 저장 → **보내기** → 프로필 링크 | sends 신호 |
| 금지 | 1인칭 사용 경험, 효능 보장, 데이터에 없는 금액 | 검수 오류 = 게시 차단 |

## 4. 버전

| 버전 | 레이아웃 | 훅 |
|---|---|---|
| v1 | 계산형 | 1개당 가격 한 방 |
| v2 | 퀴즈형 | 제일 싼 건? / 스펙 퀴즈 |
| v3 | 이유형 | 사기 전 체크 3개 |
| v4 | v1 재사용 | 절감액(“20구 말고 60구 138원↓”) |
| v5 | v2 재사용 | 배송비 퀴즈 |
| v6 | v3 재사용 | 결론부터(가격 먼저) |

## 5. 게시 방식 비교

| | API 모드(권장) | 웹 모드(지금 하던 방식 자동화) |
|---|---|---|
| 준비 | Meta 앱 + 프로페셔널 계정 토큰 | 로그인된 크롬 프로필 |
| 인스타 | resumable 업로드(공개 URL 불필요) | Business Suite 예약 |
| 스레드 영상 | **공개 URL 필요** → `MEDIA_BASE_URL` 또는 R2/S3 | 웹 작성창 예약 |
| PC 상시 켜짐 | 필요(5분마다 run-due) | 불필요(예약 걸고 끔) |
| 안정성 | 높음 | UI 변경 시 셀렉터 수정 필요 |

`config/settings.json`의 `publish_mode`로 플랫폼별 선택.

## 6. 보안
- `secrets/`, `.env`, `chrome-profile*/`, `out/`, DB는 git 제외. **이 레포는 public** → 비공개 전환 권장.
- 명리리포트 계정과 크롬 프로필·토큰 분리.

## 7. 테스트

```bash
python -m pytest -q tests
```
