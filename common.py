"""여러 파일에서 같이 쓰는 설정과 도우미 함수 모음."""
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# 로그인 정보가 저장되는 크롬 프로필 폴더 (절대 다른 사람에게 공유하지 마세요)
PROFILE_DIR = ROOT / "browser_profile"
# 만들어진 글이 저장되는 폴더
POSTS_DIR = ROOT / "posts"
POSTS_DIR.mkdir(exist_ok=True)

BLOG_ID = os.getenv("BLOG_ID", "").strip()


@contextmanager
def open_browser(headless=False):
    """로그인 상태가 유지되는 크롬 창을 연다.

    한 번 login.py로 로그인해 두면 browser_profile 폴더에 로그인이 저장돼서
    다음부터는 다시 로그인하지 않아도 된다.
    """
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            context.close()


def is_logged_in(page):
    """네이버 로그인 쿠키(NID_AUT)가 있으면 로그인된 상태."""
    return any(c["name"] == "NID_AUT" for c in page.context.cookies("https://naver.com"))


def read_post(path):
    """글 파일을 읽어 (제목, 본문)으로 돌려준다. 첫 줄이 제목, 나머지가 본문."""
    text = Path(path).read_text(encoding="utf-8").strip()
    title, _, body = text.partition("\n")
    title = title.removeprefix("제목:").strip()
    return title, body.strip()
