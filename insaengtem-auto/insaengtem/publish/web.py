"""방법 B: 브라우저 자동화(Playwright) — 11/3 손으로 성공한 클릭 순서를 그대로 옮김 (docs/DESIGN.md 5-6).

- 로그인·2단계 인증은 사람이 1회: `python -m insaengtem login` 으로 전용 크롬 프로필에 로그인해 둔다.
- 예약은 각 서비스의 '예약' 기능을 써서 주간 묶음으로 미리 걸어둔다 → PC 가 게시 시각에 켜져 있을 필요 없음.
- 모든 입력은 입력 후 화면 텍스트를 다시 읽어 **원문과 대조**(11/3 '바꿈어요' 사고 재발 방지).
⚠️ UI 문구/구조가 바뀌면 셀렉터 수정 필요. 실패 시 스크린샷을 out/web_errors/ 에 남긴다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..config import OUT, ROOT, env, parse_when

ERR = OUT / "web_errors"


class WebError(RuntimeError):
    pass


def _ctx(p, headless=False):
    return p.chromium.launch_persistent_context(
        str(ROOT / env("CHROME_PROFILE_DIR", "chrome-profile-insaengtem")), channel=env("CHROME_CHANNEL") or None,
        headless=headless, locale="ko-KR", timezone_id="Asia/Seoul", viewport={"width": 1400, "height": 1000})


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _shot(page, name: str):
    ERR.mkdir(parents=True, exist_ok=True)
    path = ERR / f"{datetime.now():%m%d_%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    return path


def _type_and_verify(page, box, text: str, where: str):
    box.click()
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln:
            page.keyboard.insert_text(ln)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")
    page.wait_for_timeout(400)
    got = box.inner_text()
    if _norm(got) != _norm(text):
        _shot(page, f"verify_{where}")
        raise WebError(f"[{where}] 입력 대조 불일치\n원문: {_norm(text)[:120]}\n화면: {_norm(got)[:120]}")


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _ctx(p)
        for url in ("https://www.threads.com/", "https://business.facebook.com/latest/home", "https://yo-go.co.kr/"):
            ctx.new_page().goto(url)
        import sys
        if sys.stdin and sys.stdin.isatty():
            input("세 탭에서 로그인(2단계 인증 포함)을 마치고 Enter 를 누르세요… ")
        else:  # 관리 프로그램에서 실행: 브라우저 창을 닫으면 끝
            print("세 탭에서 로그인을 마친 뒤 브라우저 창을 닫으세요.", flush=True)
            while ctx.pages:
                ctx.pages[0].wait_for_timeout(1000)
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ Threads
def schedule_threads(posts: list[dict], headless: bool = False) -> list[dict]:
    """posts: [{id, when_kst, video(rel|None), text, reply(링크 치환 완료)}]"""
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        ctx = _ctx(p, headless)
        page = ctx.new_page()
        for post in posts:
            try:
                _threads_one(page, post)
                results.append({"id": post["id"], "ok": True})
            except Exception as e:  # noqa: BLE001
                shot = _shot(page, f"threads_{post['id']}")
                results.append({"id": post["id"], "ok": False, "error": f"{e} (스크린샷 {shot.name})"})
            page.wait_for_timeout(6000)   # 예약 직후 바로 새 작성창 열면 안 열리는 경우 → 5~7초 대기
        ctx.close()
    return results


def _threads_one(page, post: dict):
    page.goto("https://www.threads.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    for _ in range(3):
        page.get_by_text(re.compile("새로운 소식을 공유|What's new")).first.click()
        if page.get_by_role("dialog").count():
            break
        page.wait_for_timeout(2000)
    dlg = page.get_by_role("dialog").last
    boxes = dlg.locator("[contenteditable='true']")
    if post.get("video"):
        dlg.locator("input[type=file]").first.set_input_files(str(ROOT / post["video"]))
        page.wait_for_timeout(4000)
    _type_and_verify(page, boxes.first, post["text"], "threads_text")
    if post.get("reply"):
        dlg.get_by_text(re.compile("스레드에 추가|Add to thread")).first.click()
        page.wait_for_timeout(800)
        _type_and_verify(page, dlg.locator("[contenteditable='true']").last, post["reply"], "threads_reply")
    # 우상단 … → 예약…  (첫 클릭은 자주 무시됨 → 달력 뜰 때까지 재클릭)
    when = parse_when(post["when_kst"])
    for _ in range(5):
        dlg.get_by_role("button", name=re.compile("더 보기|More")).first.click()
        page.get_by_text(re.compile("^예약|Schedule")).first.click()
        page.wait_for_timeout(1200)
        if page.get_by_role("grid").count() or page.locator("[aria-label*='달력'], [role=grid]").count():
            break
    else:
        raise WebError("예약 달력이 열리지 않음")
    page.get_by_role("gridcell", name=re.compile(rf"\b{when.day}\b")).first.click()
    hh, mm = page.get_by_placeholder("hh").first, page.get_by_placeholder("mm").first
    hh.fill(f"{when.hour:02d}")
    mm.fill(f"{when.minute:02d}")
    page.get_by_role("button", name=re.compile("완료|Done")).first.click()
    banner = _norm(dlg.inner_text())
    want = f"{when.hour % 12 or 12}:{when.minute:02d}"
    if want not in banner:
        raise WebError(f"예약 배너 확인 실패: '{want}' 없음")
    dlg.get_by_role("button", name=re.compile("^예약$|^Schedule$")).last.click()
    page.wait_for_timeout(2500)


# ------------------------------------------------------------------ Instagram (Meta Business Suite)
PATCH_FILE_INPUT = """
(() => { const orig = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type === 'file') { if (!this.isConnected) document.body.appendChild(this); return; }
    return orig.call(this); }; })();
"""


def schedule_instagram(posts: list[dict], headless: bool = False) -> list[dict]:
    from playwright.sync_api import sync_playwright
    asset, biz = env("META_ASSET_ID", required=True), env("META_BUSINESS_ID", required=True)
    url = f"https://business.facebook.com/latest/reels_composer/?asset_id={asset}&business_id={biz}"
    results = []
    with sync_playwright() as p:
        ctx = _ctx(p, headless)
        page = ctx.new_page()
        for post in posts:
            try:
                _ig_one(page, url, post)
                results.append({"id": post["id"], "ok": True})
            except Exception as e:  # noqa: BLE001
                shot = _shot(page, f"ig_{post['id']}")
                results.append({"id": post["id"], "ok": False, "error": f"{e} (스크린샷 {shot.name})"})
        ctx.close()
    return results


def _ig_one(page, url: str, post: dict):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    video = str(ROOT / post["video"])
    try:  # 1순위: file chooser 이벤트
        with page.expect_file_chooser(timeout=5000) as fc:
            page.get_by_text(re.compile("Add video|동영상 추가")).first.click()
        fc.value.set_files(video)
    except Exception:  # noqa: BLE001  2순위: click 패치 후 붙은 input 에 직접
        page.evaluate(PATCH_FILE_INPUT)
        page.get_by_text(re.compile("Add video|동영상 추가")).first.click()
        page.locator("input[type=file]").last.set_input_files(video)
    page.get_by_text(re.compile("100%")).first.wait_for(timeout=300000)
    box = page.locator("[contenteditable='true']").first
    _type_and_verify(page, box, post["text"], "ig_caption")
    for _ in range(2):
        page.get_by_role("button", name=re.compile("^Next$|^다음$")).first.click()
        page.wait_for_timeout(2500)
    page.get_by_text(re.compile("^Schedule$|^예약$")).first.click()
    when = parse_when(post["when_kst"])
    date_box = page.get_by_placeholder(re.compile("mm/dd/yyyy")).first
    date_box.click(); page.keyboard.press("Control+A"); date_box.type(when.strftime("%m/%d/%Y"))
    page.keyboard.press("Escape")
    for name, val in (("hours", f"{when.hour % 12 or 12:02d}"), ("minutes", f"{when.minute:02d}"),
                      ("meridiem", "P" if when.hour >= 12 else "A")):
        sb = page.get_by_role("spinbutton", name=re.compile(name, re.I)).first
        sb.click(); page.keyboard.type(val)
    body = _norm(page.inner_text("body"))
    if when.strftime("%m/%d/%Y") not in body and f"{when.month}/{when.day}" not in body:
        raise WebError("예약 날짜 표시 확인 실패")
    page.get_by_role("button", name=re.compile("^Schedule$|^예약$")).last.click()
    page.wait_for_timeout(4000)
