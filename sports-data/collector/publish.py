"""수집한 데이터로 정적 사이트를 만든다 (GitHub Pages 등 무료 호스팅용).

- 경기마다 1페이지: 검색 유입용 (제목·설명·구조화 데이터·FAQ)
- 리그별 페이지, 프로토 회차 페이지, 속보 피드
- 애드센스 심사 필수 페이지: 소개, 개인정보처리방침, ads.txt
"""
import html
import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .espn import inj_ko

KST = timezone(timedelta(hours=9))
WD = "월화수목금토일"
SPORT_KO = {"soccer": "축구", "basketball": "농구", "hockey": "아이스하키", "baseball": "야구", "volleyball": "배구", "etc": "기타"}
STATE_KO = {"pre": "경기 전", "in": "경기 중", "post": "종료"}
LINEUP_HINT = {
    "soccer": "축구 선발 명단은 보통 킥오프 약 1시간 전에 발표됩니다.",
    "basketball": "농구 선발은 경기 30분 전후로 확정되는 경우가 많습니다.",
    "hockey": "하키는 선발 골리가 경기 당일 오전·오후에 확정되는 경우가 많습니다.",
    "baseball": "야구 선발 라인업은 보통 경기 3~4시간 전에 발표됩니다.",
}
esc = html.escape


def josa(word, pair):
    """받침 여부로 조사 선택. pair 예: ('은','는'), ('와','과')."""
    if not word:
        return pair[1]
    ch = word[-1]
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
        return pair[1] if has else pair[0]
    return f"{pair[1]}({pair[0]})"


def to_kst(s):
    s = s.replace("Z", "+00:00")
    if len(s) == 22:
        s = s[:16] + ":00" + s[16:]
    return datetime.fromisoformat(s).astimezone(KST)


def kdate(dt):
    return f"{dt.month}월 {dt.day}일({WD[dt.weekday()]})"


def ktime(dt):
    return dt.strftime("%H:%M")


def record_ko(rec, sport):
    if not rec:
        return None
    try:
        p = [int(x) for x in rec.split("-")]
    except ValueError:
        return rec
    if sport == "soccer" and len(p) == 3:
        return f"{p[0]}승 {p[1]}무 {p[2]}패"
    if sport == "hockey" and len(p) == 3:
        return f"{p[0]}승 {p[1]}패 {p[2]}연장패"
    return f"{p[0]}승 {p[1]}패"


def form_count(games):
    c = defaultdict(int)
    for g in games or []:
        c[g.get("result")] += 1
    return c


def status_ko(g):
    """경기 전·종료는 한국어로, 경기 중에는 원문 진행 상황(예: 2nd Half 67')을 함께 보여준다."""
    if g["state"] == "in":
        return f"경기 중 · {g.get('status_detail') or ''}".strip(" ·")
    if g["state"] == "post":
        return "경기 종료"
    detail = (g.get("status_detail") or "").lower()
    if "postpon" in detail:
        return "연기"
    if "cancel" in detail:
        return "취소"
    return "경기 전"


def slug(g):
    return g["id"].replace("/", "-")


CSS = """
:root{--bg:#F2F4F7;--surface:#fff;--ink:#13203A;--muted:#5B6578;--line:#DCE1E9;--accent:#C8460E;--accent-soft:#FBE9E0;--turf:#1C6B58;--turf-soft:#E2F1EC;--bad:#B42318;--bad-soft:#FDE7E5;--board:#13203A;--board-fg:#F5F7FA}
@media (prefers-color-scheme:dark){:root{--bg:#0E1422;--surface:#161E30;--ink:#E8ECF3;--muted:#9AA4B8;--line:#2A3550;--accent:#F07A43;--accent-soft:#3A2218;--turf:#4FC3A1;--turf-soft:#173229;--bad:#F27A6E;--bad-soft:#3A1A18;--board:#060A13;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 "IBM Plex Sans KR",system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
a{color:var(--accent)}.wrap{max-width:1080px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
header{background:var(--board);color:var(--board-fg)}header .wrap{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;padding-block:12px}
.logo{font:400 22px "Black Han Sans",sans-serif;color:var(--board-fg);text-decoration:none}.logo span{color:var(--accent)}
nav{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}nav a{color:var(--board-fg);opacity:.8;text-decoration:none;padding:4px 10px;border-radius:6px;font-size:14px}nav a:hover{background:rgba(255,255,255,.1)}
main{padding-block:20px 40px}h1{font-size:26px;line-height:1.3;margin:4px 0 8px;text-wrap:balance}h2{font-size:19px;margin:28px 0 10px}
.muted,.small{color:var(--muted)}.small{font-size:13px}.num{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;align-items:start}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.day{font-size:13px;color:var(--muted);margin:22px 0 8px;display:flex;gap:8px;align-items:center}.day::after{content:"";flex:1;height:1px;background:var(--line)}
.row{display:grid;grid-template-columns:52px 90px minmax(0,1fr) auto;gap:10px;align-items:center;padding:9px 12px;background:var(--surface);border:1px solid var(--line);border-radius:8px;margin-bottom:6px;text-decoration:none;color:var(--ink)}
.row:hover{border-color:var(--accent)}.row .lg{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row .vs{font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:560px){.row{grid-template-columns:48px minmax(0,1fr)}.row .lg{grid-column:2}.row .st{grid-column:2}}
.b{display:inline-block;font-size:11px;font-weight:700;padding:0 6px;border-radius:4px;margin-left:4px}.b.lu{background:var(--turf-soft);color:var(--turf)}.b.inj{background:var(--bad-soft);color:var(--bad)}.b.live{background:var(--accent-soft);color:var(--accent)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted)}
.tbl{overflow-x:auto}.bar{height:10px;background:var(--line);border-radius:5px;overflow:hidden}.bar i{display:block;height:100%;background:var(--turf)}
.prob{display:grid;grid-template-columns:110px minmax(0,1fr) 54px;gap:8px;align-items:center;margin-bottom:6px;font-size:14px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.feed{list-style:none;margin:0;padding:0;display:grid;gap:10px;font-size:14px}.feed time{font-size:12px;color:var(--muted);display:block}
.cta{background:var(--board);color:var(--board-fg);border-radius:10px;padding:16px}.cta h3{margin:0 0 6px;font-size:17px}.cta p{margin:0 0 10px;font-size:14px;opacity:.85}
.btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;padding:8px 14px;border-radius:8px;margin:4px 6px 0 0}
.ad{margin:16px 0;min-height:0}footer{border-top:1px solid var(--line);background:var(--surface);font-size:13px;color:var(--muted)}footer .wrap{padding-block:18px;display:grid;gap:4px}footer b{color:var(--ink)}
details{margin-bottom:8px}summary{cursor:pointer;font-weight:700}
"""


class Site:
    def __init__(self, cfg, ko, now, out):
        self.cfg, self.ko, self.now, self.out = cfg, ko, now, out
        self.pages = []
        self.models = {}

    def ad(self):
        c = self.cfg.get("adsense_client")
        if not c:
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" '
                'data-ad-format="auto" data-full-width-responsive="true"></ins>'
                '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')

    def cta(self):
        links = []
        if self.cfg.get("telegram_channel_url"):
            links.append(f'<a class="btn" href="{esc(self.cfg["telegram_channel_url"])}">텔레그램 속보 받기</a>')
        if self.cfg.get("kakao_channel_url"):
            links.append(f'<a class="btn" href="{esc(self.cfg["kakao_channel_url"])}">카카오톡 채널 추가</a>')
        if self.cfg.get("google_form_url"):
            links.append(f'<a class="btn" href="{esc(self.cfg["google_form_url"])}">이메일로 받기</a>')
        if not links:
            return ""
        return ('<div class="cta"><h3>라인업·부상 속보 무료 알림</h3>'
                '<p>선발 명단 발표, 부상 소식, 경기 결과를 감지 즉시 보내드립니다.</p>' + "".join(links) + "</div>")

    def page(self, path, title, desc, body, jsonld=None, depth=0):
        r = "../" * depth
        c = self.cfg
        head_ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={esc(c["adsense_client"])}" '
                    'crossorigin="anonymous"></script>') if c.get("adsense_client") else ""
        ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
        url = f"{c['base_url']}/{path}".replace("/index.html", "/")
        doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(url)}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website"><meta property="og:url" content="{esc(url)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=IBM+Plex+Sans+KR:wght@400;700&family=IBM+Plex+Mono:wght@500&display=swap">
<link rel="stylesheet" href="{r}assets/style.css">{head_ads}{ld}</head><body>
<header><div class="wrap"><a class="logo" href="{r}index.html">프로토<span>데이터룸</span></a>
<nav><a href="{r}index.html">오늘 경기</a><a href="{r}proto.html">프로토 회차</a><a href="{r}news.html">속보</a><a href="{r}record.html">적중 기록</a><a href="{r}about.html">소개</a></nav></div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap"><div><b>{esc(c['site_name'])}는 체육진흥투표권을 판매·중개·대행하지 않습니다.</b> 모든 정보는 참고용이며 결과를 보장하지 않습니다. 구매는 공식 발매처(베트맨, 스포츠토토 판매점)에서만 가능합니다.</div>
<div>만 19세 미만 구매 불가 · 도박문제 상담 1336 · 불법스포츠토토 신고 1899-1119</div>
<div>데이터 출처: ESPN 공개 데이터, 각 리그 공식 발표 · 마지막 갱신 {self.now.astimezone(KST).strftime('%Y-%m-%d %H:%M')} KST · <a href="{r}privacy.html">개인정보처리방침</a></div></div></footer>
</body></html>"""
        full = os.path.join(self.out, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(doc)
        self.pages.append(path)

    # ---------- 공통 조각 ----------
    def row(self, g, depth):
        ko = self.ko
        dt = to_kst(g["start_utc"])
        badges = ""
        if g.get("lineups"):
            badges += '<span class="b lu">라인업</span>'
        n_inj = sum(len(v) for v in g.get("injuries", {}).values())
        if n_inj:
            badges += f'<span class="b inj">부상 {n_inj}</span>'
        if g["state"] == "in":
            badges += '<span class="b live">LIVE</span>'
        if g["state"] in ("in", "post") and g["home"].get("score") is not None:
            st = f'<span class="num">{esc(str(g["home"]["score"]))} : {esc(str(g["away"]["score"]))}</span>'
        elif g.get("prob") and g["state"] == "pre":
            pr = g["prob"]
            fav = ko(g["home"]["name"]) if pr["home"] >= pr["away"] else ko(g["away"]["name"])
            st = f'<span class="small">{esc(fav)} <b class="num">{max(pr["home"], pr["away"]) * 100:.0f}%</b></span>'
        else:
            st = f'<span class="small">{status_ko(g)}</span>'
        href = ("../" * depth) + f"m/{slug(g)}.html"
        return (f'<a class="row" href="{href}"><span class="num">{ktime(dt)}</span><span class="lg">{esc(g["league_name"])}</span>'
                f'<span class="vs">{esc(ko(g["home"]["name"]))} vs {esc(ko(g["away"]["name"]))}{badges}</span><span class="st">{st}</span></a>')

    def day_list(self, games, depth):
        by_day = defaultdict(list)
        for g in sorted(games, key=lambda x: x["start_utc"]):
            by_day[to_kst(g["start_utc"]).date()].append(g)
        out = []
        for d in sorted(by_day):
            dt = datetime(d.year, d.month, d.day, tzinfo=KST)
            out.append(f'<div class="day">{kdate(dt)} · {len(by_day[d])}경기</div>')
            out += [self.row(g, depth) for g in by_day[d]]
        return "".join(out) or '<p class="muted">표시할 경기가 없습니다.</p>'

    def feed_html(self, feed, n, depth):
        items = []
        for e in feed[:n]:
            t = to_kst(e["ts"]) if e.get("ts") else None
            when = f"{kdate(t)} {ktime(t)}" if t else ""
            href = ("../" * depth) + f"m/{e['game'].replace('/', '-')}.html"
            items.append(f'<li><time>{when} · {esc(e["league"])}</time><a href="{href}">{esc(e["text"])}</a>'
                         + (f'<div class="small">{esc(e["detail"][:160])}</div>' if e.get("detail") else "") + "</li>")
        return f'<ul class="feed">{"".join(items)}</ul>' if items else '<p class="small">새 소식이 감지되면 여기에 표시됩니다.</p>'

    # ---------- 경기 페이지 ----------
    def match(self, g, siblings, proto_rows):
        ko = self.ko
        H, A = ko(g["home"]["name"]), ko(g["away"]["name"])
        dt = to_kst(g["start_utc"])
        sport = SPORT_KO.get(g["sport"], "")
        title = f"{H} vs {A} 경기 분석 · {kdate(dt)} {g['league_name']} 승률·라인업·부상"
        hrec, arec = record_ko(g["home"].get("record"), g["sport"]), record_ko(g["away"].get("record"), g["sport"])
        l5 = g.get("last_five", {})
        hf, af = form_count(l5.get(g["home"].get("id"))), form_count(l5.get(g["away"].get("id")))
        lineups = g.get("lineups", {})
        inj = g.get("injuries", {})

        # 본문 요약 (데이터로 문장 생성)
        p = [f"{kdate(dt)} {ktime(dt)}(한국시간) {esc(g['league_name'])} {esc(H)}{josa(H, ('와', '과'))} {esc(A)}의 경기가"
             + (f" {esc(g['venue'])}에서" if g.get("venue") else "") + (" 열렸습니다." if g["state"] == "post" else " 열립니다.")]
        if hrec and arec:
            p.append(f"이번 시즌 {esc(H)}{josa(H, ('는', '은'))} {hrec}, {esc(A)}{josa(A, ('는', '은'))} {arec}입니다.")
        if sum(hf.values()) and sum(af.values()):
            def fs(c):
                return f"{c['W']}승" + (f" {c['D']}무" if c.get("D") else "") + f" {c['L']}패"
            p.append(f"최근 5경기는 {esc(H)} {fs(hf)}, {esc(A)} {fs(af)}입니다.")
        n_inj = sum(len(v) for v in inj.values())
        if n_inj:
            p.append(f"현재 부상·결장 관련 선수는 두 팀 합계 {n_inj}명입니다.")
        if lineups:
            p.append("선발 명단이 발표돼 아래에 정리했습니다.")
        elif g["state"] == "pre":
            p.append(LINEUP_HINT.get(g["sport"], "") + " 발표되면 이 페이지에 바로 반영됩니다.")
        if g["state"] == "post":
            p.append(f"경기는 {esc(H)} {esc(str(g['home'].get('score')))} : {esc(str(g['away'].get('score')))} {esc(A)}로 끝났습니다.")
        if g.get("note"):
            p.append(esc(g["note"]))
        if g.get("comment"):
            p.append(esc(g["comment"][0]))

        info = [("경기 시각", f"{kdate(dt)} {ktime(dt)} (한국시간)"), ("리그", f"{g['league_name']} · {sport}"),
                ("장소", g.get("venue") or "-"), ("상태", status_ko(g))]
        info_html = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in info)

        prob_html = ""
        pr = g.get("prob")
        an = g.get("analysis")
        if an:
            rows = [(H, pr["home"])] + ([("무승부", pr["draw"])] if "draw" in pr else []) + [(A, pr["away"])]
            bars = "".join(f'<div class="prob"><span>{esc(n)}</span><div class="bar"><i style="width:{v * 100:.0f}%"></i></div><span class="num">{v * 100:.1f}%</span></div>' for n, v in rows)
            extra = []
            if an.get("xg"):
                extra.append(f"<tr><th>예상 득점</th><td>{esc(H)} {an['xg'][0]:.2f} · {esc(A)} {an['xg'][1]:.2f}</td></tr>")
                extra.append("<tr><th>유력 스코어</th><td>" + ", ".join(f"{s_} ({p_ * 100:.0f}%)" for s_, p_ in an["top_scores"]) + "</td></tr>")
                extra.append(f"<tr><th>{an['ou_line']} 오버 / 언더</th><td class='num'>{an['over'] * 100:.0f}% / {(1 - an['over']) * 100:.0f}%</td></tr>")
                extra.append(f"<tr><th>양 팀 모두 득점</th><td class='num'>{an['btts'] * 100:.0f}%</td></tr>")
            if an.get("exp_score"):
                extra.append(f"<tr><th>예상 점수</th><td>{esc(H)} {an['exp_score'][0]} : {an['exp_score'][1]} {esc(A)}</td></tr>")
                extra.append(f"<tr><th>예상 점수차 / 총점</th><td class='num'>{an['exp_margin']:+.1f} / {an['exp_total']:.1f}</td></tr>")
            ftab = "".join(
                f"<tr><td>{esc(f['label'])}</td><td>{esc(f['text'])}</td><td class='num'>{f['pts']:+.0f}</td>"
                f"<td>{esc(H) if f['pts'] > 0 else esc(A) if f['pts'] < 0 else '-'}</td></tr>" for f in an["factors"])
            com = "".join(f"<li>{esc(c_)}</li>" for c_ in g.get("comment", []))
            prob_html = (f"<h2>승률 분석 <span class='b {'lu' if an['confidence'] == '높음' else 'inj' if an['confidence'] == '낮음' else 'live'}'>신뢰도 {an['confidence']}</span></h2>"
                         f"<div class='card'>{bars}</div>"
                         f"<h2>분석 코멘트</h2><div class='card'><ul style='margin:0;padding-left:18px'>{com}</ul></div>"
                         + (f"<div class='card tbl'><table>{''.join(extra)}</table></div>" if extra else "")
                         + f"<h2>승률에 반영한 요인</h2><div class='card tbl'><table><tr><th>요인</th><th>근거</th><th>영향(Elo)</th><th>유리</th></tr>{ftab}"
                         f"<tr><th colspan='2'>합계 (홈 기준, +면 홈 유리)</th><td class='num'><b>{an['diff']:+.0f}</b></td><td></td></tr></table></div>"
                         "<p class='small'>Elo 100점 차이는 승률 약 64% 대 36%에 해당합니다. 표본이 적은 요인은 자동으로 영향이 줄어듭니다. "
                         f"분석은 데이터 갱신 때마다 다시 계산됩니다 (최근 {self.now.astimezone(KST).strftime('%m-%d %H:%M')}).</p>")
        elif pr:
            rows = [(H, pr["home"])] + ([("무승부", pr["draw"])] if "draw" in pr else []) + [(A, pr["away"])]
            prob_html = ("<h2>시즌 성적 기반 기본 확률</h2><div class='card'>" +
                         "".join(f'<div class="prob"><span>{esc(n)}</span><div class="bar"><i style="width:{v * 100:.0f}%"></i></div><span class="num">{v * 100:.1f}%</span></div>' for n, v in rows) +
                         "<p class='small' style='margin:6px 0 0'>시즌 승률과 홈 이점만으로 계산한 참고 수치입니다. 부상·라인업·일정은 반영하지 않습니다.</p></div>")

        def lineup_block(side):
            tid = g[side].get("id")
            lu = lineups.get(tid)
            name = ko(g[side]["name"])
            if not lu:
                return f"<div class='card'><b>{esc(name)}</b><p class='small'>아직 발표되지 않았습니다.</p></div>"
            li = "".join(f"<tr><td class='num'>{esc(str(x.get('no') or ''))}</td><td>{esc(x.get('name') or '')}</td><td>{esc(x.get('pos') or '')}</td></tr>" for x in lu["starters"])
            return (f"<div class='card'><b>{esc(name)}</b> <span class='small'>{esc(lu.get('formation') or '')}</span>"
                    f"<div class='tbl'><table><tr><th>번호</th><th>선수</th><th>포지션</th></tr>{li}</table></div></div>")

        def inj_block(side):
            items = inj.get(g[side].get("id"), [])
            name = ko(g[side]["name"])
            if not items:
                return f"<div class='card'><b>{esc(name)}</b><p class='small'>보고된 부상자가 없습니다.</p></div>"
            li = "".join(f"<tr><td>{esc(i.get('name') or '')}</td><td>{esc(inj_ko(i.get('status')))}</td><td>{esc(i.get('part') or '')}</td></tr>" for i in items)
            return f"<div class='card'><b>{esc(name)}</b><div class='tbl'><table><tr><th>선수</th><th>상태</th><th>부위</th></tr>{li}</table></div></div>"

        def l5_block(side):
            items = l5.get(g[side].get("id"), [])
            name = ko(g[side]["name"])
            if not items:
                return ""
            res = {"W": "승", "L": "패", "D": "무"}
            li = "".join(
                f"<tr><td class='num'>{esc((x.get('date') or '')[:10])}</td><td>{res.get(x.get('result'), esc(x.get('result') or ''))}</td>"
                f"<td>{esc(x.get('at_vs') or '')} {esc(ko(x.get('opponent') or ''))}</td><td class='num'>{esc(x.get('score') or '')}</td></tr>"
                for x in items)
            return f"<div class='card'><b>{esc(name)}</b><div class='tbl'><table><tr><th>날짜</th><th>결과</th><th>상대</th><th>스코어</th></tr>{li}</table></div></div>"

        sections = [f"<p class='small'>{esc(g['league_name'])} · {sport} · 데이터 출처 {esc(g.get('source', ''))}</p>",
                    f"<h1>{esc(H)} vs {esc(A)} 경기 분석</h1>",
                    self.team_links(g),
                    "<div class='card'>" + " ".join(p) + "</div>", self.ad(),
                    f"<div class='card tbl'><table>{info_html}</table></div>", prob_html]
        if g.get("source") in ("ESPN", "API-Sports"):
            sections += ["<h2>선발 라인업</h2><div class='cols'>" + lineup_block("home") + lineup_block("away") + "</div>",
                         "<h2>부상·결장</h2><div class='cols'>" + inj_block("home") + inj_block("away") + "</div>"]
            l5h = l5_block("home") + l5_block("away")
            if l5h:
                sections.append("<h2>최근 5경기</h2><div class='cols'>" + l5h + "</div>")
        sections.append(self.cta())
        rel = [s for s in siblings if s["id"] != g["id"]][:8]
        if rel:
            sections.append(f"<h2>{esc(g['league_name'])} 다른 경기</h2>" + "".join(self.row(s, 1) for s in rel))
        # FAQ (검색 노출용)
        faq = [(f"{H} {A} 경기 시간은 언제인가요?", f"한국시간 {kdate(dt)} {ktime(dt)}입니다."),
               (f"{H} {A} 승리 확률은?", (f"{H} {pr['home'] * 100:.0f}%" + (f", 무승부 {pr['draw'] * 100:.0f}%" if 'draw' in pr else '') + f", {A} {pr['away'] * 100:.0f}%입니다.") if pr else "계산 중입니다."),
               (f"{H} {A} 선발 라인업은 발표됐나요?", "발표됐습니다. 위 선발 라인업 표를 확인하세요." if lineups else "아직입니다. " + LINEUP_HINT.get(g["sport"], "")),
               (f"{H} {A} 부상자는 누구인가요?", f"두 팀 합계 {n_inj}명이 보고돼 있습니다." if n_inj else "현재 보고된 부상자가 없습니다.")]
        sections.append("<h2>자주 묻는 질문</h2>" + "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in faq))
        sections.append(self.ad())

        status_map = {"pre": "EventScheduled", "in": "EventScheduled", "post": "EventScheduled"}
        ld = [{"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{H} vs {A}",
               "startDate": dt.isoformat(), "eventStatus": f"https://schema.org/{status_map[g['state']]}",
               "sport": sport, "homeTeam": {"@type": "SportsTeam", "name": H}, "awayTeam": {"@type": "SportsTeam", "name": A},
               "location": {"@type": "Place", "name": g.get("venue") or g["league_name"]}},
              {"@context": "https://schema.org", "@type": "FAQPage",
               "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}]
        desc = f"{kdate(dt)} {ktime(dt)} {g['league_name']} {H} vs {A}. " + (f"시즌 {H} {hrec}, {A} {arec}. " if hrec and arec else "") + "승률 분석, 선발 라인업, 부상자, 휴식일, 최근 5경기, 상대전적을 정리했습니다."
        self.page(f"m/{slug(g)}.html", title, desc, "".join(sections), ld, depth=1)

    def team_href(self, league, tid, depth):
        return ("../" * depth) + f"t/{league}-{tid}.html"

    def team_links(self, g):
        if not g["home"].get("id") or g["league"] not in self.models:
            return ""
        return ("<p class='small'>팀 페이지: " + " · ".join(
            f"<a href='{self.team_href(g['league'], g[s]['id'], 1)}'>{esc(self.ko(g[s]['name']))} 최신 정보</a>" for s in ("home", "away")) + "</p>")

    def team_pages(self, games, league_names):
        ko = self.ko
        upcoming = defaultdict(list)
        for g in games:
            for s in ("home", "away"):
                if g[s].get("id"):
                    upcoming[(g["league"], g[s]["id"])].append(g)
        n = 0
        for key, m in self.models.items():
            names = {}
            for g in m.games:
                names[g["home"]] = g.get("home_name")
                names[g["away"]] = g.get("away_name")
            current = {g["home"] for g in m.games} | {g["away"] for g in m.games}
            order = sorted(current, key=lambda t: -m.elo.get(t, m.default))
            for tid in order:
                st = m.team_stats(tid)
                name = ko(names.get(tid) or tid)
                rank = order.index(tid) + 1
                pct = lambda v: f"{v * 100:.0f}%" if v is not None else "-"
                rows = [("전력 점수(Elo)", f"{m.elo.get(tid, m.default):.0f} · 리그 {rank}위/{len(order)}팀"),
                        ("시즌 승률", f"{pct(st['win'])} ({st['n']}경기)"),
                        ("홈 / 원정 승률", f"{pct(st['home_win'])} ({st['home_n']}) / {pct(st['away_win'])} ({st['away_n']})"),
                        ("경기당 득점 / 실점", f"{st['gf']:.1f} / {st['ga']:.1f}" if st["gf"] is not None else "-")]
                info = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in rows)
                res_ko = {1: "승", 0: "패", 0.5: "무"}
                last = "".join(
                    f"<tr><td class='num'>{to_kst(x['date']).strftime('%m-%d')}</td><td>{'홈' if x['home'] else '원정'}</td>"
                    f"<td>{esc(ko(names.get(x['opp']) or x['opp']))}</td><td class='num'>{x['gf']}-{x['ga']}</td><td>{res_ko.get(x['res'], '')}</td>"
                    f"<td class='num'>{x['exp'] * 100:.0f}%</td></tr>" for x in reversed(st["last"]))
                ups = sorted((g for g in upcoming.get((key, tid), []) if g["state"] != "post"), key=lambda x: x["start_utc"])
                up_html = "".join(self.row(g, 1) for g in ups[:5]) or "<p class='small'>예정 경기가 아직 없습니다.</p>"
                inj = []
                for g in ups[:1]:
                    inj = g.get("injuries", {}).get(tid, [])
                inj_html = ("<div class='card tbl'><table><tr><th>선수</th><th>상태</th><th>부위</th></tr>" + "".join(
                    f"<tr><td>{esc(i.get('name') or '')}</td><td>{esc(inj_ko(i.get('status')))}</td><td>{esc(i.get('part') or '')}</td></tr>" for i in inj)
                    + "</table></div>") if inj else "<p class='small'>보고된 부상자가 없습니다.</p>"
                lname = league_names.get(key, key)
                body = (f"<p class='small'>{esc(lname)} · 팀 정보</p><h1>{esc(name)} 최신 정보·전력 분석</h1>{self.ad()}"
                        f"<div class='card tbl'><table>{info}</table></div><h2>다음 경기</h2>{up_html}"
                        f"<h2>부상·결장</h2>{inj_html}{self.cta()}"
                        f"<h2>최근 10경기</h2><div class='card tbl'><table><tr><th>날짜</th><th>장소</th><th>상대</th><th>스코어</th><th>결과</th><th>경기 전 승률</th></tr>{last}</table></div>{self.ad()}")
                self.page(f"t/{key}-{tid}.html", f"{name} 최신 정보 · 일정·부상·전력 분석 | {lname}",
                          f"{name}({lname})의 다음 경기 승률, 부상자, 홈·원정 성적, 최근 10경기를 자동으로 갱신합니다.", body, depth=1)
                n += 1
        return n

    def record_page(self, record, league_names):
        rows = []
        tot_n = tot_hit = 0
        for key, r in sorted(record.items(), key=lambda x: -(x[1]["n"] or 0)):
            if not r["n"]:
                continue
            tot_n += r["n"]
            tot_hit += r["acc"] * r["n"]
            rows.append(f"<tr><td>{esc(league_names.get(key, key))}</td><td class='num'>{r['n']}</td><td class='num'>{r['acc'] * 100:.1f}%</td><td class='num'>{r['brier']:.3f}</td></tr>")
        overall = f"{tot_hit / tot_n * 100:.1f}%" if tot_n else "-"
        body = (f"<h1>모델 적중 기록</h1><p class='muted'>모든 경기를 경기 전 시점의 전력 점수로 예측해 채점한 결과입니다. 틀린 경기도 빼지 않습니다.</p>"
                f"<div class='card'><b>전체 {tot_n}경기 적중률 {overall}</b></div>"
                f"<div class='card tbl'><table><tr><th>리그</th><th>채점 경기</th><th>적중률</th><th>브라이어 점수(낮을수록 정확)</th></tr>{''.join(rows)}</table></div>"
                "<p class='small'>축구는 승·무·패 3지선다라 적중률이 낮게 나오는 것이 정상입니다. 각 팀이 3경기 이상 치른 뒤의 경기만 채점합니다. "
                "부상·휴식일 같은 경기 요인은 과거 시점 자료가 없어 이 채점에는 빠져 있고, 실제 경기 분석에는 반영합니다.</p>" + self.cta())
        self.page("record.html", f"모델 적중 기록 | {self.cfg['site_name']}", "리그별 승률 모델의 실제 적중률과 브라이어 점수를 매일 공개합니다.", body)

    # ---------- 목록 페이지 ----------
    def index(self, games, feed):
        now = self.now
        upcoming = [g for g in games if to_kst(g["start_utc"]) >= now.astimezone(KST) - timedelta(hours=3)]
        recent = [g for g in games if g["state"] == "post" and g not in upcoming]
        leagues = sorted({(g["league"], g["league_name"]) for g in games if g["league"] != "kr"}, key=lambda x: x[1])
        lg_links = " · ".join(f'<a href="league/{k}.html">{esc(n)}</a>' for k, n in leagues)
        body = (f"<h1>오늘·내일 스포츠 경기 데이터</h1><p class='muted'>해외축구·NBA·NHL·MLB·국내 리그 일정, 선발 라인업, 부상, 최근 5경기를 자동으로 모아 갱신합니다.</p>"
                f"<p class='small'>리그별: {lg_links}</p>{self.ad()}"
                f"<div class='grid'><div style='min-width:0'>{self.day_list(upcoming, 0)}"
                + (f"<h2>최근 종료 경기</h2>{self.day_list(recent[-20:], 0)}" if recent else "")
                + f"</div><aside>{self.cta()}<div class='card'><h2 style='margin-top:0'>실시간 속보</h2>{self.feed_html(feed, 15, 0)}"
                f"<p class='small'><a href='news.html'>속보 전체 보기</a></p></div>{self.ad()}</aside></div>")
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": self.cfg["site_name"], "url": self.cfg["base_url"] + "/"}
        self.page("index.html", f"{self.cfg['site_name']} · 오늘 경기 라인업·부상·데이터", self.cfg["description"], body, ld)

    def league_pages(self, games):
        by = defaultdict(list)
        for g in games:
            if g["league"] != "kr":
                by[g["league"]].append(g)
        for key, lst in by.items():
            name = lst[0]["league_name"]
            body = f"<h1>{esc(name)} 경기 일정·라인업·부상</h1>{self.ad()}{self.day_list(lst, 1)}{self.cta()}"
            self.page(f"league/{key}.html", f"{name} 경기 일정·라인업·부상 데이터 | {self.cfg['site_name']}",
                      f"{name} 최근·예정 경기의 한국시간 일정, 선발 라인업, 부상자, 최근 5경기를 정리합니다.", body, depth=1)

    def proto_page(self, rows):
        if rows:
            by_round = defaultdict(list)
            for r in rows:
                by_round[r["round"]].append(r)
            parts = []
            for rnd in sorted(by_round, reverse=True):
                trs = "".join(
                    f"<tr><td class='num'>{esc(r.get('game_no', ''))}</td><td class='num'>{esc(r.get('date', ''))} {esc(r.get('time', ''))}</td>"
                    f"<td>{esc(r.get('league', ''))}</td><td>{esc(r.get('type', ''))}</td><td><b>{esc(r.get('home', ''))}</b> vs {esc(r.get('away', ''))}</td>"
                    + "".join(f"<td class='num'>{r[k]:.2f}</td>" if r.get(k) else "<td>-</td>" for k in ("odd_win", "odd_draw", "odd_lose"))
                    + "</tr>" for r in by_round[rnd])
                parts.append(f"<h2>{esc(rnd)}회차</h2><div class='card tbl'><table><tr><th>번호</th><th>일시</th><th>리그</th><th>유형</th><th>경기</th><th>승</th><th>무</th><th>패</th></tr>{trs}</table></div>")
            body = "".join(parts)
        else:
            body = "<p class='muted'>등록된 회차가 없습니다.</p>"
        body = ("<h1>프로토 승부식 회차별 대상경기</h1><p class='muted'>베트맨 공식 발표 기준으로 정리합니다. 배당은 발매 중 바뀔 수 있으니 구매 전 베트맨에서 꼭 확인하세요.</p>"
                + self.ad() + body + self.cta())
        self.page("proto.html", f"프로토 승부식 회차별 대상경기·배당 정리 | {self.cfg['site_name']}",
                  "프로토 승부식 회차별 대상경기와 공식 배당, 경기별 라인업·부상 데이터를 한 곳에서 확인하세요.", body)

    def news(self, feed):
        body = f"<h1>실시간 스포츠 속보</h1><p class='muted'>선발 명단 발표, 부상 소식, 경기 결과를 감지되는 즉시 기록합니다.</p>{self.cta()}<div class='card'>{self.feed_html(feed, 200, 0)}</div>{self.ad()}"
        self.page("news.html", f"실시간 라인업·부상 속보 | {self.cfg['site_name']}", "선발 라인업 발표, 부상, 경기 결과 속보를 실시간으로 모읍니다.", body)

    def static_pages(self):
        n = self.cfg["site_name"]
        about = (f"<h1>{esc(n)} 소개</h1><div class='card'><p>{esc(n)}는 국내외 프로스포츠 경기의 일정, 선발 라인업, 부상, 최근 경기 기록을 자동으로 모아 한국시간 기준으로 정리하는 스포츠 데이터 사이트입니다.</p>"
                 "<p>모든 데이터는 공개된 공식 기록과 공개 데이터를 바탕으로 하며, 수집 즉시 갱신합니다. 기본 확률은 시즌 성적만으로 계산한 참고 수치입니다.</p>"
                 "<p>이 사이트는 체육진흥투표권을 판매·중개·대행하지 않으며, 불법 도박 사이트와 어떤 제휴도 하지 않습니다.</p></div>"
                 "<h2>문의</h2><div class='card'><p>제휴·오류 제보는 텔레그램 채널 또는 사이트 하단 연락처로 보내주세요.</p></div>")
        self.page("about.html", f"{n} 소개", f"{n}는 스포츠 경기 데이터를 정리하는 정보 사이트입니다.", about)
        privacy = (f"<h1>개인정보처리방침</h1><div class='card'>"
                   f"<p>{esc(n)}(이하 '사이트')는 회원가입 없이 이용할 수 있으며, 이름·연락처 등 개인정보를 직접 수집하지 않습니다.</p>"
                   "<h2>쿠키와 광고</h2><p>사이트는 Google 애드센스 광고를 게재할 수 있습니다. Google을 포함한 제3자 광고 사업자는 쿠키를 사용해 이용자의 이 사이트 및 다른 사이트 방문 기록을 바탕으로 광고를 게재할 수 있습니다. "
                   "이용자는 Google 광고 설정(adssettings.google.com)에서 맞춤 광고를 해제할 수 있습니다.</p>"
                   "<h2>방문 통계</h2><p>서비스 개선을 위해 방문 페이지, 접속 시간 같은 익명 통계를 수집할 수 있습니다.</p>"
                   "<h2>외부 알림 채널</h2><p>텔레그램·카카오톡 채널 구독 정보는 각 서비스의 개인정보처리방침을 따릅니다.</p>"
                   f"<p class='small'>시행일 {self.now.astimezone(KST).strftime('%Y-%m-%d')}</p></div>")
        self.page("privacy.html", f"개인정보처리방침 | {n}", f"{n} 개인정보처리방침", privacy)

    def seo_files(self):
        base = self.cfg["base_url"]
        today = self.now.strftime("%Y-%m-%d")
        urls = "".join(f"<url><loc>{esc(base + '/' + p.replace('index.html', ''))}</loc><lastmod>{today}</lastmod></url>" for p in self.pages)
        with open(os.path.join(self.out, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
        with open(os.path.join(self.out, "robots.txt"), "w", encoding="utf-8") as f:
            f.write(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
        c = self.cfg.get("adsense_client", "")
        if c:
            with open(os.path.join(self.out, "ads.txt"), "w", encoding="utf-8") as f:
                f.write(f"google.com, {c.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
        with open(os.path.join(self.out, ".nojekyll"), "w") as f:
            f.write("")


def build(cfg, games, feed, proto, ko, now, out, models=None, record=None):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "assets"))
    with open(os.path.join(out, "assets", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    site = Site(cfg, ko, now, out)
    site.models = models or {}
    league_names = {g["league"]: g["league_name"] for g in games}
    by_league = defaultdict(list)
    for g in games:
        by_league[g["league"]].append(g)
    for g in games:
        site.match(g, sorted(by_league[g["league"]], key=lambda x: x["start_utc"]), proto)
    site.index(games, feed)
    site.league_pages(games)
    site.proto_page(proto)
    site.news(feed)
    site.team_pages(games, league_names)
    site.record_page(record or {}, league_names)
    site.static_pages()
    site.seo_files()
    return len(site.pages)
