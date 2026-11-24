"""대구·경북 병원 주소 (건강보험심사평가원 병원정보서비스, data.go.kr 같은 인증키).
처음 한 번 data.go.kr 에서 '건강보험심사평가원_병원정보서비스' 활용신청(자동승인)만 하면 된다.
의원(동네 의원)은 빼고 병원급 이상만. 한 달에 한 번 새로 받아 data/hospitals.json 에 저장."""
import json
import logging
import time

import requests

from config import DATA, DATA_GO_KR_KEY

log = logging.getLogger(__name__)
CACHE = DATA / "hospitals.json"
URL = "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList"
SIDO = {"230000": "대구", "370000": "경북"}
# 01 상급종합 · 11 종합병원 · 21 병원 · 28 요양병원 · 29 정신병원 · 41 치과병원 · 92 한방병원
KINDS = {"01": "상급종합병원", "11": "종합병원", "21": "병원", "28": "요양병원", "29": "정신병원",
         "41": "치과병원", "92": "한방병원"}
LAST_ERROR = ""


def _get(params):
    r = requests.get(URL, timeout=40, params={"serviceKey": DATA_GO_KR_KEY, "_type": "json", **params})
    text = r.text.strip()
    if text.startswith("<"):
        import re
        m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>(.*?)<", text)
        raise ValueError(m.group(1) if m else text[:150])
    body = r.json().get("response", {})
    head = body.get("header", {})
    if str(head.get("resultCode", "00")) not in ("00", "0"):
        raise ValueError(f'{head.get("resultCode")} {head.get("resultMsg")}')
    b = body.get("body", {}) or {}
    items = (b.get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(items, dict):
        items = [items]
    return items or [], int(b.get("totalCount") or 0)


def load(force=False):
    global LAST_ERROR
    if CACHE.exists() and not force and time.time() - CACHE.stat().st_mtime < 30 * 86400:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    out = []
    try:
        for sido, region in SIDO.items():
            for cl, kind in KINDS.items():
                page = 1
                while True:
                    items, total = _get({"sidoCd": sido, "clCd": cl, "pageNo": page, "numOfRows": 500})
                    for h in items:
                        addr = str(h.get("addr") or "")
                        if not addr.startswith(("대구", "경상북도", "경북")):
                            continue
                        out.append({"병원명": h.get("yadmNm", ""), "종별": h.get("clCdNm") or kind,
                                    "시도": region, "시군구": h.get("sgguCdNm", ""), "주소": addr,
                                    "우편번호": str(h.get("postNo") or "").strip(), "전화": h.get("telno", "")})
                    if page * 500 >= total or not items:
                        break
                    page += 1
    except (requests.RequestException, ValueError) as e:
        LAST_ERROR = str(e)
        log.warning("병원정보 실패: %s", e)
        if CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8"))
        return []
    if out:
        CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
