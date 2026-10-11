"""네이버 블로그 글쓰기 화면에 글을 입력하고, 임시저장 또는 발행한다.

제목 입력·본문 입력·발행 버튼 누르기는 실제 네이버에서 동작을 확인한 코드다.
사람처럼 보이게 동작 사이사이에 1~3초씩 무작위로 쉰다.
"""
import logging
import random
import re
from contextlib import contextmanager
from datetime import datetime

from playwright.sync_api import sync_playwright

from config import BLOG_ID, COMPANY_PHONE, LOGS_DIR, PROFILE_DIR

log = logging.getLogger(__name__)

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
# 가운데 정렬: 정렬 버튼을 눌러 목록을 연 뒤 '가운데'를 고른다
ALIGN_BUTTON = [
    ".se-toolbar-item-align button", "button[class*='align'][class*='toolbar-button']",
    'button[data-name="align-drop-down-with-justify"]', 'button[data-name="align"]',
]
ALIGN_CENTER = [
    "button[class*='align-center']", 'button[data-value="center"]',
    'button:has-text("가운데 정렬")', 'button[aria-label*="가운데"]',
]
# 굵게 버튼 (켜져 있는지 확인하는 데 쓴다)
BOLD_BUTTON = ["button.se-bold-toolbar-button", 'button[data-name="bold"]', ".se-toolbar-item-bold button"]
# 에디터 위쪽 '링크' 버튼으로 링크 카드 넣기 (주소 입력 → 검색 → 확인)
OGLINK_BUTTON = ["button.se-oglink-toolbar-button", ".se-toolbar-item-oglink button", 'button[data-name="oglink"]']
OGLINK_INPUT = ["input.se-popup-oglink-input", ".se-popup-oglink input", "[class*='oglink'] input[type='text']"]
OGLINK_SEARCH = ["button.se-popup-oglink-button", ".se-popup-oglink button[class*='search']",
                 "[class*='oglink'] button:has-text('검색')"]
OGLINK_CONFIRM = ["button.se-popup-button-confirm", ".se-popup-oglink button:has-text('확인')",
                  "[class*='popup'] button:has-text('확인')"]
# 글자에 링크 걸기 (전화번호 줄에 tel: 링크). 주소로 카드를 만드는 '링크 카드' 창과는 다르다.
TEXT_LINK_BUTTON = ["button.se-link-toolbar-button", ".se-toolbar-item-link button"]
TEXT_LINK_INPUT = [
    "input.se-custom-layer-link-input", ".se-custom-layer-link input",
    "input[placeholder*='URL']:not(.se-popup-oglink *)", "input[placeholder*='링크']:not(.se-popup-oglink *)",
]
TEXT_LINK_APPLY = ["button.se-custom-layer-link-apply-button", ".se-custom-layer-link button:has-text('확인')"]
# 발행 설정 창의 태그 입력 칸
TAG_INPUT = ['input[placeholder*="태그"]', "#tag-input", "input[class*='tag_input']", "input[class*='tag']"]
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
            no_viewport=True,  # 노트북, 데스크톱 어떤 화면이든 창 크기에 맞춘다
            locale="ko-KR",
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            try:
                context.close()
            except Exception:
                pass  # 창이 이미 닫혔으면 그냥 넘어간다


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
            pass
        try:
            if target.count():  # 있는데 덮개에 가려 못 누른 경우: 덮개를 무시하고 누른다
                target.click(timeout=timeout, force=True)
                return True
        except Exception:
            pass
    return False


def click_text(target, timeout=2000):
    """글 칸을 클릭한다. 네이버 에디터는 깜박이는 커서와 선택 표시를 글 위에 덮어 두는데,
    이 덮개가 클릭을 가로막으면 덮개를 무시하고 그 자리를 바로 누른다. 성공하면 True."""
    try:
        target.click(timeout=timeout)
        return True
    except Exception:
        pass
    try:
        target.click(timeout=timeout, force=True)
        return True
    except Exception:
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
                if not click_text(image.locator(selector).first, timeout=3000):
                    continue
                page.wait_for_timeout(500)
                type_line(page, caption)
                break
            except Exception:
                continue

    move_below(page, editor, image)
    return True


def align_center(page, editor):
    """지금 커서가 있는 줄부터 가운데 정렬로 바꾼다. 성공하면 True."""
    if not click_first(editor, ALIGN_BUTTON, timeout=1500):
        return False
    page.wait_for_timeout(300)
    return click_first(editor, ALIGN_CENTER, timeout=1500)


def move_below(page, editor, component):
    """사진, 링크 카드 바로 아래 글 칸으로 커서를 옮긴다."""
    below = component.locator(
        "xpath=following-sibling::div[contains(@class,'se-text')][1]//p[contains(@class,'se-text-paragraph')]"
    )
    target = below.last if below.count() else editor.locator(".se-text-paragraph").last
    click_text(target)
    page.keyboard.press("End")
    page.wait_for_timeout(500)
    align_center(page, editor)  # 새 글 칸은 왼쪽 정렬로 시작할 수 있어서 다시 맞춘다


def bold_is_on(editor):
    """지금 굵게가 켜져 있는지. 모르면 None."""
    for selector in BOLD_BUTTON:
        button = editor.locator(selector).first
        try:
            if button.count():
                state = (button.get_attribute("class") or "") + " " + (button.get_attribute("aria-pressed") or "")
                return "selected" in state or "true" in state or "active" in state
        except Exception:
            continue
    try:
        return bool(editor.evaluate("document.queryCommandState('bold')"))
    except Exception:
        return None


def set_bold(page, editor, on):
    """굵게를 켜거나 끈다. 누를 때마다 바뀌는 버튼이라, 지금 상태를 보고 필요할 때만 누른다."""
    state = bold_is_on(editor)
    if state is None:
        if on:  # 상태를 모르면 켤 때만 누르고, 끌 때는 type_blocks가 짝을 맞춰 누른다
            page.keyboard.press("Control+b")
        return state
    if state != on:
        page.keyboard.press("Control+b")
    return state


def _plain(text):
    """띄어쓰기와 눈에 안 보이는 글자(네이버가 넣는 특수 공백)를 뺀 글자."""
    return re.sub(r"[\s\u200b\u200c\u200d\u2060\ufeff]", "", text).rstrip("/")


def _undo_if_card_lost(page, editor, cards_before):
    """링크 카드가 줄었으면(지우기 키가 카드를 지웠으면) 되돌린다. 카드를 지켰으면 True."""
    for _ in range(3):
        if editor.locator(LINK_CARD_COMPONENT).count() >= cards_before:
            return True
        page.keyboard.press("Control+z")
        page.wait_for_timeout(500)
    return editor.locator(LINK_CARD_COMPONENT).count() >= cards_before


def remove_url_lines(page, editor, url):
    """주소 글자만 있는 줄을 지운다. (링크 카드가 생긴 뒤 남은 주소 글자)
    지우다가 링크 카드가 사라지면 바로 되돌리고 멈춘다. 돌려주는 값: 'removed', 'none', 'kept_card'"""
    target = _plain(url)
    result = "none"
    for _ in range(3):
        lines = editor.locator(".se-text-paragraph")
        found = None
        for i in range(lines.count()):
            try:
                line = lines.nth(i)
                box = line.bounding_box()
                # 높이가 없는(안 보이는) 줄을 누르면 카드가 눌릴 수 있어서 건너뛴다
                if _plain(line.inner_text()) == target and box and box["height"] > 5:
                    found = line
                    break
            except Exception:
                continue
        if found is None or not click_text(found):
            return result
        cards_before = editor.locator(LINK_CARD_COMPONENT).count()
        page.keyboard.press("End")
        page.keyboard.press("Shift+Home")
        page.keyboard.press("Backspace")  # 주소 글자 지우기
        page.wait_for_timeout(300)
        if editor.locator(LINK_CARD_COMPONENT).count() < cards_before:
            # 지우기 키가 카드를 지웠다 → 되돌리고, 주소 글자는 남겨 둔 채 멈춘다
            return "kept_card" if _undo_if_card_lost(page, editor, cards_before) else "card_lost"
        result = "removed"
        try:
            line_left = found.is_visible() and _plain(found.inner_text()) == ""
        except Exception:
            line_left = False
        if line_left:
            page.keyboard.press("Backspace")  # 남은 빈 줄 지우기
            page.wait_for_timeout(300)
            if editor.locator(LINK_CARD_COMPONENT).count() < cards_before:
                _undo_if_card_lost(page, editor, cards_before)
                return result
    return result


def add_phone_link(page, editor):
    """방금 쓴 전화번호 줄을 선택해 tel: 링크를 건다. 모바일에서 누르면 바로 전화가 걸린다."""
    tel = "tel:" + re.sub(r"\D", "", COMPANY_PHONE)
    page.keyboard.press("Shift+Home")  # 방금 쓴 줄 선택
    page.wait_for_timeout(300)
    box = None
    for attempt in ("shortcut", "button"):
        if attempt == "shortcut":
            page.keyboard.press("Control+k")
        elif not click_first(editor, TEXT_LINK_BUTTON, timeout=1500):
            break
        page.wait_for_timeout(500)
        box = next((editor.locator(sel).first for sel in TEXT_LINK_INPUT
                    if editor.locator(sel).first.is_visible()), None)
        if box:
            break
    ok = False
    if box:
        try:
            box.fill(tel)
            if not click_first(editor, TEXT_LINK_APPLY, timeout=1000):
                page.keyboard.press("Enter")
            ok = True
        except Exception:
            pass
    page.wait_for_timeout(300)
    if not ok:
        page.keyboard.press("Escape")
    page.keyboard.press("End")  # 선택 풀고 줄 끝으로
    return ok


def _visible(editor, selectors):
    for selector in selectors:
        target = editor.locator(selector).first
        try:
            if target.count() and target.is_visible():
                return target
        except Exception:
            continue
    return None


def _link_card_by_toolbar(page, editor, url):
    """에디터 위쪽 '링크' 버튼으로 카드를 만든다. 클립보드가 필요 없고 주소 글자도 남지 않는다."""
    before = editor.locator(LINK_CARD_COMPONENT).count()
    if not click_first(editor, OGLINK_BUTTON, timeout=2000):
        return False, "링크 버튼 없음"
    box = None
    for _ in range(10):  # 처음 여는 링크 창은 늦게 뜰 때가 있어서 최대 5초 기다린다
        page.wait_for_timeout(500)
        box = _visible(editor, OGLINK_INPUT)
        if box is not None:
            break
    if box is None:
        page.keyboard.press("Escape")
        return False, "주소 입력 칸 없음"
    box.fill(url)
    if not click_first(editor, OGLINK_SEARCH, timeout=1500):
        page.keyboard.press("Enter")
    for _ in range(20):  # 미리보기가 뜨면 '확인'을 누른다 (최대 10초)
        page.wait_for_timeout(500)
        if editor.locator(LINK_CARD_COMPONENT).count() > before:
            return True, "링크 버튼"
        click_first(editor, OGLINK_CONFIRM, timeout=300)
    page.keyboard.press("Escape")
    return False, "확인 후에도 카드 없음"


def _link_card_by_paste(page, editor, url):
    """주소를 붙여 넣어 카드를 만든다 (예전 방식). 남은 주소 글자는 지운다."""
    before = editor.locator(LINK_CARD_COMPONENT).count()
    try:
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.bring_to_front()
        editor.evaluate("url => navigator.clipboard.writeText(url)", url)
        page.keyboard.press("Control+v")
    except Exception as e:
        return False, f"클립보드 사용 불가: {e.__class__.__name__}"
    for _ in range(20):  # 링크 카드는 최대 10초 기다린다
        page.wait_for_timeout(500)
        if editor.locator(LINK_CARD_COMPONENT).count() > before:
            page.wait_for_timeout(500)
            return True, f"붙여 넣기, 주소 글자 정리={remove_url_lines(page, editor, url)}"
    remove_url_lines(page, editor, url)  # 카드가 안 생겼으면 붙여 넣은 주소 글자도 남기지 않는다
    return False, "붙여 넣었지만 카드 안 생김"


def insert_link(page, editor, url):
    """내 블로그 다른 글을 링크 카드로 넣는다. '링크' 버튼 → 안 되면 붙여 넣기 순서로 시도한다.
    둘 다 안 되면 그 순간 화면을 logs 폴더에 저장한다."""
    reasons = []
    # 링크 버튼이 첫 번째에 실패하는 경우가 있어서 한 번 더 해 보고, 그래도 안 되면 붙여 넣기
    for method in (_link_card_by_toolbar, _link_card_by_toolbar, _link_card_by_paste):
        ok, how = method(page, editor, url)
        if ok:
            log.info("내부링크: 카드 생성됨 (%s) %s", how, url)
            move_below(page, editor, editor.locator(LINK_CARD_COMPONENT).last)
            return True
        reasons.append(how)
    shot = screenshot(page, "link_fail")
    log.info("내부링크: 카드를 못 만들었어요 (%s) %s 화면: %s", " / ".join(reasons), url, shot)
    return False


def type_blocks(page, editor, blocks, photo_paths, captions):
    """formatter가 만든 블록을 차례로 입력한다.
    실패는 건너뛰고 (넣지 못한 사진, 전화 링크를 못 건 줄) 목록으로 돌려준다."""
    failed_photos, failed_phone_links = [], []
    for i, block in enumerate(blocks):
        kind = block["type"]
        if kind == "blank":
            if i and blocks[i - 1]["type"] in ("photo", "link"):
                continue  # 사진, 링크 아래에는 이미 새 줄이 있다
            if i + 1 < len(blocks) and blocks[i + 1]["type"] == "photo":
                continue  # 사진은 지금 줄 아래에 들어가므로 빈 줄을 더 만들지 않는다
            page.keyboard.press("Enter")
        elif kind == "link":
            insert_link(page, editor, block["url"])
        elif kind == "photo":
            path = photo_paths.get(block["file"])
            if not path or not insert_photo(page, editor, path, captions.get(block["file"], "")):
                failed_photos.append(block["file"])
        else:
            bold = kind == "heading" or bool(block.get("bold"))
            before = set_bold(page, editor, bold)  # 이 줄에 맞게 굵게를 켜거나 끈다
            type_line(page, block["text"])
            if block.get("phone") and not add_phone_link(page, editor):
                failed_phone_links.append(block["text"])
            if bold and before is None:
                page.keyboard.press("Control+b")  # 상태를 모를 때는 켠 만큼 다시 끈다
            elif bold:
                set_bold(page, editor, False)
            page.keyboard.press("Enter")
        if i % 8 == 7:
            pause(page, 0.5, 2.0)  # 가끔 쉬어 가며 입력
    return failed_photos, failed_phone_links


def add_tags(page, editor, tags):
    """발행 설정 창의 태그 칸에 태그를 하나씩 넣는다. (발행 설정 창이 열려 있어야 한다)"""
    for selector in TAG_INPUT:
        box = editor.locator(selector).first
        try:
            box.click(timeout=2000)
        except Exception:
            continue
        for tag in tags:
            type_line(page, tag)
            page.keyboard.press("Enter")
            page.wait_for_timeout(200)
        return True
    return False


def type_tags_in_body(page, editor, tags):
    """태그 칸을 못 찾았을 때: 본문 끝에 #태그로 쓴다. (네이버가 발행할 때 태그로 등록한다)"""
    click_text(editor.locator(".se-text-paragraph").last)
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    for tag in tags:
        type_line(page, f"#{tag}")
        page.keyboard.press("Space")


def open_publish_layer(page, editor):
    if not click_first(editor, PUBLISH_BUTTON):
        raise PublishError(f"발행 버튼을 찾지 못했어요. 화면: {screenshot(page, 'no_publish')}")
    pause(page)  # 발행 설정 창이 뜰 때까지 대기


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
    if not align_center(page, editor):
        warnings.append("가운데 정렬 버튼을 찾지 못해 왼쪽 정렬로 썼어요.")
    failed, failed_phone_links = type_blocks(page, editor, blocks, photo_paths, captions)
    # 마지막 확인: 늦게 생긴 링크 카드 위에 주소 글자가 남아 있으면 지운다
    for block in blocks:
        if block["type"] == "link" and editor.locator(LINK_CARD_COMPONENT).count():
            remove_url_lines(page, editor, block["url"])
    wanted = sum(1 for b in blocks if b["type"] == "link")
    cards = editor.locator(LINK_CARD_COMPONENT).count()
    log.info("내부링크: 넣을 링크 %s개, 글에 있는 링크 카드 %s개", wanted, cards)
    if cards < wanted:
        warnings.append(f"내부링크 {wanted}개 중 링크 카드가 {cards}개만 들어갔어요.")
    if failed:
        warnings.append(f"사진 {len(failed)}장을 넣지 못했어요: {', '.join(failed)}")
    if failed_phone_links:
        warnings.append("전화번호에 전화 링크를 걸지 못한 줄이 있어요. 번호는 글자로 들어갔어요.")
    pause(page)

    # 태그는 본문이 아니라 발행 설정 창의 태그 칸에 넣는다 (본문이 깔끔해진다)
    open_publish_layer(page, editor)
    tags_ok = add_tags(page, editor, tags) if tags else True

    if not publish:
        page.keyboard.press("Escape")  # 발행 설정 창 닫기
        page.wait_for_timeout(500)
        if editor.locator(", ".join(CONFIRM_BUTTON)).first.is_visible():
            click_first(editor, PUBLISH_BUTTON)  # Esc로 안 닫히면 발행 버튼을 다시 눌러 닫는다
            page.wait_for_timeout(500)
        if not tags_ok:
            type_tags_in_body(page, editor, tags)
            warnings.append("태그 칸을 찾지 못해 본문 끝에 #태그로 넣었어요.")
        if not click_first(editor, SAVE_BUTTON):
            raise PublishError(f"임시저장 버튼을 찾지 못했어요. 화면: {screenshot(page, 'no_save')}")
        page.wait_for_timeout(3000)
        return {"result": "draft", "url": page.url, "failed_photos": failed, "warnings": warnings}

    if not tags_ok:
        warnings.append("태그 칸을 찾지 못해 태그 없이 발행했어요.")
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
