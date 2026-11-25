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
    """심평원 서버가 느리거나 바쁘면(99) 잠깐 쉬고 다시, https 가 안 되면 http 로."""
    last = None
    for attempt in range(3):
        for url in (URL, URL.replace("https://", "http://")):
            try:
                r = requests.get(url, timeout=90, params={"serviceKey": DATA_GO_KR_KEY, "_type": "json", **params})
                return _parse(r.text.strip())
            except requests.RequestException as e:
                last = e
            except ValueError as e:
                last = e
                if not str(e).startswith("99"):
                    raise
                break  # 서버 바쁨: http 로 바꿔 봐야 같음 → 쉬었다가 다시
        time.sleep(10 * (attempt + 1))
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


def _read_cache():
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("parts", {}) if isinstance(data, dict) else {}


def load(force=False, cache_only=False):
    """종류(시도×종별)마다 따로 저장. 30일 지난 것·실패한 것만 다시 받는다. cache_only 면 서버에 묻지 않음."""
    global LAST_ERROR
    parts = _read_cache()
    fails = []
    if not cache_only:
        for sido, region in SIDO.items():
            for cl, kind in KINDS.items():
                key = f"{sido}-{cl}"
                if not force and time.time() - parts.get(key, {}).get("t", 0) < 30 * 86400:
                    continue
                rows, page = [], 1
                try:
                    while True:
                        items, total = _get({"sidoCd": sido, "clCd": cl, "pageNo": page, "numOfRows": 100})
                        for h in items:
                            addr = str(h.get("addr") or "")
                            if addr.startswith(("대구", "경상북도", "경북")):
                                rows.append({"병원명": h.get("yadmNm", ""), "종별": h.get("clCdNm") or kind,
                                             "시도": region, "시군구": h.get("sgguCdNm", ""), "주소": addr,
                                             "우편번호": str(h.get("postNo") or "").strip(), "전화": h.get("telno", "")})
                        if page * 100 >= total or not items:
                            break
                        page += 1
                    parts[key] = {"t": time.time(), "rows": rows}
                    CACHE.write_text(json.dumps({"parts": parts}, ensure_ascii=False), encoding="utf-8")
                except ValueError as e:  # 이 종류만 다음에 다시 (받아 둔 옛 자료는 그대로 씀)
                    fails.append(f"{region} {kind}: {e}")
                    log.warning("병원정보 %s %s 실패(다음 실행 때 다시): %s", region, kind, e)
    LAST_ERROR = (fails[0] + (f" 외 {len(fails) - 1}건" if len(fails) > 1 else "")) if fails else ""
    return [r for p in parts.values() for r in p.get("rows", [])]
