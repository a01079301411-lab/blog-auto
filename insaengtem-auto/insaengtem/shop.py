"""인생템연구소 링크샵 — 판매 가능한 모든 제품을 한 페이지에.

- 품절·숨김 제품 자동 제외, 제품마다 고정 번호(영상 캡션 "링크샵 23번")
- 이번 주 영상 속 제품은 맨 위 '영상 속 제품' 섹션
- 검색 · 카테고리 · 1개당 가격 · 무료배송 뱃지 · 광고(제휴) 고지
- 결과: out/shop/index.html + img/  →  R2/S3 업로드(shop deploy) 또는 폴더 그대로 아무 정적 호스팅
- 인포크링크용 내보내기: out/shop/inpock.csv
"""
from __future__ import annotations

import csv
import html
import json
from datetime import timedelta
from pathlib import Path

from .catalog import load_catalog, load_facts, load_links
from .config import OUT, ROOT, env, fmt_when, now, settings

SHOP = OUT / "shop"


def _featured_keys() -> list[str]:
    from . import db
    start, end = fmt_when(now() - timedelta(days=3)), fmt_when(now() + timedelta(days=7))
    with db.connect() as con:
        rows = con.execute("SELECT product, MIN(when_kst) f FROM posts WHERE product IS NOT NULL AND when_kst BETWEEN ? AND ? "
                           "AND status NOT IN ('skipped') GROUP BY product ORDER BY f", (start, end)).fetchall()
    return [r["product"] for r in rows]


def items() -> list[dict]:
    """링크샵에 올릴 제품 목록(판매중 + 링크 있음 + 숨김 아님)."""
    from .generate import short_name
    from .catalog import usp_of
    links = load_links()
    feat = _featured_keys()
    out = []
    for c in load_catalog():
        if not c.get("available") or c.get("hidden") or c["key"] not in links:
            continue
        try:
            f = load_facts(c["key"])
        except SystemExit:
            continue  # 정보 수집 전 제품은 링크샵에 안 올림 (scrape 후 자동 포함)
        if f.get("soldout"):
            continue
        it = {"key": c["key"], "no": c.get("no"), "name": (f or {}).get("name") or c.get("name") or c["key"],
              "category": c.get("category") or "etc", "url": links[c["key"]], "img": None,
              "price": None, "unit": None, "badges": [], "featured": c["key"] in feat or bool(c.get("pinned")),
              "order": feat.index(c["key"]) if c["key"] in feat else 999}
        if f:
            try:
                u = usp_of(f)
                it["price"] = f"{u.best.option.label} {u.best.option.price:,}원"
                if u.best.option.qty > 1 and f.get("show_unit_price", True):
                    it["unit"] = u.best.text
                if u.best.shipping == 0 and not (u.shipping_fee and not u.free_over):
                    it["badges"].append("무료배송")
                if u.discount_rate:
                    it["badges"].append(f"{u.discount_rate}% 할인")
            except Exception:  # noqa: BLE001
                pass
            it["short"] = short_name(f)
            img = ROOT / (f.get("image") or "")
            if f.get("image") and img.exists():
                it["_img_src"] = img
        out.append(it)
    out.sort(key=lambda x: (x["order"], x["no"] or 9999))
    return out


def _thumb(src: Path, dst: Path) -> None:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if im.height > 60:
        im = im.crop((0, 0, im.width, im.height - 26)) if im.height > im.width * 0.5 else im
    im.thumbnail((480, 480))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=82, optimize=True)


def build() -> str:
    s = settings()["shop"]
    data = items()
    SHOP.mkdir(parents=True, exist_ok=True)
    for it in data:
        src = it.pop("_img_src", None)
        if src:
            name = f"img/{it['key']}.jpg"
            _thumb(src, SHOP / name)
            it["img"] = name
    cats = {k: v for k, v in s["categories"].items() if any(i["category"] == k for i in data)}
    page = TEMPLATE.replace("__TITLE__", html.escape(s["title"])).replace("__SUB__", html.escape(s["subtitle"])) \
        .replace("__DISC__", html.escape(s["disclosure"])).replace("__UPDATED__", now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__DATA__", json.dumps({"items": data, "cats": cats}, ensure_ascii=False).replace("</", "<\\/"))
    (SHOP / "index.html").write_text(page, encoding="utf-8")
    export_inpock(data)
    print(f"[shop] 제품 {len(data)}개 · 영상 속 {sum(i['featured'] for i in data)}개 → {SHOP / 'index.html'}")
    return str(SHOP / "index.html")


def export_inpock(data: list[dict] | None = None) -> str:
    """인포크링크 등 링크인바이오 서비스에 옮겨 적기 위한 목록(엑셀에서 열림)."""
    data = data if data is not None else items()
    p = SHOP / "inpock.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["번호", "제목(인포크 블록 제목)", "부제(가격)", "URL", "이미지 파일", "영상 속 제품"])
        for i in data:
            w.writerow([i["no"], f"{i['no']}. {i.get('short') or i['name']}"[:30], " · ".join(x for x in [i["unit"] or i["price"], *i["badges"]] if x),
                        i["url"], str(SHOP / i["img"]) if i.get("img") else "", "Y" if i["featured"] else ""])
    return str(p)


def deploy() -> str:
    """R2/S3(스레드 영상용과 같은 버킷)에 업로드 → 공개 주소. 성공 시 .env SHOP_PUBLIC_URL 저장."""
    from .config import set_env_values
    if not (SHOP / "index.html").exists():
        build()
    if not env("S3_BUCKET"):
        raise SystemExit("링크샵 업로드 대상이 없습니다: [설정]에 R2/S3 를 입력하거나, out/shop 폴더를 "
                         "Cloudflare Pages / Netlify 에 끌어다 놓고 그 주소를 SHOP_PUBLIC_URL 에 입력하세요.")
    import boto3
    s3 = boto3.client("s3", endpoint_url=env("S3_ENDPOINT_URL"), aws_access_key_id=env("S3_ACCESS_KEY_ID"),
                      aws_secret_access_key=env("S3_SECRET_ACCESS_KEY"))
    n = 0
    for f in SHOP.rglob("*"):
        if f.is_file() and f.suffix in (".html", ".jpg"):
            key = "shop/" + f.relative_to(SHOP).as_posix()
            ct = "text/html; charset=utf-8" if f.suffix == ".html" else "image/jpeg"
            cc = "no-cache" if f.suffix == ".html" else "public, max-age=86400"
            s3.upload_file(str(f), env("S3_BUCKET"), key, ExtraArgs={"ContentType": ct, "CacheControl": cc})
            n += 1
    url = env("S3_PUBLIC_BASE_URL", required=True).rstrip("/") + "/shop/index.html"
    if not env("SHOP_PUBLIC_URL"):
        set_env_values({"SHOP_PUBLIC_URL": url})
    print(f"[shop] {n}개 파일 업로드 → {env('SHOP_PUBLIC_URL') or url}")
    return url


TEMPLATE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><meta name="description" content="__SUB__"><meta name="robots" content="noindex">
<style>
:root{--bg:#fbf7f1;--card:#fff;--fg:#221a12;--sub:#7a6b5d;--line:#efe6db;--acc:#ff6b1a;--acc2:#2a1c10}
@media (prefers-color-scheme:dark){:root{--bg:#14110d;--card:#1f1a15;--fg:#f3ece4;--sub:#ab9d90;--line:#332b23;--acc2:#f3ece4}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:0 16px 40px}
header{text-align:center;padding:28px 0 12px}.logo{width:64px;height:64px;border-radius:18px;background:var(--acc);color:#fff;display:grid;place-items:center;margin:0 auto 10px;font-weight:800;font-size:26px}
h1{font-size:20px;margin:0}.sub{color:var(--sub);margin:4px 0 0;font-size:14px}
.ad{font-size:12px;color:var(--sub);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin:12px 0}
.search{position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:2}
.search input{width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;font-size:16px}
.chips{display:flex;gap:6px;overflow-x:auto;padding:8px 0 2px}.chips button{flex:none;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:20px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}
.chips button.on{background:var(--acc2);color:var(--bg);border-color:var(--acc2)}
h2{font-size:15px;margin:18px 0 8px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
@media (min-width:560px){.grid{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;text-decoration:none;color:inherit}
.card .im{aspect-ratio:1/1;background:var(--line) center/cover no-repeat;position:relative}
.no{position:absolute;left:8px;top:8px;background:var(--acc2);color:var(--bg);border-radius:8px;padding:2px 8px;font-weight:700;font-size:13px}
.card .b{padding:9px 10px 11px;display:flex;flex-direction:column;gap:3px;flex:1}
.nm{font-size:14px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.7em}
.unit{color:var(--acc);font-weight:800;font-size:15px}.pr{color:var(--sub);font-size:13px}
.bd{display:flex;gap:4px;flex-wrap:wrap}.bd span{font-size:11px;border:1px solid var(--acc);color:var(--acc);border-radius:6px;padding:0 5px}
.buy{margin-top:auto;padding-top:6px;font-weight:700;font-size:14px}
.empty{color:var(--sub);text-align:center;padding:30px 0}footer{color:var(--sub);font-size:12px;text-align:center;margin-top:24px}
</style></head><body><div class="wrap">
<header><div class="logo">인</div><h1>__TITLE__</h1><p class="sub">__SUB__</p></header>
<div class="ad">[광고] __DISC__</div>
<div class="search"><input id="q" type="search" placeholder="번호 또는 제품명 검색 (예: 23, 설렁탕)" inputmode="search">
<div class="chips" id="chips"></div></div>
<div id="feat"></div><div id="all"></div>
<footer>업데이트 __UPDATED__ · 가격은 판매처 사정에 따라 바뀔 수 있어요</footer></div>
<script>
const D=__DATA__;let cat="all";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const card=i=>`<a class="card" href="${esc(i.url)}" target="_blank" rel="sponsored noopener nofollow">
<div class="im" style="${i.img?`background-image:url('${esc(i.img)}')`:""}"><span class="no">${i.no}</span></div>
<div class="b"><div class="nm">${esc(i.name)}</div>${i.unit?`<div class="unit">${esc(i.unit)}</div>`:""}<div class="pr">${esc(i.price||"")}</div>
<div class="bd">${i.badges.map(b=>`<span>${esc(b)}</span>`).join("")}</div><div class="buy">구매하러 가기 →</div></div></a>`;
function render(){const q=document.getElementById("q").value.trim();
 const hit=i=>(cat=="all"||i.category==cat)&&(!q||String(i.no)==q||i.name.includes(q));
 const top=!q&&cat=="all";const f=D.items.filter(i=>i.featured&&hit(i)),a=D.items.filter(i=>hit(i)&&!(top&&i.featured));
 document.getElementById("feat").innerHTML=f.length&&!q&&cat=="all"?`<h2>🎬 영상 속 제품</h2><div class="grid">${f.map(card).join("")}</div>`:"";
 document.getElementById("all").innerHTML=(a.length||!top?`<h2>${q?"검색 결과":top?"다른 제품":"제품"} (${a.length})</h2>`:"")+(a.length?`<div class="grid">${a.map(card).join("")}</div>`:(top?"":`<div class="empty">찾는 제품이 없어요</div>`));}
document.getElementById("chips").innerHTML=`<button class="on" data-c="all">전체</button>`+Object.entries(D.cats).map(([k,v])=>`<button data-c="${k}">${esc(v)}</button>`).join("");
document.getElementById("chips").onclick=e=>{if(!e.target.dataset.c)return;cat=e.target.dataset.c;document.querySelectorAll("#chips button").forEach(b=>b.classList.toggle("on",b===e.target));render()};
document.getElementById("q").oninput=render;
const h=location.hash.slice(1);if(h)document.getElementById("q").value=decodeURIComponent(h);render();
</script></body></html>"""
