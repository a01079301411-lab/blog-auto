"""조달청 나라장터 OpenAPI(공공데이터포털) 호출.

쓰는 서비스 (공공데이터포털에서 각각 '활용신청' 필요, 키는 하나로 같음)
- 조달청_나라장터 입찰공고정보서비스   (bid)   : 지금 나와 있는 입찰·견적 공고
- 조달청_나라장터 사전규격정보서비스   (pre)   : 공고 전 사전규격 (공고보다 1~3주 빠름)
- 조달청_나라장터 발주계획현황서비스   (plan)  : 올해·내년 발주 예정 (가장 빠른 신호)
- 조달청_나라장터 낙찰정보서비스       (award) : 낙찰업체 = 원도급사 영업 대상
"""
import logging
import re
import time
from datetime import datetime, timedelta

import requests

from config import BASES, DATA_GO_KR_KEY

log = logging.getLogger(__name__)

KINDS = {"용역": "Servc", "공사": "Cnstwk", "물품": "Thng"}

# 소스별 목록 오퍼레이션 이름 ({k} 자리에 Servc/Cnstwk/Thng)
OPS = {
    "bid": "getBidPblancListInfo{k}",
    "bid_search": "getBidPblancListInfo{k}PPSSrch",
    "pre": "getPublicPrcureThngInfo{k}",
    "plan": "getOrderPlanSttusList{k}",
    "award": "getScsbidListSttus{k}",
    "award_search": "getScsbidListSttus{k}PPSSrch",
}

ROWS = 500          # 한 번에 받는 건수
MAX_PAGES = 40      # 한 구간 최대 페이지 (하루 호출 한도 보호)
WINDOW_DAYS = 7     # 기간을 7일씩 잘라서 조회 (기간 제한 대비)


class ApiError(Exception):
    pass


def _fmt(dt, with_time=True):
    return dt.strftime("%Y%m%d%H%M") if with_time else dt.strftime("%Y%m%d")


def _items(payload):
    """data.go.kr 응답에서 item 목록과 전체 건수를 꺼낸다."""
    resp = payload.get("response", payload)
    header = resp.get("header", {}) or {}
    code = str(header.get("resultCode", "00"))
    if code not in ("00", "0", "INFO-000"):
        raise ApiError(f"{code} {header.get('resultMsg', '')}".strip())
    body = resp.get("body", {}) or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


def _xml_error(text):
    for tag in ("returnAuthMsg", "errMsg", "resultMsg", "returnReasonCode"):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text)
        if m:
            return m.group(1)
    return text[:200]


def call(base_key, op, params, page=1):
    if not DATA_GO_KR_KEY:
        raise ApiError("DATA_GO_KR_KEY 가 비어 있어요. 0_처음설치.bat 을 다시 실행해서 키를 넣어 주세요.")
    url = f"{BASES[base_key]}/{op}"
    q = {"serviceKey": DATA_GO_KR_KEY, "pageNo": page, "numOfRows": ROWS, "type": "json", **params}
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=q, timeout=40)
            text = r.text.strip()
            if text.startswith("<"):
                raise ApiError(_xml_error(text))
            if r.status_code != 200:
                raise ApiError(f"HTTP {r.status_code} {text[:150]}")
            return _items(r.json())
        except requests.exceptions.SSLError as e:  # 일부 PC 에서 https 가 막히면 http 로 한 번 더
            last = e
            url = url.replace("https://", "http://")
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise ApiError(f"연결 실패: {last}")


def fetch_range(base_key, op, start, end, extra=None, with_time=True, window_days=WINDOW_DAYS):
    """start~end 기간을 잘라서 전부 받아 온다. 행마다 _src(출처), _op 를 붙인다."""
    out = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=window_days), end)
        params = {"inqryDiv": 1, "inqryBgnDt": _fmt(cur, with_time), "inqryEndDt": _fmt(nxt, with_time)}
        params.update(extra or {})
        page = 1
        while True:
            items, total = call(base_key, op, params, page)
            for it in items:
                it["_src"], it["_op"] = base_key, op
            out.extend(items)
            if page * ROWS >= total or not items or page >= MAX_PAGES:
                if page >= MAX_PAGES and page * ROWS < total:
                    log.warning("%s %s~%s: %d건 중 일부만 받음 (한도)", op, params["inqryBgnDt"], params["inqryEndDt"], total)
                break
            page += 1
        cur = nxt
    return out


def collect_daily(days):
    """매일 추적: 입찰공고·사전규격·낙찰 (용역·공사·물품) + 발주계획."""
    end = datetime.now()
    start = end - timedelta(days=days)
    rows, errors = [], []
    jobs = []
    for kind, k in KINDS.items():
        jobs += [("bid", OPS["bid"].format(k=k), kind), ("pre", OPS["pre"].format(k=k), kind),
                 ("award", OPS["award"].format(k=k), kind)]
    for src, op, kind in jobs:
        try:
            got = fetch_range(src, op, start, end)
            for it in got:
                it["_kind"] = kind
            rows += got
            log.info("%-6s %-38s %5d건", src, op, len(got))
        except ApiError as e:
            errors.append(f"{op}: {e}")
            log.warning("%s 실패: %s", op, e)
    # 발주계획: 게시일 기준 최근 30일 (자주 안 바뀌므로 넓게)
    for kind, k in KINDS.items():
        op = OPS["plan"].format(k=k)
        try:
            ym_from = end.strftime("%Y%m")
            ym_to = (end + timedelta(days=400)).strftime("%Y%m")
            got = fetch_range("plan", op, end - timedelta(days=max(days, 30)), end,
                              extra={"orderBgnYm": ym_from, "orderEndYm": ym_to}, window_days=30)
            for it in got:
                it["_kind"] = kind
            rows += got
            log.info("%-6s %-38s %5d건", "plan", op, len(got))
        except ApiError as e:
            errors.append(f"{op}: {e}")
            log.warning("%s 실패: %s", op, e)
    return rows, errors


def collect_history(months, keywords):
    """과거 N개월 동안 '이사·이전·운반·보관' 이 공고명에 들어간 공고 = 이사를 실제로 발주한 기관."""
    end = datetime.now()
    start = end - timedelta(days=30 * months)
    rows, errors = [], []
    for kind in ("용역", "물품"):
        op = OPS["bid_search"].format(k=KINDS[kind])
        for kw in keywords:
            try:
                got = fetch_range("bid", op, start, end, extra={"bidNtceNm": kw}, window_days=30)
                for it in got:
                    it["_kind"], it["_kw"] = kind, kw
                rows += got
                log.info("과거공고 %s '%s' %d건", kind, kw, len(got))
            except ApiError as e:
                errors.append(f"{op} '{kw}': {e}")
                log.warning("%s '%s' 실패: %s", op, kw, e)
                if "LIMITED" in str(e).upper() or "한도" in str(e):
                    return rows, errors
    return rows, errors


def collect_awards(months, keywords):
    """같은 기간 같은 단어로 낙찰 결과 = 실제 계약 금액·낙찰업체(경쟁사)·참가업체 수."""
    end = datetime.now()
    start = end - timedelta(days=30 * months)
    rows, errors = [], []
    for kind in ("용역", "물품"):
        op = OPS["award_search"].format(k=KINDS[kind])
        for kw in keywords:
            try:
                got = fetch_range("award", op, start, end, extra={"bidNtceNm": kw}, window_days=30)
                for it in got:
                    it["_kind"], it["_kw"] = kind, kw
                rows += got
                log.info("과거낙찰 %s '%s' %d건", kind, kw, len(got))
            except ApiError as e:
                errors.append(f"{op} '{kw}': {e}")
                log.warning("%s '%s' 실패: %s", op, kw, e)
                if "LIMITED" in str(e).upper() or "한도" in str(e):
                    return rows, errors
    return rows, errors


def check():
    """서비스별로 1건씩 불러서 활용신청·키가 정상인지 확인."""
    end = datetime.now()
    start = end - timedelta(days=1)
    tests = [
        ("입찰공고정보서비스", "bid", OPS["bid"].format(k="Servc"), {}),
        ("입찰공고 검색(공고명)", "bid", OPS["bid_search"].format(k="Servc"), {"bidNtceNm": "이전"}),
        ("사전규격정보서비스", "pre", OPS["pre"].format(k="Servc"), {}),
        ("낙찰정보서비스", "award", OPS["award"].format(k="Servc"), {}),
        ("낙찰 검색(공고명)", "award", OPS["award_search"].format(k="Servc"), {"bidNtceNm": "이전"}),
        ("발주계획현황서비스", "plan", OPS["plan"].format(k="Servc"),
         {"orderBgnYm": end.strftime("%Y%m"), "orderEndYm": end.strftime("%Y%m")}),
    ]
    results = []
    for name, src, op, extra in tests:
        params = {"inqryDiv": 1, "inqryBgnDt": _fmt(start), "inqryEndDt": _fmt(end), **extra}
        try:
            items, total = call(src, op, params)
            sample = sorted(items[0].keys())[:60] if items else []
            results.append((name, True, f"정상 (최근 1일 {total}건)", sample))
        except ApiError as e:
            results.append((name, False, str(e), []))
    return results
