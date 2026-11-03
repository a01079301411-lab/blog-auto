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
