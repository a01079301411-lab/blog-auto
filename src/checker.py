"""품질 검사. 글이 아래 기준을 모두 통과해야 발행 단계로 간다.

실패 이유 목록을 돌려준다. 빈 목록이면 통과.
"""
import difflib
import re

import formatter
import history
import season
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
# 매 글에 반복되던 상투 문장 (독자가 넘겨 버린다)
STOCK_PHRASES = ("끝까지 보시면", "끝까지 읽으시면", "아시게 됩니다", "들어보셨죠", "들어보셨을")
REPEAT_MIN_CHARS = 20  # 이 길이 이상 같은 문장이 두 번 나오면 반복으로 본다


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

    # 8. 내부링크: 후보가 있으면 1~3개, 없는 번호는 안 됨
    numbers = [int(n) for n in LINK_RE.findall(body)]
    related = related or []
    if [n for n in numbers if not 1 <= n <= len(related)]:
        fails.append("없는 번호의 내부링크를 썼어요. related_posts 번호만 쓰세요.")
    if related and not numbers:
        fails.append("관련 글이 있는데 내부링크가 없어요. 1~3개 연결하세요.")
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

    fails += _repeat_problems(title, body, topic)
    fails += _snippet_problems(title, body, topic)
    fails += _structure_problems(title, body)
    fails += _season_problems(title, body, post.get("tags", []))
    fails += _claim_problems(lines)
    fails += _fact_repeat_problems(lines, topic)
    fails += _near_duplicate_problems(lines)
    return fails


# 'N가지' 제목이면 번호 붙은 소제목이 N개여야 한다 (FAQ, 마무리 소제목은 번호 없이)
NUMBERED_HEADING = re.compile(r"^(기준|방법|이유|체크|포인트|단계)?\s*(\d+)\s*[.)]|^[①-⑩]|^(첫|둘|셋|넷|다섯|여섯|일곱)째")


def _structure_problems(title, body):
    match = re.search(r"(\d+)\s*가지", title)
    if not match:
        return []
    want = int(match.group(1))
    headings = [l.lstrip("#").strip() for l in body.splitlines() if l.strip().startswith("#")]
    numbered = [h for h in headings if NUMBERED_HEADING.match(h)]
    if len(numbered) == want:
        return []
    return [f"제목은 '{match.group(0)}'인데 번호 붙은 소제목이 {len(numbered)}개예요. 제목만 보고 들어온 사람이 "
            f"{want}가지를 바로 찾게, 소제목을 '## 1. ~'부터 '## {want}. ~'까지 정확히 {want}개로 쓰세요 "
            "(질문형이어도 돼요. 자주 묻는 질문, 마무리 소제목은 번호 없이)."]


def _season_problems(title, body, tags):
    words = season.out_of_season(" ".join([title, body, " ".join(tags)]))
    if not words:
        return []
    return [f"지금 계절과 안 맞는 말이 있어요: {', '.join(words)}. "
            "제목, 본문, 태그, 댓글 보기에서 빼고 지금 계절 이야기로 바꾸세요."]


# 다른 업체·보관 방식과 가격을 비교하면서 숫자 근거가 없는 문장
RIVALS = ("컨테이너", "다른 업체", "타 업체", "다른 곳", "다른 회사", "일반 창고", "셀프 스토리지")
COST_CLAIMS = re.compile(r"저렴|싸[다고요지게]|비싸|차이가\s*(크게\s*)?(나지|없)|비용이\s*비슷|가격이\s*비슷|손해")


def _claim_problems(lines):
    bad = []
    for sentence in re.split(r"(?<=[.!])\s+|\n", "\n".join(lines)):
        s = sentence.strip()
        if not s or s.endswith("?") or re.match(r"^Q\s*[.:]", s) or not any(r in s for r in RIVALS):
            continue
        # 쉼표, '~지만'으로 나눈 마디마다 본다. '~수 있다'처럼 인정하는 마디는 괜찮다
        for clause in re.split(r",\s*|지만\s+", s):
            if (COST_CLAIMS.search(clause) and not re.search(r"\d", clause)
                    and not re.search(r"수\s*있|보일|보이", clause)):
                bad.append(s)
                break
    if not bad:
        return []
    return ["다른 업체나 컨테이너와 가격을 비교하는데 숫자 근거가 없어요: " + bad[0]
            + " → 회사 팩트의 숫자(예: 하루 보관료)로 근거를 들거나, 단정하지 말고 판단 기준으로 바꾸세요."]


FACT_TOKEN = re.compile(r"\d[\d,.]*\s*(cm|mm|m|원|만\s*원|시간|분|도|톤|평|년|일|개월|벌|%)")
FACT_MAX = 2  # 같은 숫자 사실은 글 전체에서 2번까지


def _fact_repeat_problems(lines, topic=None):
    # 이 글이 답하는 질문에 들어 있는 숫자(예: 30일 뒤 짐 상태)는 여러 번 나와도 된다
    asked = re.sub(r"\s", "", " ".join((topic or {}).get(k, "") for k in ("question", "keyword", "topic")))
    counts = {}
    for line in lines:
        if _has_phone(line):
            continue
        for m in FACT_TOKEN.finditer(line):
            key = re.sub(r"\s", "", m.group(0))
            if key not in asked:
                counts[key] = counts.get(key, 0) + 1
    over = [f"{k}({n}번)" for k, n in counts.items() if n > FACT_MAX]
    if not over:
        return []
    return ["같은 사실을 너무 자주 반복해요: " + ", ".join(over)
            + f". 한 사실은 {FACT_MAX}번까지만 쓰고, 다시 말할 땐 '앞에서 말씀드린 제습기처럼'처럼 짧게 받으세요."]


NEAR_SAME = 0.8
NEAR_MIN_CHARS = 15


def _near_duplicate_problems(lines):
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+|\n", "\n".join(lines))
                 if len(re.sub(r"\s", "", s)) >= NEAR_MIN_CHARS and not _has_phone(s)]
    for i, a in enumerate(sentences):
        for b in sentences[i + 1:]:
            if a != b and difflib.SequenceMatcher(None, a, b).ratio() >= NEAR_SAME:
                return [f"거의 같은 문장이 두 번 나와요: '{a}' / '{b}'. 한 번만 쓰거나 다른 내용으로 바꾸세요."]
    return []


# 질문형 소제목 바로 아래 첫 문장이 이렇게 시작하면 떼어 가도 답이 안 된다 (스니펫, AI 브리핑)
WEAK_ANSWER_START = re.compile(r"^((네|아니요|아니오)[,.!\s]|이것|이건|그건|그것|아래|다음과|위에서|앞에서)")
TITLE_KEYWORD_WITHIN = 10  # 메인 키워드는 제목 앞 10글자 안에서 시작해야 한다


def _snippet_problems(title, body, topic):
    """검색 결과 제목과 답 상자에 맞는 모양인지: 키워드가 제목 앞쪽에, 질문 소제목 아래 첫 문장이 완결된 답."""
    fails = []
    match = _keyword_re(topic["keyword"]).search(title)
    if match and match.start() > TITLE_KEYWORD_WITHIN:
        fails.append(f"메인 키워드 '{topic['keyword']}'를 제목 맨 앞 {TITLE_KEYWORD_WITHIN}글자 안으로 옮기세요.")
    lines = [l.strip() for l in body.splitlines()]
    weak = []
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        if not QUESTION_END.search(heading):
            continue
        answer = next((l for l in lines[i + 1:] if l and not PHOTO_RE.fullmatch(l) and not LINK_RE.fullmatch(l)), "")
        if answer.startswith("#") or WEAK_ANSWER_START.match(answer.replace("**", "")):
            weak.append(heading)
    if weak:
        fails.append("질문형 소제목 바로 아래 첫 문장을 그 문장만 읽어도 답이 되게 쓰세요 "
                     "(네, 아래에서, 이건 등으로 시작하지 말고 주어를 명사로): " + weak[0])
    return fails


def _repeat_problems(title, body, topic):
    """매 글이 같은 틀이 되지 않게: 제목의 경력 숫자, 'N가지', 상투 문장, 같은 문장 반복."""
    fails = []
    if re.search(r"11\s*년", title) and topic.get("title_type") != "권위 부여형":
        fails.append("제목에 11년은 권위 부여형 제목일 때만 써요. 경력은 본문에서 보여주세요.")
    if re.search(r"\d+\s*가지", title) and topic.get("title_type") != "숫자 목록형":
        fails.append(f"이번 제목 유형은 {topic.get('title_type')}이에요. 'N가지'는 숫자 목록형일 때만 써요.")
    used = [p for p in STOCK_PHRASES if p in body]
    if used:
        fails.append("매 글에 반복되는 상투 문장을 빼세요: " + ", ".join(used))
    seen, repeated = set(), []
    for sentence in re.split(r"(?<=[.?!])\s+|\n", body):
        key = re.sub(r"\s", "", sentence)
        if len(key) < REPEAT_MIN_CHARS or _has_phone(sentence):  # 전화번호 연락 유도는 두 번 나와도 된다
            continue
        if key in seen and sentence.strip() not in repeated:
            repeated.append(sentence.strip())
        seen.add(key)
    if repeated:
        fails.append("같은 문장이 두 번 나와요 (FAQ 답이 본문을 되풀이하는지 확인): " + repeated[0])
    return fails


def _has_phone(line):
    digits = re.sub(r"\D", "", COMPANY_PHONE)
    return bool(digits) and digits in re.sub(r"\D", "", line)


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
