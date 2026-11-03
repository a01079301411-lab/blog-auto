"""제품 카탈로그·실측 데이터(facts)·제휴 링크(로컬 비공개) 로딩."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import PRODUCTS, SECRETS
from .usp import Option, UspResult, unit_prices

LINKS_FILE = SECRETS / "affiliate_links.json"


def load_catalog() -> list[dict]:
    return json.loads((PRODUCTS / "_catalog.json").read_text(encoding="utf-8"))


def save_catalog(cat: list[dict]) -> None:
    (PRODUCTS / "_catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")


def available(cat: list[dict] | None = None) -> list[dict]:
    """품절 제외. 판매중이면서 영상 설정 JSON 이 있는 제품."""
    cat = cat if cat is not None else load_catalog()
    return [c for c in cat if c.get("available") and (PRODUCTS / f"{c['key']}.json").exists()]


def facts_path(key: str) -> Path:
    return PRODUCTS / f"{key}.facts.json"


def load_facts(key: str) -> dict:
    p = facts_path(key)
    if not p.exists():
        raise SystemExit(f"{p} 없음. 먼저 `python -m insaengtem scrape` 로 수집하세요.")
    return json.loads(p.read_text(encoding="utf-8"))


def save_facts(key: str, facts: dict) -> None:
    facts_path(key).write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")


def load_product_cfg(key: str) -> dict:
    return json.loads((PRODUCTS / f"{key}.json").read_text(encoding="utf-8"))


def usp_of(facts: dict) -> UspResult:
    return unit_prices([Option(**o) for o in facts["options"]],
                       shipping_fee=facts.get("shipping_fee") or 0,
                       free_over=facts.get("free_over"),
                       list_price=facts.get("list_price"),
                       sale_price=facts.get("sale_price"))


# ---------- 제휴 링크 (sl 토큰) : secrets/ 에만 저장 ----------
_SL = re.compile(r"[?&]sl=([A-Za-z0-9_\-]+)")


def load_links() -> dict:
    if not LINKS_FILE.exists():
        return {}
    return json.loads(LINKS_FILE.read_text(encoding="utf-8"))


def link_for(key: str, strict: bool = True) -> str:
    links = load_links()
    url = links.get(key)
    if not url:
        if strict:
            raise SystemExit(f"제휴 링크 없음: {key}. secrets/affiliate_links.json 에 추가하세요 "
                             f"(`python -m insaengtem links set {key} <URL>`).")
        return "{link}"
    if not _SL.search(url):
        raise SystemExit(f"{key} 링크에 sl= 제휴 토큰이 없습니다. 수수료가 잡히지 않으니 원본 링크를 넣으세요.")
    return url


def set_link(key: str, url: str) -> None:
    if not _SL.search(url):
        raise SystemExit("sl= 제휴 토큰이 없는 링크입니다.")
    SECRETS.mkdir(exist_ok=True)
    links = load_links()
    links[key] = url.strip()
    LINKS_FILE.write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")


def import_links(old_catalog: Path) -> int:
    """원본 zip 의 _catalog.json(링크 포함)에서 제휴 링크만 뽑아 secrets 로 옮긴다."""
    data = json.loads(Path(old_catalog).read_text(encoding="utf-8"))
    n = 0
    for c in data:
        if c.get("link") and _SL.search(c["link"]):
            set_link(c["key"], c["link"])
            n += 1
    return n


def strip_token(url: str) -> str:
    return re.sub(r"&sl=[A-Za-z0-9_\-]+", "", re.sub(r"\?sl=[A-Za-z0-9_\-]+&?", "?", url))


# ---------- 대량 등록 ----------
_URLS = re.compile(r"https?://(?:www\.)?yo-go\.co\.kr/product/detail\.html\?[^\s\"'<>]+")
CATEGORY_WORDS = {
    "food": ["설렁탕", "달걀", "계란", "유정란", "국", "탕", "밥", "김치", "고기", "만두", "과일", "쌀", "면", "소스", "간식", "견과"],
    "health": ["단백질", "쉐이크", "프로틴", "유산균", "비타민", "오메가", "콜라겐", "다이어트", "영양제"],
    "beauty": ["샴푸", "바디", "크림", "세럼", "앰플", "선크림", "립", "토너", "클렌징", "마스크팩", "미스트", "리들샷"],
    "baby": ["기저귀", "물티슈", "젖병", "유아", "아기", "키즈", "이유식"],
    "kitchen": ["프라이팬", "냄비", "용기", "도마", "칼", "주방"],
    "living": ["세제", "휴지", "수납", "청소", "섬유유연제", "방향제", "행주", "타월"],
}


def guess_category(name: str) -> str:
    for cat, words in CATEGORY_WORDS.items():
        if any(w in (name or "") for w in words):
            return cat
    return "etc"


def add_links_bulk(text: str) -> dict:
    """붙여넣은 글에서 YOGO 제휴 링크를 모두 찾아 등록. 같은 product_no 는 갱신."""
    from datetime import datetime
    cat = load_catalog()
    by_no = {c.get("product_no"): c for c in cat}
    next_no = max([c.get("no", 0) for c in cat] + [0]) + 1
    added, updated, skipped = [], [], []
    for url in dict.fromkeys(_URLS.findall(text or "")):
        url = url.rstrip(").,")
        m = re.search(r"product_no=(\d+)", url)
        if not m or not _SL.search(url):
            skipped.append(url)
            continue
        pno = int(m.group(1))
        c = by_no.get(pno)
        if c:
            updated.append(c["key"])
        else:
            c = {"key": f"p{pno}", "product_no": pno, "name": None, "link": strip_token(url), "available": True,
                 "status": "수집 대기", "no": next_no, "category": "etc", "hidden": False,
                 "added_at": f"{datetime.now():%Y-%m-%d}"}
            next_no += 1
            cat.append(c)
            by_no[pno] = c
            added.append(c["key"])
        set_link(c["key"], url)
    save_catalog(cat)
    return {"added": added, "updated": updated, "skipped": skipped}


def update_product(key: str, **fields) -> dict:
    cat = load_catalog()
    for c in cat:
        if c["key"] == key:
            for k in ("category", "hidden", "name", "pinned"):
                if k in fields:
                    c[k] = fields[k]
            save_catalog(cat)
            return c
    raise SystemExit(f"제품 없음: {key}")
