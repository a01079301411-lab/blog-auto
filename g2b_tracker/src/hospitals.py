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
    """심평원 서버가 느려서 시간 넉넉히, 세 번까지, https 가 안 되면 http 로."""
    last = None
    for attempt in range(3):
        for url in (URL, URL.replace("https://", "http://")):
            try:
                r = requests.get(url, timeout=90, params={"serviceKey": DATA_GO_KR_KEY, "_type": "json", **params})
                return _parse(r.text.strip())
            except requests.RequestException as e:
                last = e
        time.sleep(3 * (attempt + 1))
    raise ValueError(f"심평원 서버 응답 없음: {last}")


def _parse(text):
    if text.startswith("<"):
        import re
        m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg)>(.*?)<", text)
        raise ValueError(m.group(1) if m else text[:150])
    import json as _j
    body = _j.loads(text).get("response", {})
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
    out, fails = [], []
    for sido, region in SIDO.items():
        for cl, kind in KINDS.items():
            page = 1
            try:
                while True:
                    items, total = _get({"sidoCd": sido, "clCd": cl, "pageNo": page, "numOfRows": 100})
                    for h in items:
                        addr = str(h.get("addr") or "")
                        if not addr.startswith(("대구", "경상북도", "경북")):
                            continue
                        out.append({"병원명": h.get("yadmNm", ""), "종별": h.get("clCdNm") or kind,
                                    "시도": region, "시군구": h.get("sgguCdNm", ""), "주소": addr,
                                    "우편번호": str(h.get("postNo") or "").strip(), "전화": h.get("telno", "")})
                    if page * 100 >= total or not items:
                        break
                    page += 1
            except ValueError as e:  # 한 종류가 실패해도 나머지는 계속
                fails.append(f"{region} {kind}: {e}")
                log.warning("병원정보 %s %s 실패: %s", region, kind, e)
    if fails:
        LAST_ERROR = fails[0] + (f" 외 {len(fails) - 1}건" if len(fails) > 1 else "")
    if not out:
        return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else []
    if out:
        CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        if fails:  # 일부만 받았으면 내일 자동 실행 때 다시 받도록 캐시를 '오래된 것'으로 표시
            import os
            old = time.time() - 29.5 * 86400
            os.utime(CACHE, (old, old))
    return out
