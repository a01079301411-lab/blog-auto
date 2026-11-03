"""YOGO(yo-go.co.kr) 오픈딜 상세페이지 수집기.

⚠️ 클라우드 환경에서는 yo-go.co.kr 이 차단됨 → 사용자 PC 에서 실행.
   python -m insaengtem scrape            (secrets 의 모든 링크)
   python -m insaengtem scrape egg        (한 제품)

수집 위치(2026-11-03 실측, docs/DESIGN.md 5-1)
- 상품명: 상단 heading, '_COSY 상시' 접미사 제거
- 요약 USP: 상품명 아래 이모지 불릿
- 정가/판매가/할인율: 상단 가격 영역
- 배송비/무료배송 조건: "배송비 2,500원 (20,000원 이상 구매 시 무료)"
- 옵션: select "구성 옵션" option 텍스트 "(+21,900원)" → 기본가 + 추가금
- 품절: 대표 이미지 위 SOLD OUT → 제외
"""
from __future__ import annotations

import re
from datetime import datetime

from .catalog import load_catalog, load_links, save_catalog, save_facts, strip_token
from .config import ROOT, env

_MONEY = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def money(s: str) -> list[int]:
    return [int(x.replace(",", "")) for x in _MONEY.findall(s or "")]


def clean_name(s: str) -> str:
    s = re.sub(r"_?COSY\s*상시\s*$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip(" _")


def parse_shipping(text: str) -> tuple[int | None, int | None]:
    """'배송비 2,500원 (20,000원 이상 구매 시 무료)' → (2500, 20000). '무료배송' → (0, None)."""
    t = text.replace("\n", " ")
    if re.search(r"배송비\s*:?\s*무료|무료\s*배송", t) and not re.search(r"배송비\s*\d", t):
        return 0, None
    m = re.search(r"배송비\s*:?\s*(\d[\d,]*)\s*원", t)
    fee = int(m.group(1).replace(",", "")) if m else None
    m2 = re.search(r"(\d[\d,]*)\s*원\s*이상[^)]*무료", t)
    free = int(m2.group(1).replace(",", "")) if m2 else None
    return fee, free


_QTY = re.compile(r"(\d+)\s*(구|알|포|팩|개|입|병|통|매|봉|박스|kg|g|ml|L)")


def guess_qty(label: str) -> tuple[int, str]:
    """옵션 라벨에서 수량·단위 추정: '60구' → (60,'알'), '4팩' → (4,'팩'), '2종' → (2,'통')."""
    m = re.search(r"(\d+)\s*(구)", label)
    if m:
        return int(m.group(1)), "알"
    m = re.search(r"[x×*]\s*(\d+)\s*(포|팩|개|입|병|봉)", label)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.search(r"(\d+)\s*(포|팩|개|입|병|봉|통|종|세트)", label)
    if m:
        unit = m.group(2)
        return int(m.group(1)), {"종": "통", "세트": "세트"}.get(unit, unit)
    return 1, "개"


def parse_option(text: str, base_price: int) -> dict | None:
    """'60구 (+19,500원)' → {'label':'60구','price':base+19500,...}. 품절 옵션은 None."""
    if not text or "선택" in text and "필수" in text or text.strip().startswith("-"):
        return None
    if "품절" in text:
        return None
    m = re.search(r"\(([+-])\s*(\d[\d,]*)\s*원\)", text)
    delta = 0
    if m:
        delta = int(m.group(2).replace(",", "")) * (1 if m.group(1) == "+" else -1)
    label = re.sub(r"\([+-]?\s*\d[\d,]*\s*원\)", "", text).strip(" -")
    qty, unit = guess_qty(label)
    return {"label": label, "price": base_price + delta, "qty": qty, "unit": unit}


def scrape(keys: list[str] | None = None, headless: bool = False) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("pip install playwright && playwright install chrome 후 다시 실행하세요.")
    links = load_links()
    cat = load_catalog()
    by_key = {c["key"]: c for c in cat}
    targets = keys or list(links)
    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(ROOT / env("CHROME_PROFILE_DIR", "chrome-profile-insaengtem")),
            channel=env("CHROME_CHANNEL") or None, headless=headless, locale="ko-KR")
        page = ctx.new_page()
        for key in targets:
            url = links.get(key) or by_key.get(key, {}).get("link")
            if not url:
                print(f"[skip] {key}: 링크 없음")
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            f = _extract(page)
            f.update({"key": key, "source": f"YOGO 상세페이지 {datetime.now():%Y-%m-%d %H:%M} 수집",
                      "url": strip_token(url)})
            # 대표 이미지 저장
            img = ROOT / "assets" / "products" / f"{key}.png"
            if f.pop("_img_el", None):
                try:
                    page.locator(f.pop("_img_sel")).first.screenshot(path=str(img))
                    f["image"] = f"assets/products/{key}.png"
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] {key} 대표 이미지 저장 실패: {e}")
            f.setdefault("image", f"assets/products/{key}.png")
            save_facts(key, f)
            c = by_key.setdefault(key, {"key": key})
            c.update({"name": f["name"], "link": strip_token(url), "available": not f["soldout"],
                      "status": "품절 - 제외" if f["soldout"] else "판매중",
                      "checked_at": f"{datetime.now():%Y-%m-%d %H:%M}"})
            print(f"[ok] {key}: {f['name']} / 옵션 {len(f['options'])}개 / {'품절' if f['soldout'] else '판매중'}")
            results.append(f)
        ctx.close()
    save_catalog(list(by_key.values()))
    return results


def _extract(page) -> dict:
    """상세페이지 DOM → facts. 셀렉터는 텍스트 기반으로 넓게 잡고, 실패해도 빈 값으로 둔다."""
    js = r"""
    () => {
      const txt = el => (el && el.innerText || '').trim();
      const h = document.querySelector('h1, h2, .headingArea h2, .infoArea h2, .name');
      const body = document.body.innerText;
      const sel = [...document.querySelectorAll('select')].find(s => /옵션|구성/.test(s.closest('tr,li,div')?.innerText || s.name || '')) || document.querySelector('select');
      const opts = sel ? [...sel.options].map(o => o.textContent.trim()) : [];
      const soldImg = [...document.querySelectorAll('img')].some(i => /sold.?out|soldout|품절/i.test((i.src||'') + (i.alt||'')));
      const soldTxt = /SOLD\s*OUT/i.test(txt(document.querySelector('.xans-product-image, .keyImg, .thumbnail, .imgArea')))
                   || !!document.querySelector('.displaynone.soldout, .icon_soldout:not(.displaynone)');
      const big = document.querySelector('.keyImg img, .BigImage, .thumbnail img, .imgArea img');
      // 상품명 아래 이모지 불릿
      const bullets = body.split('\n').map(s => s.trim()).filter(s => /^[☀-➿\uD83C-\uDBFF⭐✅✔✅•·-]/.test(s) && s.length < 60).slice(0, 6);
      return {name: txt(h), body, opts, sold: soldImg || soldTxt, hasImg: !!big, bullets};
    }"""
    r = page.evaluate(js)
    body = r["body"]
    name = clean_name(r["name"].split("\n")[0])
    # 가격: '판매가' / '소비자가' 라벨 주변
    def near(label):
        m = re.search(label + r"[^\d]{0,20}(\d[\d,]*)\s*원", body)
        return int(m.group(1).replace(",", "")) if m else None
    sale = near("판매가") or (money(body)[0] if money(body) else None)
    lst = near("소비자가") or near("정가")
    fee, free = parse_shipping(next((ln for ln in body.split("\n") if "배송비" in ln), ""))
    options = [o for o in (parse_option(t, sale or 0) for t in r["opts"]) if o]
    if not options and sale:
        q, u = guess_qty(name)
        options = [{"label": "기본", "price": sale, "qty": q, "unit": u}]
    out = {"name": name, "bullets": [re.sub(r"^[^\w가-힣]+", "", b).strip() for b in r["bullets"]],
           "list_price": lst, "sale_price": sale, "shipping_fee": fee, "free_over": free,
           "options": options, "soldout": bool(r["sold"]) or "SOLD OUT" in body[:3000]}
    if r["hasImg"]:
        out["_img_el"] = True
        out["_img_sel"] = ".keyImg img, .BigImage, .thumbnail img, .imgArea img"
    unknown = [k for k in ("sale_price", "shipping_fee") if out[k] is None]
    if unknown:
        out["unknown"] = [f"{k}: 자동 수집 실패 → 상세페이지 확인 후 facts.json 수기 입력" for k in unknown]
    return out


def recheck_soldout(key: str) -> bool | None:
    """게시 직전 품절 재확인. Playwright 없거나 실패하면 None(판단 불가)."""
    try:
        res = scrape([key], headless=True)
        return res[0]["soldout"] if res else None
    except SystemExit:
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 품절 재확인 실패 {key}: {e}")
        return None
