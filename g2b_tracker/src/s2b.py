"""학교장터(S2B) 견적요청·공고 추적 (로그인 없이 보는 공개 공고 목록).
학교·교육청의 소액 이사·집기 이전은 나라장터가 아니라 학교장터 '견적요청'으로 많이 올라온다.
화면 구조는 MIT 라이선스 k-skill(s2b-notice-search) 분석을 참고했다. 화면이 바뀌면 0건이 될 수 있다(오류로 표시)."""
import html as H
import logging
import re
from datetime import datetime, timedelta

import requests

log = logging.getLogger(__name__)
URL = "https://www.s2b.kr/S2BNCustomer/tcmo001.do"
KEYWORDS = ["이사", "이전", "이삿짐", "집기", "장서", "보관", "재배치", "물품 이동"]
MOVE = re.compile(r"(이사|이삿짐|집기|비품|물품|가구|교구|장서|도서|자료|문서|기록물|사무실|교실|행정실|도서관).{0,8}(이전|이동|이송|운반|재배치|보관)"
                  r"|이전\s*(용역|작업)|이사\s*(용역|업체|작업)|이삿짐|임시\s*보관|짐\s*보관")
NOT_MOVE = re.compile(r"이사회|이사장|폐기|철거|구입|구매|제작|설치\s*공사|전기|통신|CCTV|급식|방역|청소|소독")
DAEGYEONG = ("대구", "경북", "경상북도", "경산", "칠곡", "고령", "성주", "군위", "달성", "구미", "김천", "영천", "포항",
             "경주", "안동", "상주", "문경", "영주", "청도", "의성", "예천", "봉화", "울진", "영덕", "청송", "영양", "울릉")


def _clean(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _date(s):
    m = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})(?:\s+(\d{1,2}:\d{2}))?", s or "")
    return (f"{m[1]}-{m[2]}-{m[3]}" + (f" {m[4]}" if m[4] else "")) if m else ""


def parse_list(page):
    """목록 HTML → [{번호, 제목, 기관, 구분, 계약, 공고일, 마감일}]. 한 공고가 <tr> 두 줄로 나뉘어도 합친다."""
    rows = re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", page, re.I)
    out, i = [], 0
    while i < len(rows):
        got = _row(rows[i])
        if not got and i + 1 < len(rows):
            got = _row(rows[i] + rows[i + 1])
            if got:
                i += 1
        if got:
            out.append(got)
        i += 1
    return out


def _row(tr):
    cells = re.findall(r"<t[dh]\b[^>]*>([\s\S]*?)</t[dh]>", tr, re.I)
    if len(cells) < 4:
        return None
    a = re.search(r"<a\b[^>]*?(?:href=[\"']javascript:|onclick=[\"'])\s*(f_detail|fn_detail|goView)\(([^)]*)\)[^>]*>([\s\S]*?)</a>", tr, re.I)
    if not a:
        return None
    args = re.findall(r"'([^']*)'|\"([^\"]*)\"", a[2])
    code = next((x or y for x, y in args if x or y), "")
    texts = [t for t in (_clean(c) for c in cells) if t]
    title = _clean(a[3])
    dates = [d for d in (_date(t) for t in texts) if d]
    kind = next((t for t in texts if t in ("물품", "공사", "용역")), "")
    org = next((t for t in texts if t not in (title, kind) and re.search(r"(학교|교육청|교육지원청|유치원|기관|센터)$", t)), "")
    contract = next((t for t in texts if "수의" in t or "입찰" in t), "")
    if not code or not title or not dates:
        return None
    return {"번호": code, "제목": title, "기관": org, "구분": kind, "계약": contract,
            "공고일": dates[0], "마감일": dates[1] if len(dates) > 1 else ""}


def search(keyword, start, end, session=None):
    s = session or requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": URL})
    out, page = [], 1
    while page <= 10:
        data = {"forwardName": "list01", "pageNo": page, "estimateCode": "", "tender_step_code": "", "page_flag": "",
                "process_yn": "Y", "search_yn": "Y", "tender_sep1": "1", "tender_name": keyword,
                "tender_sep2": "1", "tender_date_start": start.strftime("%Y%m%d"), "tender_date_end": end.strftime("%Y%m%d")}
        r = s.post(URL, data=data, timeout=40)
        r.encoding = r.apparent_encoding or "utf-8"
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        if re.search(r"로그인이 필요|captcha|접근이 차단", r.text, re.I):
            raise ValueError("학교장터가 로그인/차단 화면을 보냄")
        rows = parse_list(r.text)
        out += rows
        if len(rows) < 10:
            break
        page += 1
    return out


def collect(days=3):
    """최근 N일 학교장터 공고 중 이사·집기 이전 건. 반환 (목록, 오류)."""
    end = datetime.now()
    start = end - timedelta(days=max(days, 1))
    sess = requests.Session()
    try:
        sess.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as e:
        return [], [f"학교장터 연결 실패: {e}"]
    found, errors = {}, []
    for kw in KEYWORDS:
        try:
            for row in search(kw, start, end, sess):
                t = row["제목"]
                if (MOVE.search(t) or re.search(r"이사|이삿짐", t)) and not NOT_MOVE.search(t):
                    found[row["번호"]] = row
        except (requests.RequestException, ValueError) as e:
            errors.append(f"학교장터 '{kw}': {e}")
            break
    today = end.strftime("%Y-%m-%d %H:%M")
    rows = [r for r in found.values() if not r["마감일"] or r["마감일"] >= today[:len(r["마감일"])]]
    for r in rows:
        r["대경"] = any(x in r["기관"] + r["제목"] for x in DAEGYEONG)
    return rows, errors


def link(code=""):
    """학교장터 공고 목록 화면 (공고번호로 검색해서 열기). 상세 화면은 학교장터가 주소를 따로 주지 않는다."""
    return URL


def to_recs(rows):
    """브리핑·엑셀용 레코드로 변환 (나라장터 레코드와 같은 열)."""
    out = []
    for r in rows:
        hot = r["대경"]
        out.append({"등급": "즉시" if hot else "추적", "점수": 90 if hot else 50, "출처": "학교장터", "제목": r["제목"],
                    "수요기관": r["기관"], "공고기관": r["기관"], "마감일": r["마감일"], "공고일": r["공고일"],
                    "링크": link(r["번호"]), "번호": r["번호"], "지역": "대구경북" if hot else "타지역",
                    "구분": r["구분"], "계약방법": r["계약"], "담당자": "", "담당전화": "", "담당메일": "",
                    "낙찰업체": "", "낙찰업체전화": "", "참가업종": "", "참가가능지역": "",
                    "다음행동": f"학교장터 로그인 → 견적요청 번호 {r['번호']} 검색 → 견적서 제출 (필요하면 행정실에 현장 확인 전화)",
                    "_key": f"s2b:{r['번호']}", "_dupkeys": []})
    return out
