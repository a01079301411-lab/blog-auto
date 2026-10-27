"""검색 성과 확인: 사장님 컴퓨터에서 네이버를 직접 검색해서 확인한다.

1. 누락 확인: 올린 글의 제목으로 블로그 검색을 해서 내 글이 나오는지
2. 키워드 순위: 글의 메인 키워드로 블로그 검색을 해서 내 블로그 글이 몇 번째인지
3. 플레이스: 회사 이름으로 검색했을 때 전화번호와 지도(플레이스)가 보이는지
4. 키워드 검색량: .env에 네이버 검색광고 API 키가 있으면 주제표 키워드의 월 검색량과 경쟁 정도

결과는 output/검색성과_날짜.md 와 텔레그램으로 보낸다.
매일 자동 실행 끝에 1번만 가볍게 돌고, 5_검색성과확인.bat 으로 직접 돌리면 전부 확인한다.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import history
import notifier
import topics
from config import BLOG_ID, COMPANY_PHONE, DATA_DIR, OUTPUT_DIR

log = logging.getLogger("seo")

STATUS_FILE = DATA_DIR / "seo_status.json"  # 글마다 검색에 나왔는지 기록 (다시 확인하지 않게)
BLOG_SEARCH = "https://search.naver.com/search.naver?ssc=tab.blog.all&query={q}"
TOTAL_SEARCH = "https://search.naver.com/search.naver?query={q}"
COMPANY_NAME = "대구토탈홈서비스 로젠이사"
# 검색 결과 안의 블로그 글 주소 (두 가지 모양)
POST_RE = re.compile(
    r"blog\.naver\.com/(?:PostView\.naver\?blogId=)?([A-Za-z0-9_-]+)(?:/|&(?:amp;)?logNo=)(\d{9,})"
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
CHECK_DAYS = 30  # 최근 이 기간에 올린 글만 확인한다
MAX_TRIES = 7  # 같은 글은 이 횟수까지만 누락 확인 (그 뒤엔 누락으로 본다)


# ── 네이버 검색 ──

def _html(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    for _ in range(3):  # 블로그 검색은 아래로 내리면 더 나온다
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)
    time.sleep(random.uniform(2, 4))  # 사람처럼 천천히 (너무 빠르면 네이버가 막을 수 있다)
    return page.content()


def _posts(html):
    """검색 결과에 나온 블로그 글 순서 [(블로그 아이디, 글 번호), ...]."""
    seen = []
    for blog, number in POST_RE.findall(html):
        if (blog.lower(), number) not in seen:
            seen.append((blog.lower(), number))
    return seen


def _my_rank(html):
    """검색 결과 블로그 글 중 내 블로그 글의 순위와 그 글 번호. 없으면 (None, None)."""
    for i, (blog, number) in enumerate(_posts(html), 1):
        if blog == BLOG_ID.lower():
            return i, number
    return None, None


def _blocked(html):
    return "자동입력 방지" in html or "captcha" in html.lower()


# ── 상태 기록 ──

def _load_status():
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_status(status):
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _recent_posts():
    since = datetime.now() - timedelta(days=CHECK_DAYS)
    posts = []
    for r in history.load():
        if r.get("result") != "published":
            continue
        when = datetime.strptime(r["date"], "%Y-%m-%d %H:%M")
        if when >= since and r.get("title"):
            posts.append({**r, "_when": when})
    return posts


# ── 확인 항목 ──

def check_indexing(page, status):
    """하루 이상 지난 글 중 아직 검색에서 확인 못 한 글을 제목으로 검색한다."""
    rows = []
    for post in _recent_posts():
        title = post["title"]
        state = status.setdefault(title, {"tries": 0, "found": False})
        if not state["found"] and datetime.now() - post["_when"] >= timedelta(hours=20) \
                and state["tries"] < MAX_TRIES:
            html = _html(page, BLOG_SEARCH.format(q=urllib.parse.quote(title)))
            if _blocked(html):
                log.info("네이버가 자동 검색을 잠깐 막았어요. 다음에 다시 확인합니다.")
                break
            rank, _ = _my_rank(html)
            state["tries"] += 1
            state["found"] = rank is not None
            state["checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if state["found"]:
            mark = "검색에 나옴"
        elif state["tries"] >= MAX_TRIES:
            mark = "누락 (7번 확인해도 안 나옴)"
        elif state["tries"]:
            mark = f"아직 안 나옴 ({state['tries']}번 확인)"
        else:
            mark = "확인 전 (올린 지 하루가 안 됨)"
        rows.append((post["date"][:10], title, mark))
    return rows


def check_ranks(page):
    """최근 글의 메인 키워드로 블로그 검색 순위를 본다."""
    rows, done = [], set()
    for post in _recent_posts():
        keyword = post.get("keyword")
        if not keyword or keyword in done:
            continue
        done.add(keyword)
        html = _html(page, BLOG_SEARCH.format(q=urllib.parse.quote(keyword)))
        if _blocked(html):
            log.info("네이버가 자동 검색을 잠깐 막았어요. 순위 확인을 멈춥니다.")
            break
        rank, _ = _my_rank(html)
        shown = len(_posts(html))
        rows.append((keyword, f"{rank}위" if rank else f"{shown}위 안에 없음"))
    return rows


def check_place(page):
    html = _html(page, TOTAL_SEARCH.format(q=urllib.parse.quote(COMPANY_NAME)))
    digits = re.sub(r"\D", "", COMPANY_PHONE)
    phone_shown = bool(digits) and (COMPANY_PHONE in html or digits in re.sub(r"\D", "", html))
    place_shown = "map.naver.com" in html or "place.naver.com" in html or "pcmap.place" in html
    blog_shown = BLOG_ID.lower() in html.lower()
    return {"전화번호가 보임": phone_shown, "지도(플레이스) 영역이 보임": place_shown, "블로그가 보임": blog_shown}


# ── 키워드 검색량 (네이버 검색광고 API, 선택) ──

def _ad_keys():
    keys = (os.getenv("NAVER_AD_CUSTOMER_ID", ""), os.getenv("NAVER_AD_API_KEY", ""), os.getenv("NAVER_AD_SECRET", ""))
    return keys if all(k.strip() for k in keys) else None


def _ad_request(keys, hints):
    customer, api_key, secret = (k.strip() for k in keys)
    uri = "/keywordstool"
    stamp = str(int(time.time() * 1000))
    sign = base64.b64encode(hmac.new(secret.encode(), f"{stamp}.GET.{uri}".encode(), hashlib.sha256).digest()).decode()
    query = urllib.parse.urlencode({"hintKeywords": ",".join(hints), "showDetail": "1"})
    request = urllib.request.Request(
        f"https://api.searchad.naver.com{uri}?{query}",
        headers={"X-Timestamp": stamp, "X-API-KEY": api_key, "X-Customer": customer, "X-Signature": sign},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())["keywordList"]


def _count(value):
    return 5 if isinstance(value, str) else int(value)  # '< 10' 처럼 오면 5로 본다


def keyword_volumes():
    """주제표의 메인 키워드 월 검색량과, 같이 나온 연관 키워드 중 지역 키워드."""
    keys = _ad_keys()
    if not keys:
        return None
    all_topics, _ = topics.load_topics()
    wanted = {t["keyword"].replace(" ", ""): t["keyword"] for t in all_topics}
    found, related = {}, {}
    names = list(wanted)
    for i in range(0, len(names), 5):  # 한 번에 5개까지
        try:
            for item in _ad_request(keys, names[i:i + 5]):
                kw = item["relKeyword"]
                total = _count(item["monthlyPcQcCnt"]) + _count(item["monthlyMobileQcCnt"])
                row = (total, item.get("compIdx", ""))
                if kw in wanted:
                    found[wanted[kw]] = row
                elif re.search(r"대구|경산|칠곡|왜관|고령|수성|달서|달성", kw) and re.search(r"이사|보관|이전", kw):
                    related[kw] = row
        except Exception as e:
            log.warning("검색량을 가져오지 못했어요: %s", e)
            return None
        time.sleep(0.5)
    return found, related


# ── 실행 ──

def run(full=True):
    """full=False: 매일 자동 실행 뒤 누락 확인만. full=True: 전부."""
    from playwright.sync_api import sync_playwright

    if not BLOG_ID:
        log.info("BLOG_ID가 없어서 검색 성과 확인을 건너뜁니다.")
        return
    status = _load_status()
    report = [f"# 검색 성과 확인 ({datetime.now():%Y-%m-%d %H:%M})", ""]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA, locale="ko-KR")
        try:
            index_rows = check_indexing(page, status)
            _save_status(status)
            rank_rows = check_ranks(page) if full else []
            place = check_place(page) if full else None
        finally:
            browser.close()

    found = sum(1 for _, _, m in index_rows if m == "검색에 나옴")
    missing = [t for _, t, m in index_rows if m.startswith("누락")]
    report += ["## 1. 누락 확인 (글 제목으로 블로그 검색)", "",
               "| 올린 날 | 제목 | 결과 |", "|---|---|---|"]
    report += [f"| {d} | {t} | {m} |" for d, t, m in index_rows]
    message = [f"[검색 성과] 최근 {len(index_rows)}개 글 중 {found}개가 검색에 나와요."]
    if missing:
        message.append("누락: " + " / ".join(missing[:3]))

    if full:
        report += ["", "## 2. 키워드 순위 (블로그 검색, 내 글이 몇 번째)", "",
                   "| 메인 키워드 | 순위 |", "|---|---|"]
        report += [f"| {k} | {r} |" for k, r in rank_rows]
        ranked = [f"{k} {r}" for k, r in rank_rows if r.endswith("위") and "없음" not in r]
        message.append("순위: " + (", ".join(ranked[:5]) if ranked else "확인한 키워드에서 아직 안 보여요"))
        report += ["", f"## 3. 플레이스 ({COMPANY_NAME} 검색)", ""]
        report += [f"- {k}: {'예' if v else '아니요'}" for k, v in place.items()]
        message.append("플레이스: " + ", ".join(f"{k} {'O' if v else 'X'}" for k, v in place.items()))

        volumes = keyword_volumes()
        report += ["", "## 4. 키워드 월 검색량 (네이버 검색광고)", ""]
        if volumes is None:
            report.append("검색광고 API 키가 .env에 없어서 확인하지 못했어요. (README의 '키워드 검색량' 참고)")
        else:
            mine, related = volumes
            report += ["| 메인 키워드 | 월 검색량 | 경쟁 |", "|---|---|---|"]
            report += [f"| {k} | {v[0]:,} | {v[1]} |" for k, v in sorted(mine.items(), key=lambda x: -x[1][0])]
            report += ["", "같이 검색되는 지역 키워드 (주제 추가 후보)", "", "| 키워드 | 월 검색량 | 경쟁 |", "|---|---|---|"]
            report += [f"| {k} | {v[0]:,} | {v[1]} |" for k, v in sorted(related.items(), key=lambda x: -x[1][0])[:40]]
            message.append(f"키워드 검색량 {len(mine)}개 확인, 추가 후보 {len(related)}개")

    path = OUTPUT_DIR / f"검색성과_{datetime.now():%Y-%m-%d}.md"
    path.write_text("\n".join(report) + "\n", encoding="utf-8")
    log.info("검색 성과 보고서: %s", path)
    notifier.notify("\n".join(message) + f"\n자세한 내용: output\\{path.name}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout)])
    run(full=True)
