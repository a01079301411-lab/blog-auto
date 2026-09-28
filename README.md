# blog-auto: 네이버 블로그 자동 발행

영상에서 손으로 하던 과정을 그대로 자동화한 프로그램입니다.

```
네이버 엔터 '최신뉴스' 기사 가져오기  →  AI(GPT/Claude)로 블로그 글 쓰기  →  내 블로그에 발행
      collect_news.py                        write_post.py                  publish.py
```

## 설치 (처음 한 번만, Windows 기준)

1. **Python 설치**: https://www.python.org/downloads/ 에서 받고,
   설치 첫 화면에서 **"Add python.exe to PATH"를 꼭 체크**하세요.
2. 이 폴더를 내려받습니다. (GitHub 페이지 → 초록색 `Code` 버튼 → `Download ZIP` → 압축 풀기)
3. 폴더 안 빈 곳에서 **Shift + 마우스 오른쪽 클릭 → "터미널에서 열기"** 후 아래를 한 줄씩 입력합니다.

```
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

4. 메모장으로 `.env` 파일을 열어서 채웁니다.
   - `BLOG_ID`: 내 블로그 주소 `blog.naver.com/아이디` 의 아이디 부분
   - AI 키: **없어도 됩니다.** 비워 두면 claude.ai나 ChatGPT 사이트에 직접 붙여 넣는 수동 모드로 동작해요.
     자동으로 하려면 OpenAI 키(https://platform.openai.com/api-keys) 또는
     Claude 키(https://console.anthropic.com) 중 하나를 넣으세요. (사용한 만큼 요금이 나가요)

## 사용법

```
python login.py      ← 처음 한 번: 뜨는 크롬 창에서 직접 네이버 로그인
python main.py       ← 기사 고르기 → 글 만들기 → 확인 → 발행
```

`main.py` 실행 순서:
1. 최신 연예 기사 목록이 번호와 함께 나옵니다. 쓰고 싶은 번호를 입력하세요.
2. AI가 글을 써서 `posts` 폴더에 저장합니다. 메모장으로 열어 고쳐도 됩니다.
3. 크롬 창이 블로그 글쓰기 화면을 열고 제목과 본문을 자동으로 입력합니다.
4. 창에서 확인한 뒤 터미널에서 Enter를 누르면 발행됩니다.

그 밖의 사용법:
- `python publish.py posts/파일.txt` : 직접 쓴 글 파일을 발행 (첫 줄 제목, 나머지 본문)
- `python collect_news.py` : 최신 기사 목록만 보기
- `python main.py --auto` : 가장 최신 기사로 확인 없이 끝까지 진행
- `prompt.txt` : AI에게 주는 지시문. 말투나 분량을 바꾸고 싶으면 이 파일을 고치세요.

## 꼭 알아두세요

- **로그인 정보는 `browser_profile` 폴더에 저장됩니다.** 이 폴더와 `.env`는 절대 남에게 주거나
  인터넷에 올리지 마세요. (`.gitignore`에 등록되어 있어 GitHub에는 올라가지 않아요)
- **기사를 그대로 옮기면 저작권 침해가 될 수 있어요.** 프롬프트에 "베끼지 말고 새로 쓰기"와
  "출처 남기기"를 넣어 두었지만, 발행 전에 한 번씩 읽어 보세요.
- **너무 자주 올리면 계정이 제재되거나 검색 노출이 떨어질 수 있어요.** 하루 1~3개 정도,
  시간 간격을 두고 올리는 것을 추천합니다. 네이버는 자동화된 글쓰기를 약관으로 제한할 수 있으니
  사용 책임은 본인에게 있습니다.
- 네이버가 화면 구조를 바꾸면 버튼을 못 찾을 수 있어요. 그때는 `publish.py` 맨 위의
  화면 요소 목록(`TITLE_AREA`, `PUBLISH_BUTTON` 등)만 고치면 됩니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| `python`을 찾을 수 없다고 나옴 | Python 설치할 때 "Add to PATH"를 체크했는지 확인 후 재설치 |
| "먼저 python login.py 로 로그인해 주세요" | `python login.py` 실행 후 로그인 |
| 기사 목록이 안 나옴 | 네이버 엔터 화면이 바뀐 것. `collect_news.py`의 선택자 확인 |
| 글쓰기 화면을 못 찾음 | `.env`의 `BLOG_ID` 확인, 로그인이 풀렸으면 `login.py` 다시 실행 |
| 보안문자(캡차)가 뜸 | 창에서 직접 풀고 진행. 자주 뜨면 발행 횟수를 줄이세요 |
