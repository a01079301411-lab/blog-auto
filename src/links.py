"""내부링크 후보 찾기: 사장님 블로그에 이미 있는 글 중 이번 주제와 관련된 글을 고른다.

글 목록은 세 곳에서 모은다.
1. 네이버 블로그 RSS (최근 글 자동 수집)
2. data/links.md (사장님이 직접 적어 둔 중요한 글)
3. 이 프로그램으로 발행한 글 (data/history.json)
"""
import json
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET

import history
from config import BLOG_ID, DATA_DIR

log = logging.getLogger(__name__)

CACHE_FILE = DATA_DIR / "links_cache.json"  # RSS를 못 읽을 때 마지막으로 읽은 목록을 쓴다
MANUAL_FILE = DATA_DIR / "links.md"
MAX_CANDIDATES = 5
POST_URL_RE = re.compile(r"blog\.naver\.com/[^/?]+/\d+|logNo=\d+")
# 관련도 계산에서 빼는 흔한 말
COMMON = {"대구", "이사", "업체", "방법", "이유", "가지", "정리"}


def _from_rss():
    if not BLOG_ID:
        return []
    url = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            root = ET.fromstring(response.read())
    except Exception as e:
        log.warning("블로그 글 목록(RSS)을 읽지 못했어요: %s", e)
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return []
    posts = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").split("?")[0].strip()
        if title and link:
            posts.append({"title": title, "url": link})
    CACHE_FILE.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    return posts


def _from_manual_file():
    """data/links.md 의 표: | 제목 | 주소 |"""
    if not MANUAL_FILE.exists():
        return []
    posts = []
    for line in MANUAL_FILE.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 2 and cells[1].startswith("http"):
            posts.append({"title": cells[0], "url": cells[1]})
    return posts


def _from_history():
    return [
        {"title": r["title"], "url": r["url"]}
        for r in history.load()
        if r.get("result") == "published" and POST_URL_RE.search(r.get("url", ""))
    ]


def _words(text):
    """관련도를 재기 위한 두 글자 묶음. (실내보관이사 → 실내, 내보, 보관, 관이, 이사)"""
    grams = set()
    for word in re.findall(r"[가-힣]+", text):
        grams |= {word[i:i + 2] for i in range(len(word) - 1)}
    return grams - COMMON


def related(topic):
    """이번 주제와 관련 있는 기존 글을 최대 5개 돌려준다. [{'title', 'url'}, ...]"""
    posts, seen = [], set()
    for post in _from_manual_file() + _from_rss() + _from_history():
        if post["url"] not in seen:
            seen.add(post["url"])
            posts.append(post)

    target = _words(topic["topic"] + " " + topic["keyword"] + " " + topic["question"])
    scored = []
    for post in posts:
        score = len(target & _words(post["title"]))
        if score >= 2:  # 관련 없는 글(다른 주제 글)은 넣지 않는다
            scored.append((score, post))
    scored.sort(key=lambda x: -x[0])
    return [post for _, post in scored[:MAX_CANDIDATES]]


def describe(candidates):
    """AI에게 보여줄 내부링크 후보 목록."""
    if not candidates:
        return "(관련 글 없음. [링크:...] 표시를 쓰지 않는다.)"
    return "\n".join(f"{i}. {c['title']}" for i, c in enumerate(candidates, 1))
