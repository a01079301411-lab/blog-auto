"""전체 자동화: 최신 이슈 기사 고르기 → AI로 글 쓰기 → 내 블로그에 발행.

실행:            python main.py
1번 기사 자동 선택: python main.py --auto
"""
import os
import sys

from collect_news import add_history, fetch_article, fetch_latest, load_history
from common import is_logged_in, open_browser, read_post
from publish import publish_post
from write_post import write_post

AUTO = "--auto" in sys.argv  # 기사를 자동으로 고르고 확인 없이 발행
AUTO_PUBLISH = AUTO or os.getenv("AUTO_PUBLISH") == "1"


def choose(news):
    """아직 안 쓴 기사 중에서 하나를 고른다."""
    used = load_history()
    fresh = [n for n in news if n["url"] not in used]
    if not fresh:
        print("새로 쓸 기사가 없어요. 잠시 후 다시 실행해 보세요.")
        return None
    if AUTO:
        return fresh[0]

    print("\n[최신 이슈 기사]")
    for i, item in enumerate(fresh, 1):
        print(f"{i:2}. {item['title']}")
    number = input("\n글로 쓸 기사 번호를 입력하세요 (그만두려면 Enter): ").strip()
    if not number.isdigit() or not 1 <= int(number) <= len(fresh):
        return None
    return fresh[int(number) - 1]


def main():
    with open_browser() as page:
        if not is_logged_in(page):
            print("먼저 python login.py 로 로그인해 주세요.")
            return

        print("1) 네이버 엔터 최신뉴스를 가져오는 중...")
        picked = choose(fetch_latest(page))
        if picked is None:
            return
        print(f"   선택: {picked['title']}")
        article = fetch_article(page, picked["url"])

        print("2) 블로그 글을 만드는 중...")
        post_path = write_post(article)
        title, body = read_post(post_path)
        if not title or not body:
            print(f"글 내용이 비어 있어요: {post_path}")
            return
        print(f"   저장됨: {post_path}")
        print(f"   제목: {title}")
        print(f"   본문 미리보기: {body[:150]}...")

        if not AUTO_PUBLISH:
            input("\n   메모장으로 위 파일을 열어 고쳐도 돼요. 고쳤으면 저장 후 Enter... ")
            title, body = read_post(post_path)

        print("3) 블로그에 발행하는 중...")
        if publish_post(page, title, body, auto=AUTO_PUBLISH):
            add_history(picked["url"])


if __name__ == "__main__":
    main()
