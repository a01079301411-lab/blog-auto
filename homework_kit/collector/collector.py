"""
COSY 숙제용 로컬 수집기 (성민 PC에서 실행)
- 성민 PC의 가정용 인터넷 + 성민이 직접 로그인한 전용 브라우저 프로필을 사용 → 로봇 차단·로그인 벽 해결
- 비밀번호·쿠키를 파일이나 코드에 넣지 않음: 처음 한 번 열린 창에서 직접 로그인하면 프로필 폴더에 남음
- 읽기 전용: 좋아요·댓글·팔로우 등 어떤 조작도 하지 않음
- 사람 속도로 천천히(요청 사이 6~10초) → 계정 제한 위험 최소화

설치(한 번):  pip install playwright openpyxl  &&  python -m playwright install chromium
로그인(한 번): python collector.py login
점검:        python collector.py check   (인스타 로그인·유튜브 차단·틱톡 상태를 실제 요청으로 확인)
(선택) 유튜브 공식 API 보조: 환경변수 YOUTUBE_API_KEY 설정 시 페이지 방식 실패할 때 자동 사용
수집:        python collector.py collect urls.txt results.json
  urls.txt 한 줄에 하나: 게시물 링크 또는 계정 링크
    https://www.youtube.com/watch?v=...      / https://www.youtube.com/shorts/...
    https://www.youtube.com/@채널              (최근 영상 목록)
    https://www.youtube.com/@채널/posts        (커뮤니티 글 최근 목록·좋아요)
    https://www.instagram.com/reel/코드/        / https://www.instagram.com/p/코드/
    https://www.instagram.com/계정/             (프로필 링크·소개글 + 최근 게시물 목록 + 릴스 탭 최근 조회수)
    https://www.tiktok.com/@계정/video/ID       / https://www.tiktok.com/@계정  (최근 10개)
    https://www.youtube.com/post/ID            (유튜브 커뮤니티 글: 좋아요·본문·링크)
    그 밖의 링크(스레드·네이버 블로그·링크트리·상품 페이지)  (화면 글자·링크·캡처)
"""
import json, random, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = Path(__file__).with_name("browser_profile")
SHOTS = Path(__file__).with_name("shots")
IG_APP_ID = "936619743392459"

def pause(a=6, b=10):
    time.sleep(random.uniform(a, b))

# ---------- 페이지 안에서 실행하는 JS (이전 숙제에서 실제로 동작 확인한 방식) ----------
JS_YT_VIDEO = r"""async (id) => {
  const t = await fetch('/watch?v=' + id).then(r => r.text());
  const m = t.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\});(?:var|<\/script)/s);
  if (!m) return {err: 'no player response'};
  const p = JSON.parse(m[1]); const v = p.videoDetails || {};
  const like = (t.match(/다른 사용자 ([\d,.]+[만천]?)명/) || [])[1] || (t.match(/along with ([\d,]+) other/) || [])[1] || null;
  const cmt = (t.match(/"contextualInfo":\{"runs":\[\{"text":"([^"]+)"/) || [])[1] || null;
  return {title: v.title, views: Number(v.viewCount), seconds: Number(v.lengthSeconds),
          date: p.microformat?.playerMicroformatRenderer?.publishDate, desc: v.shortDescription,
          channel: v.author, likes: like, comments: cmt, paid_promo: t.includes('paidContentOverlay')};
}"""

JS_YT_CHANNEL = r"""() => {
  const t = document.documentElement.innerHTML; const out = []; const seen = new Set();
  for (const m of t.matchAll(/"videoId":"([\w-]{11})"[\s\S]{0,2500}?"(?:content|text)":"([^"]{2,120})"[\s\S]{0,1500}?"(?:content|text)":"([^"]*?(?:조회수|views)[^"]*)"/g)) {
    if (seen.has(m[1])) continue; seen.add(m[1]); out.push({id: m[1], title: m[2], views: m[3]});
  }
  return out.slice(0, 15);
}"""

JS_IG_MEDIA = r"""async ([code, appId]) => {
  const al = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let n = 0n; for (const c of code) n = n * 64n + BigInt(al.indexOf(c));
  const r = await fetch('/api/v1/media/' + n.toString() + '/info/', {headers: {'X-IG-App-ID': appId}});
  const j = await r.json(); const m = j.items[0];
  return {user: m.user.username, date: new Date(m.taken_at * 1000).toISOString().slice(0, 10),
          views: m.play_count || m.ig_play_count || null, likes: m.like_count, comments: m.comment_count,
          reposts: m.media_repost_count ?? null, seconds: m.video_duration ? Math.round(m.video_duration) : null,
          type: m.media_type, caption: (m.caption && m.caption.text) || '',
          carousel_count: m.carousel_media_count || null, paid_partnership: !!m.is_paid_partnership,
          product_tags: (m.product_tags || m.carousel_media?.[0]?.product_tags || null) ? true : false,
          usertags: (m.usertags?.in || []).map(t => t.user?.username).filter(Boolean),
          coauthors: (m.coauthor_producers || []).map(u => u.username)};
}"""

JS_IG_PROFILE = r"""async ([user, appId]) => {
  const r = await fetch('/api/v1/users/web_profile_info/?username=' + user, {headers: {'X-IG-App-ID': appId}});
  const u = (await r.json()).data.user;
  return {full_name: u.full_name, bio: u.biography, followers: u.edge_followed_by?.count,
          bio_links: (u.bio_links || []).map(b => b.url), external_url: u.external_url || null};
}"""

JS_YT_POST = r"""() => {
  const t = document.documentElement.innerHTML;
  const mm = t.match(/ytInitialData\s*=\s*(\{.+?\});\s*<\/script>/s);
  if (!mm) return {err: 'no initial data'};
  const d = JSON.parse(mm[1]);
  const find = (o, key) => { if (!o || typeof o !== 'object') return null; if (key in o) return o[key];
    for (const v of Object.values(o)) { const r = find(v, key); if (r) return r; } return null; };
  const p = find(d, 'backstagePostRenderer') || {};
  const txt = x => !x ? '' : x.simpleText || (x.runs || []).map(r => r.text).join('');
  const links = []; JSON.stringify(p).replace(/"url":"([^"]+)"/g, (_, u) => { links.push(u.replace(/\\u0026/g, '&')); });
  return {author: txt(p.authorText), published: txt(p.publishedTimeText), likes: txt(p.voteCount),
          comments: (t.match(/댓글\s*([\d,.]+[만천]?)개/) || [])[1] || null,
          text: txt(p.contentText), links: [...new Set(links)].slice(0, 20),
          attachment: p.backstageAttachment ? Object.keys(p.backstageAttachment)[0] : null};
}"""

JS_IG_GRID = r"""async () => {
  for (let i = 0; i < 3; i++) { window.scrollBy(0, 900); await new Promise(r => setTimeout(r, 1500)); }
  const seen = new Set(); const out = [];
  for (const a of document.querySelectorAll('a')) {
    const h = a.getAttribute('href') || ''; const m = h.match(/\/(p|reel)\/([\w-]+)/);
    if (!m || seen.has(m[2])) continue; seen.add(m[2]);
    const img = a.querySelector('img'); const multi = !!a.querySelector('svg[aria-label*="슬라이드"], svg[aria-label*="Carousel"], svg[aria-label*="carousel"]');
    out.push({href: 'https://www.instagram.com/' + m[1] + '/' + m[2] + '/', kind: m[1], carousel_icon: multi,
              alt: img ? (img.getAttribute('alt') || '').slice(0, 120) : ''});
  }
  return out.slice(0, 24);
}"""

JS_YT_POSTS_TAB = r"""() => {
  const t = document.documentElement.innerHTML;
  const mm = t.match(/ytInitialData\s*=\s*(\{.+?\});\s*<\/script>/s);
  if (!mm) return [];
  const d = JSON.parse(mm[1]); const out = [];
  const txt = x => !x ? '' : x.simpleText || (x.runs || []).map(r => r.text).join('');
  const walk = o => { if (!o || typeof o !== 'object') return;
    if (o.backstagePostRenderer) { const p = o.backstagePostRenderer;
      out.push({id: p.postId, url: 'https://www.youtube.com/post/' + p.postId, published: txt(p.publishedTimeText),
                likes: txt(p.voteCount), text: txt(p.contentText).slice(0, 150)}); }
    for (const v of Object.values(o)) walk(v); };
  walk(d); return out.slice(0, 20);
}"""

JS_PAGE_TEXT = r"""() => ({title: document.title,
  text: document.body ? document.body.innerText.slice(0, 6000) : '',
  links: [...document.querySelectorAll('a[href^="http"]')].map(a => a.href).filter((v, i, a) => a.indexOf(v) === i).slice(0, 40)})"""

JS_IG_REELS_TAB = r"""async () => {
  for (let i = 0; i < 4; i++) { window.scrollBy(0, 900); await new Promise(r => setTimeout(r, 1500)); }
  return [...document.querySelectorAll('a')].filter(a => /\/reel\//.test(a.getAttribute('href') || ''))
    .map(a => ({href: a.getAttribute('href'), views: a.innerText.replace(/\n/g, ' ').trim()})).slice(0, 18);
}"""

JS_TT_VIDEO = r"""async (url) => {
  const t = await fetch(url).then(r => r.text());
  const m = t.match(/<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application\/json">([\s\S]*?)<\/script>/);
  if (!m) return {err: 'nodata'};
  const it = JSON.parse(m[1]).__DEFAULT_SCOPE__?.['webapp.video-detail']?.itemInfo?.itemStruct;
  if (!it) return {err: 'noitem'};
  const s = it.statsV2 || it.stats;
  return {user: it.author?.uniqueId, date: new Date(it.createTime * 1000).toISOString().slice(0, 10),
          views: Number(s.playCount), likes: Number(s.diggCount), comments: Number(s.commentCount),
          shares: Number(s.shareCount), saves: Number(s.collectCount), seconds: it.video?.duration,
          music: it.music ? it.music.title + ' / ' + it.music.authorName : null, desc: it.desc};
}"""

JS_TT_EMBED = r"""async (user) => {
  const t = await fetch('/embed/@' + user).then(r => r.text());
  const out = []; const re = /"playCount":(\d+),"privateItem":(?:true|false),"authorUniqueId":"[^"]*"/g; let m;
  while ((m = re.exec(t))) {
    const seg = t.slice(Math.max(0, m.index - 20000), m.index);
    const ids = [...seg.matchAll(/"id":"(\d{19})","desc":"((?:[^"\\]|\\.)*)"/g)]; const last = ids[ids.length - 1];
    out.push({id: last ? last[1] : null, views: Number(m[1]), desc: last ? last[2].slice(0, 60) : ''});
  }
  return out;
}"""

# ---------- 링크 종류별 처리 ----------
def collect_one(page, url):
    u = url.strip()
    if ("youtube.com" in u) and "/post/" in u:
        page.goto(u if u.startswith("http") else "https://" + u, wait_until="domcontentloaded"); pause(3, 4)
        d = page.evaluate(JS_YT_POST); shot(page, re.search(r"/post/([\w-]+)", u).group(1))
        return {"platform": "youtube", "kind": "community_post", **d}
    if "youtube.com" in u or "youtu.be" in u:
        vid = re.search(r"(?:v=|shorts/|youtu\.be/)([\w-]{11})", u)
        page.goto("https://www.youtube.com/", wait_until="domcontentloaded")
        if vid:
            d = page.evaluate(JS_YT_VIDEO, vid.group(1)) if "/sorry" not in page.url else {"err": "blocked"}
            if "err" in d:  # 페이지 방식 실패 시 공식 API로 보조
                d = yt_api(vid.group(1)) or d
            page.goto(f"https://www.youtube.com/watch?v={vid.group(1)}", wait_until="domcontentloaded")
            pause(3, 4); hook_shot(page, vid.group(1))
            return {"platform": "youtube", "kind": "video", **d}
        if re.search(r"/(posts|community)/?$", u):
            page.goto(u, wait_until="domcontentloaded"); pause(3, 4)
            return {"platform": "youtube", "kind": "channel_posts", "recent_posts": page.evaluate(JS_YT_POSTS_TAB)}
        page.goto(u.rstrip("/") + "/videos", wait_until="networkidle"); pause(2, 3)
        return {"platform": "youtube", "kind": "channel", "recent": page.evaluate(JS_YT_CHANNEL)}
    if "instagram.com" in u:
        code = re.search(r"/(?:reel|reels|p)/([\w-]+)", u)
        if code:
            page.goto(u, wait_until="domcontentloaded"); pause(3, 4)
            d = page.evaluate(JS_IG_MEDIA, [code.group(1), IG_APP_ID])
            if d.get("type") == 2:
                hook_shot(page, code.group(1))
            else:
                shot(page, code.group(1) + "_cover")
            return {"platform": "instagram", "kind": "post", **d}
        acct = u.rstrip("/").split("/")[-1]
        page.goto(f"https://www.instagram.com/{acct}/", wait_until="domcontentloaded"); pause(4, 5)
        grid = page.evaluate(JS_IG_GRID)
        page.goto(f"https://www.instagram.com/{acct}/reels/", wait_until="domcontentloaded"); pause(4, 5)
        reels = page.evaluate(JS_IG_REELS_TAB)
        try:
            prof = page.evaluate(JS_IG_PROFILE, [acct, IG_APP_ID])
        except Exception as e:
            prof = {"profile_err": str(e)[:100]}
        return {"platform": "instagram", "kind": "account", "user": acct, **prof, "recent_posts": grid, "recent_reels": reels,
                "note": "앞 3개는 고정 게시물일 수 있음"}
    if "tiktok.com" in u:
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded"); pause(2, 3)
        if "/video/" in u or "/photo/" in u:
            d = page.evaluate(JS_TT_VIDEO, u.replace("/photo/", "/video/"))
            return {"platform": "tiktok", "kind": "post", **d}
        user = re.search(r"@([\w.]+)", u).group(1)
        return {"platform": "tiktok", "kind": "account", "user": user, "recent": page.evaluate(JS_TT_EMBED, user)}
    # 그 밖의 페이지(스레드·네이버 블로그·링크트리·상품 페이지 등): 화면 글자·링크·캡처
    page.goto(u if u.startswith("http") else "https://" + u, wait_until="domcontentloaded"); pause(4, 5)
    d = page.evaluate(JS_PAGE_TEXT); shot(page, re.sub(r"\W+", "_", u)[-60:])
    return {"platform": "web", "kind": "page", "final_url": page.url, **d}

def shot(page, name):
    """화면 캡처 (카드뉴스 표지·글 게시물 확인용)"""
    try:
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.jpg"), quality=80, type="jpeg")
    except Exception:
        pass

def hook_shot(page, name):
    """첫 3초 후킹 확인용: 0.5초 지점 화면 캡처"""
    try:
        page.evaluate("() => { const v = document.querySelector('video'); if (v) { v.muted = true; v.pause(); v.currentTime = 0.5; } }")
        time.sleep(1.5); SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}_0.5s.jpg"), quality=85, type="jpeg")
    except Exception:
        pass

def open_browser(p):
    opts = dict(headless=False, locale="ko-KR", viewport={"width": 1280, "height": 900})
    try:  # PC에 설치된 정식 크롬이 있으면 그걸 사용 (일반 사용자 브라우저와 동일)
        return p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", **opts)
    except Exception:
        return p.chromium.launch_persistent_context(str(PROFILE), **opts)

def yt_api(video_id):
    """유튜브 공식 API 보조 경로 (환경변수 YOUTUBE_API_KEY가 있을 때만). 차단과 무관, 무료 할당량 내 사용"""
    import os, urllib.request
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return None
    url = ("https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails"
           f"&id={video_id}&key={key}")
    with urllib.request.urlopen(url, timeout=20) as r:
        items = json.loads(r.read().decode()).get("items", [])
    if not items:
        return {"err": "API에 영상 없음"}
    it = items[0]; s = it["statistics"]
    return {"title": it["snippet"]["title"], "views": int(s.get("viewCount", 0)), "likes": s.get("likeCount"),
            "comments": s.get("commentCount"), "date": it["snippet"]["publishedAt"][:10],
            "desc": it["snippet"]["description"], "channel": it["snippet"]["channelTitle"],
            "duration_iso": it["contentDetails"]["duration"], "source": "youtube_data_api"}

def check(page):
    """실행 전 환경 점검: 로그인 상태·차단 여부를 실제 요청 1건씩으로 확인"""
    rep = {}
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded"); pause(3, 4)
    try:
        d = page.evaluate(JS_IG_MEDIA, ["Ddge_XiycRg", IG_APP_ID])
        rep["instagram"] = f"OK (테스트 릴스 조회 {d['views']}, 좋아요 {d['likes']})"
    except Exception as e:
        rep["instagram"] = f"실패 → 'python collector.py login'으로 인스타 직접 로그인 필요 ({str(e)[:60]})"
    page.goto("https://www.youtube.com/", wait_until="domcontentloaded"); pause(2, 3)
    if "/sorry" in page.url:
        rep["youtube"] = "차단(/sorry) → 네트워크가 가정용인지 확인, 또는 YOUTUBE_API_KEY 설정"
    else:
        d = page.evaluate(JS_YT_VIDEO, "znj8v8XY5js")
        rep["youtube"] = f"OK (지정 영상 조회 {d.get('views')})" if "err" not in d else f"실패: {d['err']} → YOUTUBE_API_KEY 설정 권장"
    page.goto("https://www.tiktok.com/", wait_until="domcontentloaded"); pause(2, 3)
    d = page.evaluate(JS_TT_EMBED, "soso_zip")
    rep["tiktok"] = f"OK (최근 {len(d)}개 조회수 확인)" if d else "실패(일시 제한 가능) → 몇 분 뒤 재시도"
    for k, v in rep.items():
        print(f"{k:10s}: {v}")
    return rep

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    with sync_playwright() as p:
        ctx = open_browser(p); page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if cmd == "login":
            for site in ["https://www.instagram.com/", "https://www.youtube.com/", "https://www.tiktok.com/"]:
                page.goto(site); input(f"{site} 에서 직접 로그인한 뒤 Enter (로그인 안 할 사이트는 그냥 Enter): ")
        elif cmd == "check":
            check(page)
        elif cmd == "collect":
            urls = [l for l in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            out = Path(sys.argv[3]); res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
            for i, u in enumerate(urls, 1):
                if u in res and "err" not in res[u]:
                    continue  # 이미 수집한 건 건너뜀 (중간에 끊겨도 이어서)
                try:
                    res[u] = collect_one(page, u)
                except Exception as e:
                    res[u] = {"err": str(e)[:200]}
                res[u]["collected_at"] = time.strftime("%Y-%m-%d %H:%M")
                out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"[{i}/{len(urls)}] {u} → {'실패: ' + res[u]['err'] if 'err' in res[u] else 'OK'}")
                pause()
        else:
            print(__doc__)
        ctx.close()

if __name__ == "__main__":
    main()
