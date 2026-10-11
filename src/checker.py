"""품질 검사. 글이 아래 기준을 모두 통과해야 발행 단계로 간다.

실패 이유 목록을 돌려준다. 빈 목록이면 통과.
"""
import difflib
import re

import formatter
import history
from config import COMPANY_PHONE, DATA_DIR, SAMPLES_DIR

MIN_CHARS = 2000
KEYWORD_MIN, KEYWORD_MAX = 5, 8
MIN_QUESTION_HEADINGS = 3
MIN_FAQ = 4
MIN_FACTS = 2
SIMILAR_TITLE = 0.75
SIMILAR_SAMPLE_TITLE = 0.6
SIMILAR_OPENING = 0.7
MAX_LINKS = 3
MIN_PHOTOS = 4  # 받은 사진이 이보다 적으면 받은 만큼
CTA_WORDS = ("전화", "문의", "연락", "상담")
# 지역명 뒤에 붙어도 지역명으로 보는 글자 (예: 구미에서, 포항까지). '상주하는' 같은 말은 제외된다.
PARTICLES = "에의은는이가을를도로시군구과와까"
# 물음표가 없어도 질문 어미(~나요, ~까요, ~나, ~는지 등)로 끝나면 질문형 소제목으로 본다
QUESTION_END = re.compile(r"(\?|나요|까요|가요|ㄴ가|인가|는가|을까|할까|는지|인지|을지|나|까)\s*$")
PHOTO_RE = re.compile(r"\[사진:\s*([^\]]+?)\s*\]")
LINK_RE = re.compile(r"\[링크:\s*(\d+)\s*\]")


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
        line = LINK_RE.sub("", PHOTO_RE.sub("", line)).replace("**", "").lstrip("#").strip()
        if line:
            lines.append(line)
    return lines


def sample_title(path=SAMPLES_DIR / "sample_storage_post.md"):
    match = re.search(r"제목:\**\s*(.+)", path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else ""


def check(post, topic, photo_set=None, related=None):
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
    questions = [h for h in headings if QUESTION_END.search(h)]
    if not headings:
        fails.append("소제목이 없어요. 소제목은 '## '로 시작하는 줄에 따로 쓰세요.")
    elif len(questions) < MIN_QUESTION_HEADINGS:
        fails.append(
            f"질문형 소제목이 {len(questions)}개예요. '## '로 시작하는 소제목 중 {MIN_QUESTION_HEADINGS}개 이상을 "
            "물음표로 끝나는 질문으로 쓰세요. 예: ## 몇 달 맡기면 보관료는 얼마나 드나요?"
        )
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
        fails.append("본문 중간(강점 사진 바로 아래)에 전화번호가 들어간 연락 유도가 없어요. "
                     "예: 전화 상담 " + (COMPANY_PHONE or "전화번호"))

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
    used = set(PHOTO_RE.findall(body)) & allowed
    if allowed and len(used) < min(len(allowed), MIN_PHOTOS):
        fails.append(f"사진을 {len(used)}장만 썼어요. 받은 사진 {len(allowed)}장 중 "
                     f"{min(len(allowed), MIN_PHOTOS)}장 이상을 소제목마다 나눠 넣으세요.")

    # 8. 내부링크: 후보가 2개 이상이면 2~3개, 1개면 1개, 없는 번호는 안 됨
    numbers = [int(n) for n in LINK_RE.findall(body)]
    related = related or []
    if [n for n in numbers if not 1 <= n <= len(related)]:
        fails.append("없는 번호의 내부링크를 썼어요. related_posts 번호만 쓰세요.")
    if related and not numbers:
        fails.append("관련 글이 있는데 내부링크가 없어요. 2~3개 연결하세요.")
    elif len(related) >= 2 and len(set(numbers)) < 2:
        fails.append("관련 글이 2개 이상 있는데 내부링크가 1개뿐이에요. 서로 다른 글 2~3개를 연결하세요.")
    if len(numbers) > MAX_LINKS:
        fails.append(f"내부링크가 {len(numbers)}개예요. {MAX_LINKS}개 이하로 줄이세요.")

    # 9. 매번 다르게: 샘플 글, 최근 글과 제목·첫 문장이 비슷하면 안 됨
    def similar(a, b):
        return difflib.SequenceMatcher(None, a, b).ratio()

    sample = sample_title()
    if sample and similar(title, sample) >= SIMILAR_SAMPLE_TITLE:
        fails.append(f"샘플 글 제목과 문장 구조가 너무 비슷해요: {sample}")
    first = formatter.opening(formatter.format_body(body))
    for record in history.within_days(history.load(), 60):
        if similar(title, record.get("title", "")) >= SIMILAR_TITLE:
            fails.append(f"최근 글 제목과 너무 비슷해요: {record['title']}")
            break
    for record in history.load()[-10:]:
        if record.get("opening") and similar(first, record["opening"]) >= SIMILAR_OPENING:
            fails.append(f"최근 글과 첫 문장이 너무 비슷해요: {record['opening']}")
            break

    return fails


def _has_middle_cta(body, photo_set):
    """본문 중간(앞쪽 85% 안)에 전화번호가 들어간 연락 유도가 있는지.
    사진이 있는 글이면 그 연락 유도가 사진 바로 아래(4줄 이내)에 있어야 한다."""
    digits = re.sub(r"\D", "", COMPANY_PHONE)
    if not digits:
        return True
    raw = [l.strip() for l in body.splitlines() if l.strip()]
    end = int(len(raw) * 0.85)

    def has_phone(line):
        return digits in re.sub(r"\D", "", line)

    if photo_set:
        for i, line in enumerate(raw[:end]):
            if PHOTO_RE.fullmatch(line):
                after = [l for l in raw[i + 1:i + 5] if not PHOTO_RE.fullmatch(l)]
                if any(has_phone(l) for l in after):
                    return True
        return False
    return any(has_phone(l) for l in raw[int(len(raw) * 0.2):end])
