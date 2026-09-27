"""3단계: 글 파일을 네이버 블로그에 발행한다.

따로 실행하기(직접 쓴 글을 올릴 때):  python publish.py posts/글파일.txt
글 파일 형식: 첫 줄은 제목, 둘째 줄부터 본문.
"""
import os
import sys

from common import BLOG_ID, is_logged_in, open_browser, read_post

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


def type_text(page, text):
    """사람이 타자 치듯 한 줄씩 입력한다. 빈 줄은 문단 띄우기가 된다."""
    for line in text.splitlines():
        if line.strip():
            page.keyboard.type(line.strip(), delay=10)
        page.keyboard.press("Enter")


def publish_post(page, title, body, auto=False):
    """글쓰기 화면을 열어 제목·본문을 입력하고 발행한다. 발행했으면 True."""
    page.goto(write_url(), wait_until="domcontentloaded")
    editor = find_editor(page)
    if editor is None:
        print("글쓰기 화면을 찾지 못했어요. 로그인 상태와 .env의 BLOG_ID를 확인하세요.")
        return False

    page.wait_for_timeout(1500)
    for selector in POPUP_CLOSE:
        click_first(editor, [selector], timeout=1500)

    print("제목 입력 중...")
    if not click_first(editor, TITLE_AREA):
        print("제목 칸을 찾지 못했어요.")
        return False
    page.keyboard.type(title, delay=10)

    print("본문 입력 중... (글이 길면 1~2분 걸려요)")
    if not click_first(editor, BODY_AREA):
        print("본문 칸을 찾지 못했어요.")
        return False
    type_text(page, body)

    if not auto:
        answer = input("\n크롬 창에서 글을 확인하세요. 발행하려면 Enter, 그만두려면 n: ").strip().lower()
        if answer == "n":
            input("발행하지 않았어요. 창에서 직접 고치거나 저장한 뒤 Enter를 누르면 창이 닫혀요... ")
            return False

    if not click_first(editor, PUBLISH_BUTTON):
        print("발행 버튼을 찾지 못했어요. 창에서 직접 발행한 뒤 Enter를 누르세요.")
        input()
        return False
    page.wait_for_timeout(1500)  # 발행 설정 창이 뜰 때까지 대기
    if not click_first(editor, CONFIRM_BUTTON, pick_last=True):
        print("발행 확인 버튼을 찾지 못했어요. 창에서 직접 '발행'을 누른 뒤 Enter를 누르세요.")
        input()
        return False

    # 발행되면 에디터가 사라지고 글 보기 화면으로 바뀐다
    for _ in range(30):
        page.wait_for_timeout(1000)
        if find_editor(page, seconds=1) is None:
            print("발행 완료!")
            return True
    print("발행이 끝났는지 확인하지 못했어요. 블로그에서 직접 확인해 주세요.")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python publish.py posts/글파일.txt")
        sys.exit(1)
    title, body = read_post(sys.argv[1])
    with open_browser() as page:
        if not is_logged_in(page):
            print("먼저 python login.py 로 로그인해 주세요.")
            sys.exit(1)
        publish_post(page, title, body, auto=os.getenv("AUTO_PUBLISH") == "1")
