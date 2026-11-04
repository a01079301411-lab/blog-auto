"""공고 한 건을 '우리 일감인가?' 기준으로 골라내고 점수를 매긴다.

점수 기준 (코어 프로필의 기회점수)
  직접 이사·이전·보관 공고 +30 (용역·물품으로 나오면 +20 더) / 이전·개청 명시 +25 / 리모델링·환경개선 등 선행공사 +20
  기존 운영시설(리모델링·개선) +15 / 문서고·사무실·병원 등 +15 / 보관 필요 신호 +10
  대구 근교 +10 / 담당자 연락처 있음 +10 / 원도급사(낙찰업체) 확인 +10
  여성·장애인기업·소액수의·견적 공고 +15 / 지켜보는 사업 +20
  신축(기존 물품 없음) −15 / 특수운송(문화재·의료장비 등)만 −20
  → 60점 이상 '즉시 연락', 40~59 '추적', 40 미만은 버림
"""
import hashlib
import json
import re
from datetime import datetime

from config import DATA

SRC_NAME = {"bid": "입찰공고", "pre": "사전규격", "plan": "발주계획", "award": "낙찰(원도급사)", "contract": "계약"}

TITLE = ("bidNtceNm", "prdctClsfcNoNm", "bizNm", "cntrctNm", "bsnsNm")
ORG = ("dminsttNm", "rlDminsttNm", "orderInsttNm", "ntceInsttNm", "insttNm", "rlDminsttNm", "cntrctInsttNm")
NOTICE_ORG = ("ntceInsttNm", "orderInsttNm")
DATE = ("cntrctCnclsDate", "cntrctDate", "bidNtceDt", "rgstDt", "rcptDt", "nticeDt", "opengDt", "fnlSucsfDate", "rlOpengDt")
DEADLINE = ("bidClseDt", "opninRgstClseDt", "rcptClseDt")
AMOUNT = ("presmptPrce", "asignBdgtAmt", "bdgtAmt", "sumOrderAmt", "orderAmt", "sucsfbidAmt", "thtmCntrctAmt", "totCntrctAmt", "cntrctAmt", "totCnstwkScle")
METHOD = ("cntrctCnclsMthdNm", "bidMethdNm", "prcrmntMethd", "cntrctMthdNm", "sucsfbidMthdNm")
OFFICER = ("cntrctInsttOfclNm", "ntceInsttOfclNm", "ofclNm", "dminsttOfclNm", "exctvNm", "orderInsttOfclNm")
PHONE = ("cntrctInsttOfclTelNo", "ntceInsttOfclTelNo", "ofclTelNo", "dminsttOfclTelNo", "orderInsttOfclTelNo", "telNo")
EMAIL = ("cntrctInsttOfclEmailAdrs", "ntceInsttOfclEmailAdrs", "ofclEmail", "emailAdrs")
DEPT = ("cntrctInsttChrgDeptNm", "cntrctInsttDeptNm", "ntceInsttOfclDeptNm", "dminsttChrgDeptNm", "chrgDeptNm", "deptNm")
WINNER = ("bidwinnrNm", "sucsfbidCorpNm", "corpNm")
WINNER_TEL = ("bidwinnrTelNo", "bidwinnrTelno")
WINNER_CEO = ("bidwinnrCeoNm",)
URL = ("bidNtceDtlUrl", "bidNtceUrl", "dtlUrl", "specDocFileUrl1")
ID = ("bidNtceNo", "bfSpecRgstNo", "orderPlanUntyNo", "dcsnCntrctNo", "untyCntrctNo")


def load_rules():
    rules = json.loads((DATA / "keywords.json").read_text(encoding="utf-8"))
    watch = []
    wl = DATA / "watchlist.txt"
    if wl.exists():
        for line in wl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                watch.append(line)
    rules["_watch"] = watch
    return rules


def pick(item, keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, "", "0", 0):
            return str(v).strip()
    return ""


def _hits(text, words):
    return [w for w in words if w in text]


def _amount(v):
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return 0


def _corp(raw):
    """corpList '[1^주계약업체^단독^업체명^대표자^대한민국^…]' 에서 업체명만."""
    if not raw:
        return ""
    first = re.findall(r"\[([^\]]*)\]", raw)
    parts = (first[0] if first else raw).split("^")
    return (parts[3] if len(parts) > 3 else parts[-1]).strip()[:40]


def normalize(item):
    title = pick(item, TITLE)
    org = pick(item, ORG)
    rec = {
        "출처": SRC_NAME.get(item.get("_src"), item.get("_src", "")),
        "구분": item.get("_kind", ""),
        "제목": title,
        "수요기관": org,
        "공고기관": pick(item, NOTICE_ORG),
        "공고일": pick(item, DATE)[:16],
        "마감일": pick(item, DEADLINE)[:16],
        "금액": _amount(pick(item, AMOUNT) or 0),
        "계약방법": pick(item, METHOD),
        "담당자": pick(item, OFFICER),
        "담당부서": pick(item, DEPT),
        "담당전화": pick(item, PHONE),
        "담당메일": pick(item, EMAIL),
        "낙찰업체": pick(item, WINNER),
        "낙찰업체전화": pick(item, WINNER_TEL),
        "낙찰업체대표": pick(item, WINNER_CEO),
        "번호": pick(item, ID) + (("-" + str(item.get("bidNtceOrd"))) if item.get("bidNtceOrd") else ""),
        "링크": pick(item, URL),
        "낙찰금액": _amount(pick(item, ("sucsfbidAmt", "thtmCntrctAmt", "totCntrctAmt", "cntrctAmt")) or 0),
        "계약업체": _corp(pick(item, ("corpList", "cntrctCorpNm"))),
        "낙찰률": pick(item, ("sucsfbidRate",)),
        "참가업체수": pick(item, ("prtcptCnum",)),
        "공고번호": pick(item, ("bidNtceNo",)),
    }
    # 지역·키워드 판정은 모든 글자를 합쳐서 (필드 이름이 바뀌어도 놓치지 않게)
    rec["_all"] = " ".join(str(v) for k, v in item.items() if not str(k).startswith("_") and isinstance(v, (str, int)))
    rec["_key"] = item.get("_src", "") + ":" + (rec["번호"] or hashlib.md5((title + org).encode()).hexdigest()[:12])
    return rec


def region_of(rec, rules):
    head = " ".join([rec["수요기관"], rec["공고기관"], rec["제목"]])
    # 수요기관이 다른 시·도면 무조건 제외 (조달청 대구지청이 대신 낸 서울·대전 공고 등)
    if _hits(rec["수요기관"], rules.get("타지역", [])) and not _hits(rec["수요기관"], ["대구", "경북", "경상북도"]):
        return ""
    if _hits(head, rules["근교지역"]):
        return "대구근교"
    if _hits(head, rules["대구경북지역"]):
        return "경북"
    # 기관명에 지역이 없을 때 (예: 국가기관) 주소·참가제한지역 등 전체 글자에서 한 번 더
    if _hits(rec["_all"], ["대구광역시", "경상북도", "대구지방조달청"]):
        return "대구경북(주소)"
    return ""


def score(rec, rules):
    """(점수, 이유 목록) 을 돌려준다. 우리 일과 상관없으면 (0, [])."""
    title = rec["제목"]
    text = title + " " + rec["계약방법"] + " " + rec["_all"]
    reasons, s = [], 0

    watch = _hits(title + rec["수요기관"], rules["_watch"])
    excl = _hits(title, rules["제외"])
    direct = _hits(title, rules["직접수요"])
    move = _hits(title, rules["이전개청"])
    pre = _hits(title, rules["선행신호"])

    if excl and not direct and not watch:
        return 0, []
    if _hits(title, rules.get("강제제외", [])) and not _hits(title, ["이사", "집기", "문서", "청사 이전", "사무실 이전"]):
        return 0, []
    if not (direct or move or pre or watch):
        return 0, []

    if direct:
        s += 30; reasons.append("직접수요(" + ",".join(direct[:2]) + ")")
        if rec["구분"] in ("용역", "물품"):
            s += 20; reasons.append("이사 용역 직접 발주")
    if move:
        s += 25; reasons.append("이전·개청(" + ",".join(move[:2]) + ")")
    if pre:
        s += 20; reasons.append("선행공사(" + ",".join(pre[:2]) + ")")
        if _hits(title, ["리모델링", "환경개선", "재구조화", "개보수", "개선", "수선"]):
            s += 15; reasons.append("기존 운영시설")
    if _hits(title, rules["공간유형"]):
        s += 15; reasons.append("사무·문서·병원류")
    if _hits(title, rules["보관신호"]) and (direct or move):
        s += 10; reasons.append("보관 가능성")
    if rec["_region"] == "대구근교":
        s += 10; reasons.append("대구 근교")
    if rec["담당전화"]:
        s += 10; reasons.append("담당자 연락처")
    if rec["낙찰업체"]:
        s += 10; reasons.append("원도급사 확인")
    sole = _hits(text, rules["수의계약신호"])
    if sole and (direct or move):
        s += 15; reasons.append("수의·제한(" + ",".join(sole[:2]) + ")")
    if watch:
        s += 20; reasons.append("관심사업(" + watch[0] + ")")
    if _hits(title, rules["신축감점"]) and not (direct or move):
        s -= 15; reasons.append("신축 −15")
    sub = rules.get("부대공종", [])
    if rec["구분"] == "공사" and not direct and re.search(r"\((" + "|".join(sub) + r")\)|(" + "|".join(sub) + r")\s*공사", title):
        s -= 10; reasons.append("부대공종 −10")
    if _hits(title, rules["특수운송감점"]):
        s -= 20; reasons.append("특수운송 −20")
    return s, reasons


def grade(s):
    return "즉시" if s >= 60 else "추적" if s >= 40 else "제외"


def next_action(rec):
    """점수 이유를 보고 오늘 할 일을 한 줄로."""
    src = rec["출처"]
    if src.startswith("낙찰"):
        who = rec["낙찰업체"] or "낙찰업체"
        tel = f" ({rec['낙찰업체전화']})" if rec["낙찰업체전화"] else ""
        return f"원도급사 {who}{tel} 공무·현장소장에게: 집기·문서 이전이 공사내역에 포함인지, 협력업체 견적 가능한지"
    if src == "사전규격":
        return "사전규격 의견등록 기간: 담당자에게 이전·보관 범위가 들어가는지, 별도 발주인지 문의"
    if src == "발주계획":
        return "발주 전 단계: 담당부서에 이전 시기·별도 이사 발주 여부 확인, 소개서 발송"
    if "직접수요" in rec.get("이유", ""):
        return "공고문·과업지시서 확인 → 참가자격(지역·여성·장애인기업 제한) 확인 → 현장설명/실사 신청 → 견적 제출"
    return "담당자에게 공사 전후 집기 이동·임시보관이 별도 발주되는지 확인, 소개서 발송"


def _deadline_passed(rec):
    digits = re.sub(r"\D", "", rec["마감일"])
    if len(digits) < 8:
        return False
    return digits[:12].ljust(12, "0") < datetime.now().strftime("%Y%m%d%H%M")


def _project_key(rec, rules):
    """같은 기관의 같은 사업(공종만 다른 공고, 재공고)은 하나로 묶는다."""
    t = re.sub(r"\(.*?\)|\[.*?\]", "", rec["제목"])
    t = re.sub(r"(" + "|".join(rules.get("부대공종", []) + ["건축"]) + r")\s*공사", "", t)
    t = re.sub(r"(입찰\s*공고|수의계약\s*안내공고|안내공고|재공고|긴급|공사|용역|\s|\d{4}년?)", "", t)
    stage = "award" if rec["출처"].startswith("낙찰") else "notice"  # 발주계획·사전규격·입찰공고는 한 사업으로
    return stage + "|" + (rec["수요기관"] or rec["공고기관"]) + "|" + t[:16]


def evaluate(items, rules):
    out = {}
    for it in items:
        rec = normalize(it)
        rec["_region"] = region_of(rec, rules)
        if not rec["_region"] or not rec["제목"]:
            continue
        s, reasons = score(rec, rules)
        if s < 40:
            continue
        rec["점수"] = s
        rec["등급"] = grade(s)
        rec["지역"] = rec["_region"]
        rec["이유"] = " · ".join(reasons)
        rec["다음행동"] = next_action(rec)
        if rec["출처"] in ("입찰공고", "사전규격") and _deadline_passed(rec):
            rec["등급"] = "마감"
            rec["다음행동"] = "마감됨 → 낙찰 결과에서 원도급사 확인 후 협력업체 영업 (원도급사 시트·알림에 자동으로 뜸)"
        # 같은 공고가 여러 번 들어오면 점수 높은 것 하나만
        if rec["_key"] not in out or out[rec["_key"]]["점수"] < s:
            out[rec["_key"]] = rec
    # 같은 사업 묶기
    groups = {}
    for rec in out.values():
        k = _project_key(rec, rules)
        g = groups.setdefault(k, [])
        g.append(rec)
    merged = []
    for g in groups.values():
        stage_rank = {"입찰공고": 0, "사전규격": 1, "발주계획": 2}
        g.sort(key=lambda r: (r["등급"] == "마감", -r["점수"], stage_rank.get(r["출처"], 3)))
        top = g[0]
        if len(g) > 1:
            top["이유"] += f" · 같은 사업 {len(g)}건"
            top["_dupkeys"] = [r["_key"] for r in g[1:]]
        merged.append(top)
    order = {"즉시": 0, "추적": 1, "마감": 2}
    return sorted(merged, key=lambda r: (order.get(r["등급"], 3), -r["점수"], r["마감일"] or "9999"))


def is_history_hit(rec, rules):
    """진짜 이사·집기 이전 계약인지 (폐기물 운반·보관함 구입·장비 이전설치 등은 제외)."""
    title = rec["제목"] or ""
    inc = rules.get("이사판정_포함")
    exc = rules.get("이사판정_제외")
    if inc:
        return bool(re.search(inc, title)) and not (exc and re.search(exc, title))
    return bool(_hits(title, rules["직접수요"])) and not _hits(title, rules["제외"])


def move_type(title):
    t = title or ""
    if re.search(r"도서관|장서|도서|자료", t):
        return "도서관·장서 이전"
    if re.search(r"모듈러|임시교사|임시교실", t):
        return "학교 모듈러(임시교사) 이사"
    if re.search(r"조직개편|부서|사무실|청사|사무공간", t):
        return "관공서 사무실·부서 이동"
    if re.search(r"공간재구조화|그린스마트|공간혁신|고교학점제|공간조성|리모델링|환경개선|증개축|개축|공사", t):
        return "학교·시설 공사 전후 집기이전"
    if re.search(r"기록물|문서", t):
        return "문서·기록물 이전"
    return "기타 이사"


def org_type(name):
    n = name or ""
    if any(w in n for w in ("교육청", "교육지원청", "학교", "유치원", "교육연구원")):
        return "교육청·학교"
    if "대학" in n:
        return "대학"
    if any(w in n for w in ("병원", "의료원", "보건소")):
        return "병원·보건"
    if any(w in n for w in ("법원", "검찰", "경찰", "조달청", "우정", "세무", "병무", "보훈", "고용노동", "수사청", "지방청")):
        return "국가기관"
    if any(w in n for w in ("공사", "공단", "진흥원", "재단", "연구원", "테크노파크", "센터", "협회")):
        return "공공기관"
    if any(n.endswith(w) or (w + " ") in n for w in ("구", "군", "시", "도")) or "광역시" in n or "경상북도" in n:
        return "지자체"
    return "기타"


def today():
    return datetime.now().strftime("%Y-%m-%d")
