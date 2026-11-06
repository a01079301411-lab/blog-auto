"""실측 수집기 (스펙 7장). 모두 '읽기 전용' — 좋아요·댓글·팔로우 등 쓰기 동작은 하지 않는다.

- 유튜브: 영상 상세(조회·좋아요·댓글·게시일·길이·설명·유료광고·쇼핑태그), 채널 최근 영상/쇼츠 조회수
- 틱톡: 영상/사진 상세(재생·좋아요·댓글·공유·저장·음원·길이), 계정 최근 영상 재생수·팔로워·바이오 링크
- 인스타: 게시물 상세·계정 최근 게시물(로그인 세션 쿠키 IG_SESSIONID 필요, GET만)
- 후킹 프레임: yt-dlp + ffmpeg로 0.5초 지점 캡처
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

from .fmt import fmt_count, parse_count

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE_HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
_last_tiktok = 0.0


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _get(url: str, headers: dict | None = None, cookies: dict | None = None, tries: int = 3,
         min_len: int = 200) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={**BASE_HEADERS, **(headers or {})}, cookies=cookies, timeout=25)
            if r.status_code == 200 and len(r.content) >= min_len:
                return r
            last = RuntimeError(f"HTTP {r.status_code}, {len(r.content)}바이트")
        except requests.RequestException as e:
            last = e
        time.sleep(2 * (i + 1) + random.random() * 2)
    raise RuntimeError(f"{url} 가져오기 실패: {last}")


def _json_after(html: str, marker: str):
    """'marker = {...};' 형태의 JSON을 잘라서 파싱."""
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find("{", i)
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[j:])
        return obj
    except ValueError:
        return None


def _walk(o, key: str):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key)


def _txt(o) -> str:
    if o is None:
        return ""
    if isinstance(o, str):
        return o
    if "simpleText" in o:
        return o["simpleText"]
    if "content" in o and isinstance(o["content"], str):
        return o["content"]
    if "runs" in o:
        return "".join(r.get("text", "") for r in o["runs"])
    return ""


# ----------------------------------------------------------------- 유튜브
def youtube_id(url: str) -> str:
    u = urlparse(url if "://" in url else "https://" + url)
    if u.hostname and "youtu.be" in u.hostname:
        return u.path.strip("/").split("/")[0]
    m = re.search(r"/(?:shorts|live|embed)/([\w-]{11})", u.path)
    if m:
        return m.group(1)
    v = parse_qs(u.query).get("v")
    if v:
        return v[0]
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    raise ValueError(f"유튜브 영상 ID를 찾지 못함: {url}")


def youtube_video(url: str) -> dict:
    vid = youtube_id(url)
    html = _get(f"https://www.youtube.com/watch?v={vid}&hl=ko&gl=KR",
                cookies={"CONSENT": "YES+1"}).text
    pr = _json_after(html, "ytInitialPlayerResponse") or {}
    vd = pr.get("videoDetails", {})
    mf = pr.get("microformat", {}).get("playerMicroformatRenderer", {})
    likes = None
    m = re.search(r"다른 사용자 ([\d,.]+[만천]?)명", html) or re.search(r"along with ([\d,]+) other", html)
    if m:
        likes = parse_count(m.group(1))
    if likes is None:
        m = re.search(r'"likeCount":"?(\d+)', html)
        likes = int(m.group(1)) if m else None
    comments = None
    m = re.search(r'"contextualInfo":\{"runs":\[\{"text":"([^"]+)"', html)
    if m:
        comments = parse_count(m.group(1))
    shop = re.search(r"(\d+)개 제품", html)
    views = int(vd["viewCount"]) if vd.get("viewCount") else None
    desc = vd.get("shortDescription", "")
    return {
        "platform": "유튜브",
        "url": f"https://www.youtube.com/watch?v={vid}",
        "is_shorts": "/shorts/" in url or (int(vd.get("lengthSeconds") or 999) <= 180 and "#shorts" in desc.lower()),
        "title": vd.get("title"),
        "channel": vd.get("author"),
        "channel_url": mf.get("ownerProfileUrl"),
        "published": mf.get("publishDate") or mf.get("uploadDate"),
        "length_sec": int(vd.get("lengthSeconds") or 0),
        "views": views, "views_fmt": fmt_count(views),
        "likes": likes, "likes_fmt": fmt_count(likes) if likes is not None else "미확인(좋아요 숨김 또는 파싱 실패)",
        "comments": comments, "comments_fmt": fmt_count(comments) if comments is not None else "미확인",
        "paid_promotion": "paidContentOverlay" in html,
        "shopping_tag": f"{shop.group(1)}개 제품" if shop else None,
        "description": desc[:3000],
        "links_in_description": re.findall(r"https?://\S+", desc)[:20],
        "collected_at": _now(),
    }


def youtube_channel(handle_or_url: str, tab: str = "videos", limit: int = 12) -> dict:
    """채널 최근 영상(videos) 또는 쇼츠(shorts) 목록 + 조회수. 평소 대비 계산용."""
    h = handle_or_url.strip()
    if h.startswith("http"):
        path = urlparse(h).path.rstrip("/")
        path = re.sub(r"/(videos|shorts|featured|streams)$", "", path)
    else:
        path = "/" + (h if h.startswith("@") else "@" + h)
    html = _get(f"https://www.youtube.com{path}/{tab}?hl=ko&gl=KR", cookies={"CONSENT": "YES+1"}).text
    data = _json_after(html, "ytInitialData") or {}
    items = []
    for v in _walk(data, "videoRenderer"):
        items.append({"id": v.get("videoId"), "title": _txt(v.get("title")),
                      "views_text": _txt(v.get("viewCountText")), "published": _txt(v.get("publishedTimeText"))})
    for v in _walk(data, "lockupViewModel"):
        meta = v.get("metadata", {}).get("lockupMetadataViewModel", {})
        rows = []
        for r in _walk(meta, "metadataParts"):
            rows += [_txt(p.get("text")) for p in r]
        items.append({"id": v.get("contentId"), "title": _txt(meta.get("title")),
                      "views_text": next((x for x in rows if "조회" in x or "views" in x), ""),
                      "published": next((x for x in rows if "전" in x or "ago" in x), "")})
    for v in _walk(data, "shortsLockupViewModel"):
        ov = v.get("overlayMetadata", {})
        vid = next(iter(_walk(v, "videoId")), None)
        items.append({"id": vid, "title": _txt(ov.get("primaryText")),
                      "views_text": _txt(ov.get("secondaryText")), "published": ""})
    seen, out = set(), []
    for it in items:
        if not it["id"] or it["id"] in seen:
            continue
        seen.add(it["id"])
        it["views"] = parse_count(it["views_text"])
        it["url"] = (f"https://www.youtube.com/shorts/{it['id']}" if tab == "shorts"
                     else f"https://www.youtube.com/watch?v={it['id']}")
        out.append(it)
        if len(out) >= limit:
            break
    subs = re.search(r"구독자 ([\d.,]+[만천]?명)", html)
    return {"platform": "유튜브", "channel": path, "tab": tab, "subscribers": subs.group(1) if subs else None,
            "recent": out, "note": "목록 순서 = 채널 탭 최신순", "collected_at": _now()}


# ----------------------------------------------------------------- 틱톡
def _tiktok_wait():
    global _last_tiktok
    gap = time.time() - _last_tiktok
    need = random.uniform(5, 9)
    if gap < need:
        time.sleep(need - gap)
    _last_tiktok = time.time()


def _tiktok_universal(url: str) -> dict:
    _tiktok_wait()
    html = _get(url, min_len=1000).text
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("틱톡 페이지 데이터(__UNIVERSAL_DATA_FOR_REHYDRATION__)를 찾지 못함 — 잠시 후 재시도")
    return json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})


def tiktok_video(url: str) -> dict:
    url = url.replace("/photo/", "/video/")
    scope = _tiktok_universal(url)
    item = scope.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct")
    if not item:
        raise RuntimeError(f"틱톡 영상 정보를 찾지 못함(삭제·비공개·차단 가능): {url}")
    st = item.get("statsV2") or item.get("stats") or {}
    g = lambda k: int(st.get(k)) if st.get(k) is not None else None  # noqa: E731
    music = item.get("music", {})
    created = dt.datetime.fromtimestamp(int(item.get("createTime", 0))).strftime("%Y-%m-%d")
    return {
        "platform": "틱톡",
        "url": url, "author": item.get("author", {}).get("uniqueId"),
        "desc": item.get("desc"), "published": created,
        "is_photo": bool(item.get("imagePost")),
        "length_sec": item.get("video", {}).get("duration"),
        "views": g("playCount"), "likes": g("diggCount"), "comments": g("commentCount"),
        "shares": g("shareCount"), "saves": g("collectCount"),
        "stats_fmt": " / ".join(fmt_count(g(k)) for k in ("playCount", "diggCount", "commentCount", "shareCount")),
        "music": f"{music.get('title')} - {music.get('authorName')}",
        "anchors": [a.get("description") or a.get("keyword") for a in item.get("anchors", []) or []],
        "is_ad": bool(item.get("isAd")) or bool(item.get("brandOrganicType")),
        "collected_at": _now(),
    }


def tiktok_user(handle: str, limit: int = 12) -> dict:
    h = handle.strip().lstrip("@").split("/")[-1].lstrip("@")
    info: dict = {"platform": "틱톡", "account": "@" + h}
    try:
        scope = _tiktok_universal(f"https://www.tiktok.com/@{h}")
        ui = scope.get("webapp.user-detail", {}).get("userInfo", {})
        u, s = ui.get("user", {}), ui.get("stats", {})
        info.update({"nickname": u.get("nickname"), "bio": u.get("signature"),
                     "bio_link": (u.get("bioLink") or {}).get("link"),
                     "followers": s.get("followerCount"), "followers_fmt": fmt_count(s.get("followerCount")),
                     "videos": s.get("videoCount"), "total_likes": s.get("heartCount")})
    except Exception as e:  # 프로필은 실패해도 임베드로 최근 영상은 시도
        info["profile_error"] = str(e)
    _tiktok_wait()
    html = _get(f"https://www.tiktok.com/embed/@{h}", min_len=500).text
    recent = []
    for m in re.finditer(r'"playCount":(\d+)', html):
        before = html[max(0, m.start() - 6000):m.start()]
        ids = re.findall(r'"id":"(\d{15,})"', before)
        descs = re.findall(r'"desc":"((?:[^"\\]|\\.)*)"', before)
        if not ids:
            continue
        vid = ids[-1]
        if any(r["id"] == vid for r in recent):
            continue
        recent.append({"id": vid, "url": f"https://www.tiktok.com/@{h}/video/{vid}",
                       "desc": json.loads(f'"{descs[-1]}"')[:80] if descs else "",
                       "views": int(m.group(1)), "views_fmt": fmt_count(int(m.group(1)))})
        if len(recent) >= limit:
            break
    info["recent"] = recent
    info["note"] = "임베드 목록 순서(대체로 최신순, 고정 영상 포함 가능)"
    info["collected_at"] = _now()
    return info


# ----------------------------------------------------------------- 인스타그램
IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
IG_HEADERS = {"X-IG-App-ID": "936619743392459", "X-Requested-With": "XMLHttpRequest",
              "Referer": "https://www.instagram.com/"}


def ig_shortcode_to_id(code: str) -> str:
    n = 0
    for ch in code:
        n = n * 64 + IG_ALPHABET.index(ch)
    return str(n)


def _ig_cookies() -> dict:
    sid = os.environ.get("IG_SESSIONID")
    if not sid:
        raise RuntimeError("인스타 수집에는 로그인 세션이 필요합니다: 환경변수 IG_SESSIONID(브라우저 쿠키 sessionid 값) 설정. "
                           "없으면 web_search/web_fetch나 성민 앱 화면 캡처로 대체")
    c = {"sessionid": sid}
    if os.environ.get("IG_DS_USER_ID"):
        c["ds_user_id"] = os.environ["IG_DS_USER_ID"]
    if os.environ.get("IG_CSRFTOKEN"):
        c["csrftoken"] = os.environ["IG_CSRFTOKEN"]
    return c


def _ig_item(it: dict) -> dict:
    views = it.get("play_count") or it.get("ig_play_count") or it.get("view_count")
    cap = (it.get("caption") or {}).get("text", "") if it.get("caption") else ""
    code = it.get("code")
    kind = {1: "피드(사진)", 2: "릴스/영상", 8: "피드(캐러셀)"}.get(it.get("media_type"), str(it.get("media_type")))
    return {
        "platform": "인스타그램", "url": f"https://www.instagram.com/{'reel' if it.get('product_type') == 'clips' else 'p'}/{code}/",
        "type": kind, "product_type": it.get("product_type"),
        "author": (it.get("user") or {}).get("username"),
        "published": dt.datetime.fromtimestamp(it.get("taken_at", 0)).strftime("%Y-%m-%d"),
        "views": views, "views_fmt": fmt_count(views) if views else "웹 비공개(캐러셀·사진은 앱에서 확인)",
        "likes": it.get("like_count"), "comments": it.get("comment_count"),
        "reposts": it.get("media_repost_count"),
        "shares": "웹 비공개 — 앱 릴스 화면 리포스트 옆 숫자로 확인",
        "length_sec": it.get("video_duration"),
        "paid_partnership": bool(it.get("is_paid_partnership")),
        "sponsors": [s.get("username") for s in (it.get("sponsor_tags") or []) if isinstance(s, dict)],
        "caption": cap[:2500],
    }


def instagram_media(url: str) -> dict:
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([\w-]+)", url)
    if not m:
        raise ValueError(f"인스타 게시물 주소가 아님: {url}")
    if not os.environ.get("IG_SESSIONID"):
        return instagram_media_public(url)
    mid = ig_shortcode_to_id(m.group(1))
    r = _get(f"https://www.instagram.com/api/v1/media/{mid}/info/", headers=IG_HEADERS, cookies=_ig_cookies(), min_len=50)
    items = r.json().get("items") or []
    if not items:
        raise RuntimeError("인스타 게시물 정보 없음(삭제·비공개·세션 만료)")
    out = _ig_item(items[0])
    out["collected_at"] = _now()
    return out


def instagram_media_public(url: str) -> dict:
    """로그인 없이: 게시물 페이지 og 메타('좋아요 1,234개, 댓글 56개 - 계정 날짜: 캡션')에서 좋아요·댓글·캡션."""
    code = re.search(r"/(?:p|reel|reels|tv)/([\w-]+)", url).group(1)
    html = _get(f"https://www.instagram.com/p/{code}/", headers={"User-Agent": "facebookexternalhit/1.1"}, min_len=500).text
    m = re.search(r'<meta (?:property|name)="og:description" content="([^"]*)"', html) or \
        re.search(r'<meta (?:property|name)="description" content="([^"]*)"', html)
    if not m:
        raise RuntimeError("인스타 공개 페이지에서 수치를 찾지 못함(로그인 벽) — IG_SESSIONID 설정 후 재시도")
    import html as _h
    desc = _h.unescape(m.group(1))
    likes = re.search(r"([\d,.]+[KkMm만천]?)\s*(?:likes|좋아요|명이 좋아)", desc) or re.search(r"좋아요\s*([\d,.]+[만천]?)", desc)
    comments = re.search(r"([\d,.]+[KkMm만천]?)\s*(?:comments|댓글)", desc) or re.search(r"댓글\s*([\d,.]+[만천]?)", desc)
    lk = parse_count(likes.group(1)) if likes else None
    cm = parse_count(comments.group(1)) if comments else None
    return {"platform": "인스타그램", "url": url, "source": "공개 페이지 og:description(로그인 없음)",
            "likes": lk, "likes_fmt": fmt_count(lk) if lk is not None else "미확인",
            "comments": cm, "comments_fmt": fmt_count(cm) if cm is not None else "미확인",
            "views": "웹 비로그인에서는 조회수 미노출", "summary": desc[:1500], "collected_at": _now()}


def youtube_post(url: str) -> dict:
    """유튜브 커뮤니티 게시물(/post/ID): 본문·좋아요·댓글·첨부 링크."""
    pid = re.search(r"/post/([\w-]+)", url).group(1)
    html = _get(f"https://www.youtube.com/post/{pid}?hl=ko&gl=KR", cookies={"CONSENT": "YES+1"}).text
    data = _json_after(html, "ytInitialData") or {}
    post = next(iter(_walk(data, "backstagePostRenderer")), {}) or {}
    text = _txt(post.get("contentText"))
    likes = _txt(post.get("voteCount"))
    author = _txt(post.get("authorText"))
    published = _txt(post.get("publishedTimeText"))
    links = re.findall(r"https?://[^\s\"]+", text)
    for ep in _walk(post, "urlEndpoint"):
        if isinstance(ep, dict) and ep.get("url"):
            links.append(ep["url"])
    cm = re.search(r"댓글\s*([\d,.]+[만천]?)개", html)
    return {"platform": "유튜브 커뮤니티", "url": url, "author": author, "published": published,
            "likes": parse_count(likes), "likes_fmt": likes or "미확인",
            "comments": parse_count(cm.group(1)) if cm else None, "comments_fmt": cm.group(1) if cm else "미확인",
            "text": text[:3000], "links": list(dict.fromkeys(links))[:20],
            "has_poll": bool(post.get("backstageAttachment", {}).get("pollRenderer")) if isinstance(post.get("backstageAttachment"), dict) else False,
            "collected_at": _now()}


def instagram_user(username: str, limit: int = 12) -> dict:
    u = username.strip().lstrip("@").strip("/").split("/")[-1]
    ck = _ig_cookies()
    r = _get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={u}", headers=IG_HEADERS, cookies=ck, min_len=50)
    try:
        user = r.json()["data"]["user"]
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"프로필 API가 JSON을 주지 않음({e}) — 세션 확인 또는 다른 방법 사용")
    uid = user["id"]
    r2 = _get(f"https://www.instagram.com/api/v1/feed/user/{uid}/?count={limit}", headers=IG_HEADERS, cookies=ck, min_len=50)
    feed = [_ig_item(it) for it in r2.json().get("items", [])]
    reels = [x for x in feed if x["product_type"] == "clips"]
    return {
        "platform": "인스타그램", "account": "@" + u, "full_name": user.get("full_name"),
        "bio": user.get("biography"),
        "bio_links": [b.get("url") for b in user.get("bio_links", [])],
        "followers": (user.get("edge_followed_by") or {}).get("count"),
        "followers_fmt": fmt_count((user.get("edge_followed_by") or {}).get("count")),
        "posts": (user.get("edge_owner_to_timeline_media") or {}).get("count"),
        "recent": [{k: x[k] for k in ("url", "type", "published", "views", "views_fmt", "likes", "comments")} for x in feed],
        "recent_reels_views": [x["views"] for x in reels if x["views"]],
        "note": "고정 게시물이 앞에 올 수 있음 → 게시일 기준 최신순으로 비교",
        "collected_at": _now(),
    }


# ----------------------------------------------------------------- 공통
def collect(url: str) -> dict:
    """주소 종류를 보고 알맞은 수집기를 고른다."""
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    if "youtu" in host:
        if "/post/" in url:
            return youtube_post(url)
        if re.search(r"/(watch|shorts|live|embed)|youtu\.be", url):
            return youtube_video(url)
        return youtube_channel(url, "shorts" if url.rstrip("/").endswith("shorts") else "videos")
    if "tiktok" in host:
        if "/video/" in url or "/photo/" in url:
            return tiktok_video(url)
        return tiktok_user(url)
    if "instagram" in host:
        if re.search(r"/(p|reel|reels|tv)/", url):
            return instagram_media(url)
        return instagram_user(url)
    raise ValueError("유튜브·틱톡·인스타 주소만 직접 수집합니다. 그 밖의 페이지는 web_fetch 사용")


def hook_frame(url: str, seconds: float = 0.5, outdir: str | None = None) -> str:
    """영상 0.5초 지점 프레임 PNG 경로 (yt-dlp + ffmpeg 필요). 인스타는 IG 쿠키 파일 필요할 수 있음."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        try:
            import yt_dlp  # noqa: F401
            ytdlp = None
        except ImportError:
            raise RuntimeError("yt-dlp가 없습니다: pip install yt-dlp")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg가 없습니다 (https://ffmpeg.org 설치 후 PATH 등록)")
    tmp = Path(tempfile.mkdtemp(prefix="hook_"))
    cmd = ([ytdlp] if ytdlp else ["python", "-m", "yt_dlp"]) + [
        "-f", "best[height<=720]/best", "--download-sections", "*0-3", "-o", str(tmp / "clip.%(ext)s"), url]
    cookies = os.environ.get("YTDLP_COOKIES")  # 인스타 등 로그인 필요한 경우 cookies.txt 경로
    if cookies:
        cmd[1:1] = ["--cookies", cookies]
    subprocess.run(cmd, check=False, capture_output=True, timeout=180)
    clips = list(tmp.glob("clip.*"))
    if not clips:
        raise RuntimeError("영상 다운로드 실패(비공개·로그인 필요·차단) — 성민 앱 화면 캡처로 대체")
    out = Path(outdir or tmp) / f"hook_{abs(hash(url)) % 10**8}.png"
    subprocess.run(["ffmpeg", "-y", "-ss", str(seconds), "-i", str(clips[0]), "-frames:v", "1",
                    "-vf", "scale='min(540,iw)':-2", str(out)], check=False, capture_output=True, timeout=60)
    if not out.exists():
        raise RuntimeError("프레임 추출 실패")
    return str(out)
