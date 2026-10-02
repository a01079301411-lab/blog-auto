"""품질 검사. 글이 아래 기준을 모두 통과해야 발행 단계로 간다.

실패 이유 목록을 돌려준다. 빈 목록이면 통과.
"""
import difflib
import re

import history
from config import COMPANY_PHONE, DATA_DIR

MIN_CHARS = 2000
KEYWORD_MIN, KEYWORD_MAX = 5, 8
MIN_QUESTION_HEADINGS = 3
MIN_FAQ = 4
MIN_FACTS = 2
SIMILAR_TITLE = 0.75
CTA_WORDS = ("전화", "문의", "연락", "상담")
# 지역명 뒤에 붙어도 지역명으로 보는 글자 (예: 구미에서, 포항까지). '상주하는' 같은 말은 제외된다.
PARTICLES = "에의은는이가을를도로시군구과와까"
PHOTO_RE = re.compile(r"\[사진:\s*([^\]]+?)\s*\]")


def load_forbidden(path=DATA_DIR / "forbidden.md"):
    """forbidden.md에서 (지역명 목록, 금지 표현 목록)을 읽는다."""
    regions, phrases, section = [], [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line
            continue
        text = line.strip()
        if not text or text.startswith(("#", "(")) or ("," not in text and " " in text):
            continue
        items = [i.strip() for i in text.split(",") if i.strip()]
        (regions if "지역" in section else phrases).extend(items)
    return regions, phrases


def _keyword_re(keyword):
    # '대구 실내보관이사'와 '대구실내보관이사'를 같은 것으로 센다
    return re.compile(r"\s*".join(map(re.escape, keyword.replace(" ", ""))))


def _text_lines(body):
    """사진 표시, 소제목 기호, 굵게 표시를 뺀 본문 줄."""
    lines = []
    for line in body.splitlines():
        line = PHOTO_RE.sub("", line).replace("**", "").lstrip("#").strip()
        if line:
            lines.append(line)
    return lines


def check(post, topic, photo_set=None):
    title, body = post["title"], post["body"]
    lines = _text_lines(body)
    plain = "\n".join(lines)
    fails = []

    # 1. 분량
    if len(plain) < MIN_CHARS:
        fails.append(f"본문이 {len(plain)}자예요. {MIN_CHARS}자 이상 써야 해요.")

    # 2. 메인 키워드
    kw = _keyword_re(topic["keyword"])
    if not kw.search(title):
        fails.append(f"제목에 메인 키워드 '{topic['keyword']}'가 없어요.")
    first_sentences = re.split(r"(?<=[.?!])\s+", " ".join(lines))[:3]
    if not kw.search(" ".join(first_sentences)):
        fails.append(f"첫 3문장 안에 메인 키워드 '{topic['keyword']}'가 없어요.")
    count = len(kw.findall(title + "\n" + plain))
    if not KEYWORD_MIN <= count <= KEYWORD_MAX:
        fails.append(f"메인 키워드가 제목+본문에 {count}번 나와요. {KEYWORD_MIN}~{KEYWORD_MAX}번이어야 해요.")

    # 3. 질문형 소제목, FAQ
    headings = [l.lstrip("#").strip() for l in body.splitlines() if l.strip().startswith("#")]
    questions = [h for h in headings if h.endswith("?")]
    if len(questions) < MIN_QUESTION_HEADINGS:
        fails.append(f"질문형 소제목이 {len(questions)}개예요. {MIN_QUESTION_HEADINGS}개 이상이어야 해요.")
    faq = sum(1 for l in lines if re.match(r"^Q\s*[.:]", l))
    if faq < MIN_FAQ:
        fails.append(f"FAQ가 {faq}개예요. {MIN_FAQ}개 이상이어야 해요.")

    # 4. 회사 팩트
    if len(post.get("used_facts", [])) < MIN_FACTS:
        fails.append(f"회사 팩트가 {MIN_FACTS}개 이상 들어가야 해요.")

    # 5. 전화번호와 연락 유도 (중간 1회 + 마무리 1회)
    if COMPANY_PHONE and COMPANY_PHONE not in "\n".join(lines[-15:]):
        fails.append("마무리 부분에 전화번호가 없어요.")
    if not _has_middle_cta(body, photo_set):
        fails.append("본문 중간(사진 바로 아래)에 연락 유도 문장이 없어요.")

    # 6. 금지 표현
    regions, phrases = load_forbidden()
    full = title + "\n" + plain
    found = [p for p in phrases if p in full]
    found += [r for r in regions if re.search(re.escape(r) + f"(?![가-힣])|{re.escape(r)}(?=[{PARTICLES}])", full)]
    if found:
        fails.append("쓰면 안 되는 표현이 있어요: " + ", ".join(sorted(set(found))))

    # 7. 채워지지 않은 자리표시, 없는 사진
    if "{{" in full or "}}" in full:
        fails.append("채워지지 않은 {{ }} 자리표시가 남아 있어요.")
    allowed = {p.name for p in photo_set["files"]} if photo_set else set()
    unknown = [f for f in PHOTO_RE.findall(body) if f not in allowed]
    if unknown:
        fails.append("목록에 없는 사진을 썼어요: " + ", ".join(unknown))

    # 8. 최근 글과 제목이 너무 비슷한지
    for record in history.within_days(history.load(), 60):
        ratio = difflib.SequenceMatcher(None, title, record.get("title", "")).ratio()
        if ratio >= SIMILAR_TITLE:
            fails.append(f"최근 글 제목과 너무 비슷해요: {record['title']}")
            break

    return fails


def _has_middle_cta(body, photo_set):
    """본문 앞쪽 80% 안에서, 사진 바로 아래(4줄 이내)에 연락 유도 문장이 있는지.
    사진이 없는 글이면 본문 중간(20~80%)에 연락 유도 문장이 있는지만 본다."""
    raw = [l.strip() for l in body.splitlines() if l.strip()]
    end = int(len(raw) * 0.8)
    if photo_set:
        for i, line in enumerate(raw[:end]):
            if PHOTO_RE.fullmatch(line):
                after = [l for l in raw[i + 1:i + 5] if not PHOTO_RE.fullmatch(l)]
                if any(w in l for l in after for w in CTA_WORDS):
                    return True
        return False
    return any(w in l for l in raw[int(len(raw) * 0.2):end] for w in CTA_WORDS)
