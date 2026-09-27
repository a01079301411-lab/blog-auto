"""1단계: 네이버 엔터 '최신뉴스'에서 최신 기사 목록과 본문을 가져온다.

영상에서 손으로 하던 '엔터판 → 최신뉴스 탭 → 기사 복사'를 대신 해 준다.
따로 실행해 보기:  python collect_news.py
"""
import json

from common import POSTS_DIR, open_browser

NOW_URL = "https://m.entertain.naver.com/now"  # 네이버 엔터 최신뉴스
HISTORY_FILE = POSTS_DIR / "history.json"  # 이미 글로 쓴 기사 주소 기록

# 기사 본문이 들어 있는 곳 (네이버 화면이 바뀌면 여기를 고치면 된다)
BODY_SELECTORS = ["#dic_area", "._article_content", "#articeBody", "article"]


def fetch_latest(page, limit=20):
    """최신뉴스 목록을 [{'title': ..., 'url': ...}, ...] 로 돌려준다."""
    page.goto(NOW_URL, wait_until="domcontentloaded")
    page.wait_for_selector("a[href*='/article/']", state="attached", timeout=20000)
    links = page.eval_on_selector_all(
        "a[href*='/article/']",
        "els => els.map(a => ({url: a.href.split('?')[0], text: a.innerText || ''}))",
    )

    news = {}
    for link in links:
        # 링크 안에 언론사·시간 등이 같이 있을 수 있어서 가장 긴 줄을 제목으로 쓴다
        lines = [line.strip() for line in link["text"].splitlines() if line.strip()]
        title = max(lines, key=len, default="")
        if len(title) < 8:
            continue
        if len(title) > len(news.get(link["url"], "")):
            news[link["url"]] = title
    return [{"title": t, "url": u} for u, t in news.items()][:limit]


def fetch_article(page, url):
    """기사 하나를 열어 {'title', 'body', 'url'} 을 돌려준다."""
    page.goto(url, wait_until="domcontentloaded")
    title = page.get_attribute('meta[property="og:title"]', "content") or ""

    body = ""
    for selector in BODY_SELECTORS:
        box = page.locator(selector).first
        try:
            box.wait_for(timeout=5000)
            body = box.inner_text().strip()
        except Exception:
            continue
        if len(body) > 200:
            break
    if len(body) <= 200:  # 못 찾았으면 페이지 전체 글자라도 가져온다
        body = page.inner_text("body")
    return {"title": title.strip(), "body": body[:6000], "url": url}


def load_history():
    if HISTORY_FILE.exists():
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    return set()


def add_history(url):
    used = load_history() | {url}
    HISTORY_FILE.write_text(json.dumps(sorted(used), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    with open_browser() as page:
        for i, item in enumerate(fetch_latest(page), 1):
            print(f"{i:2}. {item['title']}\n    {item['url']}")
