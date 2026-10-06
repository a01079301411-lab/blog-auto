"""네이버 블로그 글쓰기 화면에 글을 입력하고, 임시저장 또는 발행한다.

제목 입력·본문 입력·발행 버튼 누르기는 실제 네이버에서 동작을 확인한 코드다.
사람처럼 보이게 동작 사이사이에 1~3초씩 무작위로 쉰다.
"""
import random
import re
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import sync_playwright

from config import BLOG_ID, LOGS_DIR, PROFILE_DIR

# ── 네이버 스마트에디터 화면 요소 ──
# 네이버가 화면을 바꾸면 여기만 고치면 된다. 여러 개를 적어 두면 앞에서부터 차례로 시도한다.
TITLE_AREA = [".se-documentTitle .se-text-paragraph", ".se-title-text", ".se-documentTitle"]
BODY_AREA = [".se-component.se-text .se-text-paragraph", ".se-section-text", ".se-content"]
POPUP_CLOSE = [
    ".se-popup-button-cancel",  # "작성 중인 글이 있습니다" → 취소(새로 쓰기)
    ".se-help-panel-close-button",  # 도움말 패널 닫기
]
PUBLISH_BUTTON = ['button[data-click-area="tpb.publish"]', 'button:has-text("발행")']
CONFIRM_BUTTON = ['button[data-testid="seOnePublishBtn"]', '[class*="layer"] button:has-text("발행")']
SAVE_BUTTON = ['button[data-click-area="tpb.save"]', 'button[class*="save_btn"]', 'button:has-text("저장")']
PHOTO_BUTTON = ["button.se-image-toolbar-button", ".se-toolbar-item-image button", 'button[data-name="image"]']
IMAGE_COMPONENT = ".se-component.se-image"
LINK_CARD_COMPONENT = ".se-component.se-oglink"  # 주소를 붙여 넣으면 생기는 링크 카드
CAPTION_AREA = [".se-caption .se-text-paragraph", ".se-module-text.se-caption", ".se-caption"]
CATEGORY_BUTTON = ['button[aria-label*="카테고리"]', '[class*="category"] button', 'button:has-text("카테고리")']


class PublishError(Exception):
    pass


@contextmanager
def open_browser(headless=False):
    """로그인 상태가 유지되는 크롬 창을 연다. (login.py로 한 번 로그인해 두면 계속 유지)"""
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


def screenshot(page, name):
    """실패했을 때 화면을 logs 폴더에 저장한다. 나중에 이 사진을 보고 고친다."""
    path = LOGS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        return None
    return path


def pause(page, low=1.0, high=3.0):
    page.wait_for_timeout(random.uniform(low, high) * 1000)


def write_url():
    if BLOG_ID:
        return f"https://blog.naver.com/{BLOG_ID}?Redirect=Write&"
    return "https://blog.naver.com/GoBlogWrite.naver"


def find_editor(page, seconds=30):
    """글쓰기 에디터는 iframe 안에 있을 수 있어서, 모든 frame을 뒤져 찾는다."""
    for _ in range(seconds * 2):
        for frame in page.frames:
            try:
                if frame.locator(", ".join(TITLE_AREA)).count():
                    return frame
            except Exception:
                pass  # 페이지가 바뀌는 중이면 잠깐 에러가 날 수 있다
        page.wait_for_timeout(500)
    return None


def click_first(frame, selectors, timeout=3000, pick_last=False):
    """selectors를 차례로 시도해 클릭한다. 성공하면 True.

    같은 요소가 여러 개면 기본은 첫 번째, pick_last=True면 마지막 것을 누른다.
    """
    for selector in selectors:
        found = frame.locator(selector)
        target = found.last if pick_last else found.first
        try:
            target.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def type_line(page, text):
    page.keyboard.type(text, delay=random.randint(15, 45))


def read_title(editor):
    try:
        return editor.locator(", ".join(TITLE_AREA)).first.inner_text().strip()
    except Exception:
        return ""


def type_title(page, editor, title):
    """제목을 입력하고, 앞 글자가 빠지지 않았는지 확인한다. 틀리면 지우고 다시 친다."""
    for _ in range(3):
        page.wait_for_timeout(1000)  # 칸을 누르자마자 치면 첫 글자가 빠질 수 있다
        page.keyboard.type(title, delay=30)
        page.wait_for_timeout(500)
        if read_title(editor) == title.strip():
            return
        # 제목 칸 안의 글자만 선택해서 지우고 다시 입력
        page.keyboard.press("End")
        page.keyboard.press("Shift+Home")
        page.keyboard.press("Backspace")
    raise PublishError(f"제목이 제대로 입력되지 않았어요: {title}")


def insert_photo(page, editor, path, caption):
    """현재 커서 위치에 사진을 올리고 캡션을 단다. 성공하면 True."""
    before = editor.locator(IMAGE_COMPONENT).count()
    try:
        with page.expect_file_chooser(timeout=8000) as chooser:
            if not click_first(editor, PHOTO_BUTTON):
                raise PublishError("사진 버튼 없음")
        chooser.value.set_files(str(path))
    except Exception:
        # 파일 선택 창 대신 숨은 업로드 칸이 있는 경우
        try:
            editor.locator('input[type="file"]').first.set_input_files(str(path))
        except Exception:
            return False

    for _ in range(60):  # 업로드는 최대 30초 기다린다
        if editor.locator(IMAGE_COMPONENT).count() > before:
            break
        page.wait_for_timeout(500)
    else:
        return False
    pause(page)

    image = editor.locator(IMAGE_COMPONENT).last
    if caption:
        for selector in CAPTION_AREA:
            try:
                image.locator(selector).first.click(timeout=3000)
                page.wait_for_timeout(500)
                type_line(page, caption)
                break
            except Exception:
                continue

    move_below(page, editor, image)
    return True


def move_below(page, editor, component):
    """사진, 링크 카드 바로 아래 글 칸으로 커서를 옮긴다."""
    below = component.locator(
        "xpath=following-sibling::div[contains(@class,'se-text')][1]//p[contains(@class,'se-text-paragraph')]"
    )
    target = below.last if below.count() else editor.locator(".se-text-paragraph").last
    target.click()
    page.keyboard.press("End")
    page.wait_for_timeout(500)


def insert_link(page, editor, url):
    """내 블로그 다른 글 주소를 붙여 넣어 링크 카드를 만든다.
    카드가 안 만들어지면 주소가 글자(링크)로 남는다."""
    before = editor.locator(LINK_CARD_COMPONENT).count()
    try:
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        editor.evaluate("url => navigator.clipboard.writeText(url)", url)
        page.keyboard.press("Control+v")
    except Exception:
        type_line(page, url)
    for _ in range(12):  # 링크 카드는 최대 6초 기다린다
        page.wait_for_timeout(500)
        if editor.locator(LINK_CARD_COMPONENT).count() > before:
            move_below(page, editor, editor.locator(LINK_CARD_COMPONENT).last)
            return
    page.keyboard.press("Enter")


def type_blocks(page, editor, blocks, photo_paths, captions):
    """formatter가 만든 블록을 차례로 입력한다. 사진 실패는 건너뛰고 목록으로 돌려준다."""
    failed_photos = []
    for i, block in enumerate(blocks):
        kind = block["type"]
        if kind == "blank":
            if i and blocks[i - 1]["type"] in ("photo", "link"):
                continue  # 사진, 링크 아래에는 이미 새 줄이 있다
            page.keyboard.press("Enter")
        elif kind == "link":
            insert_link(page, editor, block["url"])
        elif kind == "photo":
            path = photo_paths.get(block["file"])
            if not path or not insert_photo(page, editor, path, captions.get(block["file"], "")):
                failed_photos.append(block["file"])
        else:
            bold = kind == "heading" or block.get("bold")
            if bold:
                page.keyboard.press("Control+b")
            type_line(page, block["text"])
            if bold:
                page.keyboard.press("Control+b")
            page.keyboard.press("Enter")
        if i % 8 == 7:
            pause(page, 0.5, 2.0)  # 가끔 쉬어 가며 입력
    return failed_photos


def select_category(page, editor, category):
    """발행 설정 창에서 카테고리를 고른다. 못 고르면 기본 카테고리로 발행된다."""
    if not category:
        return True
    if not click_first(editor, CATEGORY_BUTTON, timeout=2000):
        return False
    pause(page, 0.5, 1.5)
    try:
        editor.get_by_text(category, exact=True).last.click(timeout=3000)
        return True
    except Exception:
        return False


def post_url(page):
    """발행된 글 주소. 글 보기 화면이 iframe 안에 열릴 수 있어서 모든 frame에서 찾는다."""
    for url in [page.url] + [f.url for f in page.frames]:
        if "logNo=" in url or re.search(r"blog\.naver\.com/[^/?]+/\d+", url):
            return url
    return page.url


def post(page, title, blocks, tags, photo_paths=None, captions=None, publish=False, category=""):
    """글을 입력하고 임시저장(publish=False) 또는 발행(publish=True)한다.

    돌려주는 값: {"result": "draft" | "published", "url": ..., "failed_photos": [...], "warnings": [...]}
    실패하면 PublishError를 낸다.
    """
    photo_paths, captions, warnings = photo_paths or {}, captions or {}, []

    page.goto(write_url(), wait_until="domcontentloaded")
    if "nidlogin" in page.url:
        raise PublishError("네이버 로그인이 풀렸어요. login 을 다시 실행해 주세요.")
    editor = find_editor(page)
    if editor is None:
        raise PublishError(f"글쓰기 화면을 찾지 못했어요. 화면: {screenshot(page, 'no_editor')}")

    pause(page)
    for selector in POPUP_CLOSE:
        click_first(editor, [selector], timeout=1500)

    if not click_first(editor, TITLE_AREA):
        raise PublishError(f"제목 칸을 찾지 못했어요. 화면: {screenshot(page, 'no_title')}")
    type_title(page, editor, title)
    pause(page)

    if not click_first(editor, BODY_AREA):
        raise PublishError(f"본문 칸을 찾지 못했어요. 화면: {screenshot(page, 'no_body')}")
    page.wait_for_timeout(1000)  # 칸을 누르자마자 치면 첫 글자가 빠질 수 있다
    failed = type_blocks(page, editor, blocks, photo_paths, captions)
    if tags:  # 본문 끝에 #태그를 쓰면 네이버가 태그로 등록한다
        page.keyboard.press("Enter")
        for tag in tags:
            type_line(page, f"#{tag}")
            page.keyboard.press("Space")
    if failed:
        warnings.append(f"사진 {len(failed)}장을 넣지 못했어요: {', '.join(failed)}")
    pause(page)

    if not publish:
        if not click_first(editor, SAVE_BUTTON):
            raise PublishError(f"임시저장 버튼을 찾지 못했어요. 화면: {screenshot(page, 'no_save')}")
        page.wait_for_timeout(3000)
        return {"result": "draft", "url": page.url, "failed_photos": failed, "warnings": warnings}

    if not click_first(editor, PUBLISH_BUTTON):
        raise PublishError(f"발행 버튼을 찾지 못했어요. 화면: {screenshot(page, 'no_publish')}")
    pause(page)  # 발행 설정 창이 뜰 때까지 대기
    if not select_category(page, editor, category):
        warnings.append(f"카테고리 '{category}'를 고르지 못해 기본 카테고리로 발행했어요.")
    if not click_first(editor, CONFIRM_BUTTON, pick_last=True):
        raise PublishError(f"발행 확인 버튼을 찾지 못했어요. 화면: {screenshot(page, 'no_confirm')}")

    # 발행되면 에디터가 사라지고 글 보기 화면으로 바뀐다
    for _ in range(30):
        page.wait_for_timeout(1000)
        if find_editor(page, seconds=1) is None:
            return {"result": "published", "url": post_url(page), "failed_photos": failed, "warnings": warnings}
    raise PublishError(f"발행이 끝났는지 확인하지 못했어요. 화면: {screenshot(page, 'unknown')}")
