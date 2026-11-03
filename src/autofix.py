"""AI가 자주 틀리는 것 중 프로그램이 확실하게 고칠 수 있는 것은 다시 쓰게 하지 않고 바로 고친다.

- 목록에 없는 사진 이름 → 이름이 가장 비슷한 안 쓴 사진으로 바꾸거나, 없으면 뺀다
- 지금 계절과 안 맞는 말(10월의 장마 등) → 계절 없는 말로 바꾼다
- 마무리에 전화번호가 없으면 → 마지막 줄에 회사 이름과 전화번호를 붙인다
- 본문 가운데에 연락 유도가 없으면 → 두 번째 소제목의 첫 문단 뒤에 넣는다
"""
import difflib
import re

import checker
import season
from config import COMPANY_PHONE

# 계절 말 → 계절과 상관없는 말
SEASON_SWAP = {
    "장마철": "습한 날", "장마": "습한 날씨", "폭염": "더위", "무더위": "더위", "열대야": "더운 밤",
    "한여름": "여름", "한파": "추위", "한겨울": "겨울", "폭설": "눈 오는 날", "혹한": "추위",
    "동파": "배관 얼음", "벚꽃": "봄꽃", "황사": "미세먼지",
}
COMPANY_LINE = "대구토탈홈서비스 로젠이사 전화 상담 {phone}"
MIDDLE_CTA = "방문견적은 무료이고 보통 10분에서 15분이면 끝납니다.\n전화 상담 {phone}"


def _fix_photos(post, photo_set, notes):
    allowed = [p.name for p in photo_set["files"]] if photo_set else []
    used = set(checker.PHOTO_RE.findall(post["body"])) & set(allowed)

    def swap(match):
        name = match.group(1).strip()
        if name in allowed:
            return match.group(0)
        spare = [a for a in allowed if a not in used]
        best = difflib.get_close_matches(name, spare, n=1, cutoff=0.6)
        if best:
            used.add(best[0])
            notes.append(f"목록에 없는 사진 {name} → {best[0]}")
            return f"[사진:{best[0]}]"
        notes.append(f"목록에 없는 사진 {name} 을 뺐어요")
        return ""

    post["body"] = checker.PHOTO_RE.sub(swap, post["body"])


def _fix_season(post, notes):
    words = season.out_of_season(" ".join([post["title"], post.get("quote", ""), post["body"], " ".join(post["tags"])]))
    if not words:
        return
    for word in sorted(words, key=len, reverse=True):
        for w in sorted((k for k in SEASON_SWAP if word in k or k in word), key=len, reverse=True):
            for key in ("title", "quote", "body"):
                post[key] = post.get(key, "").replace(w, SEASON_SWAP[w])
            post["photo_captions"] = {f: c.replace(w, SEASON_SWAP[w]) for f, c in post["photo_captions"].items()}
    post["tags"] = [t for t in post["tags"] if not season.out_of_season(t)]
    notes.append("계절 안 맞는 말 바꿈: " + ", ".join(words))


def _fix_phone(post, notes):
    if not COMPANY_PHONE:
        return
    lines = checker._text_lines(post["body"])
    if COMPANY_PHONE not in "\n".join(lines[-15:]):
        post["body"] = post["body"].rstrip() + "\n\n" + COMPANY_LINE.format(phone=COMPANY_PHONE)
        notes.append("마무리에 전화번호를 붙였어요")
    if checker._has_middle_cta(post["body"], None):
        return
    body = post["body"].splitlines()
    headings = [i for i, l in enumerate(body) if l.strip().startswith("#")]
    start = headings[1] if len(headings) > 1 else len(body) // 2
    at = next((i for i in range(start + 1, len(body)) if not body[i].strip() and body[i - 1].strip()
               and not body[i - 1].strip().startswith(("#", "["))), None)
    if at is None:
        return
    body[at:at] = ["", *MIDDLE_CTA.format(phone=COMPANY_PHONE).splitlines()]
    post["body"] = "\n".join(body)
    notes.append("본문 가운데에 연락 유도를 넣었어요")


def fix(post, photo_set):
    """고친 내용 목록을 돌려준다. post는 그 자리에서 고친다."""
    notes = []
    _fix_photos(post, photo_set, notes)
    _fix_season(post, notes)
    _fix_phone(post, notes)
    return notes
