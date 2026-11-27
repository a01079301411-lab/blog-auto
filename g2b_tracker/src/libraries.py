"""대구·경북 공공도서관 주소 (data.go.kr '전국도서관표준데이터', 같은 인증키).
작은도서관·학교도서관은 빼고 공공·전문도서관만. 한 달에 한 번 새로 받아 data/libraries.json 에 저장."""
import json
import logging
import time

import requests

from config import DATA, DATA_GO_KR_KEY

log = logging.getLogger(__name__)
CACHE = DATA / "libraries.json"
URLS = ["https://api.data.go.kr/openapi/tn_pubr_public_lbrry_api", "http://api.data.go.kr/openapi/tn_pubr_public_lbrry_api"]
SIDO = ("대구광역시", "경상북도")
SKIP = ("작은", "학교", "병영", "교도소")
LAST_ERROR = ""


def _get(params):
    last = None
    for attempt in range(3):
        for url in URLS:
            try:
                r = requests.get(url, timeout=90, params={"serviceKey": DATA_GO_KR_KEY, "type": "json", **params})
                text = r.text.strip()
                if text.startswith("<"):
                    import re
                    m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>(.*?)<", text)
                    raise ValueError(m.group(1) if m else text[:150])
                resp = r.json().get("response", {})
                head = resp.get("header", {})
                code = str(head.get("resultCode", "00"))
                if code == "03":  # 데이터 없음
                    return [], 0
                if code not in ("00", "0"):
                    raise ValueError(f"{code} {head.get('resultMsg', '')}")
                body = resp.get("body", {}) or {}
                items = body.get("items") or []
                if isinstance(items, dict):
                    items = items.get("item", [])
                if isinstance(items, dict):
                    items = [items]
                return items, int(body.get("totalCount") or 0)
            except requests.RequestException as e:
                last = e
            except ValueError as e:
                last = e
                if not str(e).startswith("99"):
                    raise
                break
        time.sleep(10 * (attempt + 1))
    raise ValueError(f"도서관 데이터 응답 없음: {last}")


def load(force=False, cache_only=False):
    global LAST_ERROR
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    fresh = cached is not None and time.time() - CACHE.stat().st_mtime < 30 * 86400
    if cache_only or (fresh and not force):
        return cached or []
    out = []
    try:
        for sido in SIDO:
            page = 1
            while True:
                items, total = _get({"pageNo": page, "numOfRows": 1000, "ctprvnNm": sido})
                for it in items:
                    addr = str(it.get("rdnmadr") or it.get("lnmadr") or "")
                    kind = str(it.get("lbrrySe") or "")
                    name = str(it.get("lbrryNm") or "")
                    if not addr.startswith(("대구", "경상북도", "경북")) or any(x in kind + name for x in SKIP):
                        continue
                    out.append({"도서관명": name, "유형": kind or "공공도서관", "주소": addr,
                                "시군구": it.get("signguNm", ""), "전화": it.get("phoneNumber", "")})
                if page * 1000 >= total or not items:
                    break
                page += 1
    except ValueError as e:
        LAST_ERROR = str(e)
        log.warning("도서관 데이터 실패: %s", e)
        return cached or []
    LAST_ERROR = ""
    seen, uniq = set(), []
    for r in out:
        k = (r["도서관명"], r["주소"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    if uniq:
        CACHE.write_text(json.dumps(uniq, ensure_ascii=False), encoding="utf-8")
    return uniq or (cached or [])
