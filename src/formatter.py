"""AI가 쓴 본문을 사장님 블로그 규칙에 맞게 바꾼다.

- 한 줄은 공백 포함 28자까지, 어절 단위로 끊되 뜻이 끊기지 않는 자리(쉼표, ~고, ~며 뒤)에서 끊는다.
  '한두 / 박스', '어느 / 쪽이'처럼 붙어 다니는 말은 떼지 않는다.
- 문장이 끝나면 새 줄에서 시작한다.
- 같은 내용(한 문단)은 3~4줄로 묶고, 내용이 바뀔 때(문단이 바뀔 때)만 한 줄 띄운다.
- 소제목 앞에는 빈 줄 2개.
- 특수문자는 모두 뺀다.
- 사진은 연달아 붙이지 않고, 소제목 하나당 2장까지 문단 사이에 나눠 넣는다.
- 전화번호가 있는 줄은 굵게 하고, 누르면 전화가 걸리는 링크를 걸 줄로 표시한다.

결과는 '블록' 목록이다. 발행 프로그램이 이 목록을 보고 한 줄씩 입력한다.
  {"type": "line", "text": "...", "bold": False, "phone": False}  ← phone: 전화 링크를 걸 줄
  {"type": "heading", "text": "..."}
  {"type": "photo", "file": "창고_01.jpg"}
  {"type": "link", "title": "...", "url": "https://..."}
  {"type": "blank"}
"""
import re

from config import COMPANY_PHONE

LINE_MAX = 28
PHOTOS_PER_SECTION = 2
PARAGRAPH_MAX_LINES = 4
PHOTO_RE = re.compile(r"^\[사진:\s*([^\]]+?)\s*\]$")
LINK_RE = re.compile(r"^\[링크:\s*(\d+)\s*\]$")
MARKER_SPLIT = re.compile(r"(\[(?:사진|링크):[^\]]+\])")
LIST_RE = re.compile(r"^(- |[A-Z]\. |Q\. |\*\*Q|\d+\. )")

# ── 특수문자 정리 ──
REPLACEMENTS = [
    (re.compile(r"\s*\(([^()]*)\)"), r" \1"),  # 7,000원(정찰제)이고 → 7,000원 정찰제이고
    (re.compile(r"(\d)\s*~\s*(\d)"), r"\1에서 \2"),  # 10~15분 → 10에서 15분
    (re.compile(r"℃|°C|°"), "도"),
    (re.compile(r"\s*[·ㆍ]\s*"), ", "),  # 대구·경산 → 대구, 경산
    (re.compile(r"(?<!\d)-|-(?!\d)"), " "),  # 하이픈은 전화번호(숫자 사이)만 남긴다
]
NOT_ALLOWED = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ\s.,?!%\-]")


def sanitize(text):
    """한글, 영어, 숫자, 띄어쓰기, . , ? ! % 와 전화번호 하이픈만 남긴다."""
    for pattern, repl in REPLACEMENTS:
        text = pattern.sub(repl, text)
    text = NOT_ALLOWED.sub(" ", text)
    text = re.sub(r"\s+([.,?!])", r"\1", text)  # 기호 앞 띄어쓰기 정리
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# 줄을 끊기 좋은 곳: 쉼표 뒤, 이어 주는 말(~고, ~며, ~면서, ~지만, ~는데 …) 뒤
GOOD_ENDINGS = ("고", "며", "면", "서", "니라", "지만", "는데", "은데", "니다", "니까", "도록", "거나", "든지",
                "어서", "아서", "해서", "라서", "면서", "려면", "다면", "는지", "인지", "을지", "까지", "부터")
SHORT_VERBS = {"하고", "있고", "없고", "되고", "하며", "하면", "되면", "있면", "해서", "돼서", "와서", "가서", "봐서"}
# 끊으면 안 되는 곳: 뒤 낱말을 꾸미는 말 다음 (한두 / 박스, 어느 / 쪽이)
MODIFIERS = {"한", "두", "세", "네", "한두", "두세", "서너", "몇", "이", "그", "저", "어느", "어떤", "무슨",
             "이런", "그런", "저런", "모든", "다른", "각", "약", "총", "매", "첫", "새", "온", "전", "더", "덜",
             "가장", "제일", "꼭", "잘", "안", "못", "다", "좀", "또", "딱"}
# 이런 말로 시작하는 낱말은 앞 낱말과 붙어 있어야 한다 (박스, 개, 번, 수, 때 …)
BOUND_NOUNS = ("박스", "개", "번", "분", "곳", "것", "수", "때", "중", "명", "장", "대", "톤", "원",
               "일", "시간", "정도", "만큼", "뿐", "데", "쪽", "채", "벌", "동안", "이상", "이하", "이내")
PARTICLES = ("이", "가", "을", "를", "은", "는", "에", "에서", "으로", "로", "와", "과", "도", "만", "엔", "께")
LINE_MIN = 16      # 마지막 줄이 아니면 이보다 짧게 끊지 않는다
ORPHAN_MIN = 10    # 마지막 줄이 이보다 짧으면 앞줄과 나눠 갖는다


def _break_cost(prev, nxt):
    """prev 낱말 뒤에서 줄을 끊을 때의 부담 (작을수록 좋은 자리)."""
    word = prev.rstrip(".,?!")
    if prev.endswith(","):
        return -6
    cost = 0
    if word in MODIFIERS or re.fullmatch(r"[\d,.]+", word):
        cost += 14  # 숫자나 꾸미는 말 뒤 (20 / cm, 한두 / 박스)
    if len(nxt) <= 5 and nxt.startswith(BOUND_NOUNS):
        cost += 10
    ending = next((e for e in GOOD_ENDINGS if word.endswith(e)), "")
    # '창고', '사진' 같은 이름씨가 '고', '서'로 끝나는 것과 헷갈리지 않게 한 글자 끝은 3글자 이상 낱말만
    if ending and (len(ending) > 1 or len(word) >= 3 or word in SHORT_VERBS):
        cost -= 4
    elif word.endswith(PARTICLES) and len(word) > 1:
        cost -= 3  # 조사로 끝나는 낱말 뒤 (창고 환경이 / 짐 상태를)
    elif word.endswith("의"):
        cost += 4
    if len(word) == 1 and re.fullmatch(r"[가-힣]", word):
        cost += 8  # 한 글자 낱말은 뒤 낱말과 붙어 있는 경우가 많다 (짐 / 상태)
    if re.fullmatch(r"[가-힣]", nxt.rstrip(".,?!")):
        cost += 6  # 다음 줄이 한 글자 낱말로 시작하면 앞 낱말과 떨어져 보인다 (창고 / 안)
    return cost


def wrap(sentence):
    """한 문장을 28자 이하 줄로 나눈다. 글자 수만 보지 않고 뜻이 끊기지 않는 자리에서 나눈다.

    줄 길이를 고르게, 쉼표나 이어 주는 말 뒤에서 끊고, '한두 / 박스'처럼 붙어 다니는 말은
    떼지 않는 조합 중 가장 자연스러운 것을 고른다.
    """
    words = sentence.split()
    if not words:
        return []
    n = len(words)
    best = [0.0] + [float("inf")] * n  # best[j]: 앞의 j낱말을 줄로 나눈 가장 작은 부담
    back = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            line = " ".join(words[i:j])
            if len(line) > LINE_MAX and j - i > 1:
                break
            if best[i] == float("inf"):
                continue
            last = j == n
            if last:
                cost = 30 if len(line) < ORPHAN_MIN and i > 0 else 0
            else:
                slack = LINE_MAX - len(line)
                cost = slack * slack / 14 + (40 if len(line) < LINE_MIN else 0)
                cost += _break_cost(words[j - 1], words[j])
            if best[i] + cost < best[j]:
                best[j], back[j] = best[i] + cost, i
    lines, j = [], n
    while j > 0:
        i = back[j]
        lines.append(" ".join(words[i:j]))
        j = i
    return lines[::-1]


def _split_sentences(line):
    # 'Q.', 'A.', '1.' 뒤는 문장 끝이 아니다
    return [s for s in re.split(r"(?<=[.?!])(?<![A-Z0-9]\.)\s+", line) if s.strip()]


def _chunks(sentences):
    """문장(줄 묶음) 목록을 4줄 이하 묶음으로 모은다. 문장 중간에서는 절대 나누지 않는다."""
    groups, cur = [], []
    for lines in sentences:
        if cur and len(cur) + len(lines) > PARAGRAPH_MAX_LINES:
            groups.append(cur)
            cur = []
        cur = cur + lines
    if cur:
        groups.append(cur)
    return groups


def _paragraph_blocks(paragraph):
    blocks = []
    if any(LIST_RE.match(line) for line in paragraph):
        # 목록, FAQ, 보기(A, B, C)는 한 줄에 하나씩, 사이를 띄우지 않는다
        for line in paragraph:
            # **굵게** 표시가 있거나 FAQ 질문(Q.)이면 굵게
            bold = (line.startswith("**") and line.endswith("**")) or bool(re.match(r"^\**Q\s*[.:]", line))
            text = sanitize(re.sub(r"^- ", "", line))
            for sentence in _split_sentences(text):
                blocks += [{"type": "line", "text": t, "bold": bold} for t in wrap(sentence)]
        return blocks

    sentences = [wrap(s) for line in paragraph for s in _split_sentences(sanitize(line))]
    for i, group in enumerate(_chunks(sentences)):
        if i:
            blocks.append({"type": "blank"})  # 한 문단이 4줄을 넘을 때만 나눈다
        blocks += [{"type": "line", "text": t, "bold": False} for t in group]
    return blocks


def format_body(body, related=None):
    """본문을 블록 목록으로 바꾼다. related는 내부링크 후보 목록([링크:번호]의 번호 = 1부터)."""
    related = related or []
    blocks, paragraph = [], []

    def flush():
        if paragraph:
            blocks.extend(_paragraph_blocks(paragraph))
            blocks.append({"type": "blank"})
            paragraph.clear()

    # AI가 [사진:...], [링크:...] 표시를 문장 중간에 쓴 경우에도 따로 떼어 낸다
    raw_lines = []
    for raw in body.splitlines():
        parts = [x.strip() for x in MARKER_SPLIT.split(raw)]
        raw_lines += [x for x in parts if x] if len(parts) > 1 else [raw]

    for raw in raw_lines:
        line = raw.strip()
        photo, link = PHOTO_RE.match(line), LINK_RE.match(line)
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            blocks += [{"type": "blank"}, {"type": "blank"}]
            blocks.append({"type": "heading", "text": sanitize(line.lstrip("#"))})
            blocks.append({"type": "blank"})
        elif photo:
            flush()
            blocks += [{"type": "photo", "file": photo.group(1)}, {"type": "blank"}]
        elif link:
            # 링크 소개 문장과 링크는 붙여 둔다 (사이에 빈 줄 없음)
            if paragraph:
                blocks.extend(_paragraph_blocks(paragraph))
                paragraph.clear()
            number = int(link.group(1))
            if 1 <= number <= len(related):
                blocks.append({"type": "link", **related[number - 1]})
            blocks.append({"type": "blank"})
        else:
            paragraph.append(line)
    flush()
    return _tidy_blanks(_mark_phone_lines(_spread_photos(_tidy_blanks(blocks))))


def _last_content(blocks):
    return next((b["type"] for b in reversed(blocks) if b["type"] != "blank"), None)


def _spread_photos(blocks):
    """사진이 연달아 붙어 있거나(링크 카드와 붙은 것 포함) 한 소제목에 2장을 넘으면,
    그 뒤쪽에서 글 문단이 끝나는 자리로 옮긴다. 사진은 원래 자리보다 앞으로는 옮기지 않는다."""
    for pos, b in enumerate(blocks):
        b["_pos"] = pos  # 원래 순서 (앞쪽 엉뚱한 소제목으로 옮겨 가지 않게)
    pending = []

    def place(blocks, limit):
        out, count, here = [], 0, -1
        for i, b in enumerate(blocks):
            here = b.get("_pos", here)
            if b["type"] == "heading":
                count = 0
            if b["type"] == "photo":
                if _last_content(out) in ("photo", "link") or count >= limit:
                    pending.append(b)
                    continue
                count += 1
            out.append(b)
            # 글 문단이 끝난 자리(빈 줄)에, 원래 이 자리보다 앞에 있던 사진을 하나 넣는다
            nxt = next((n for n in blocks[i + 1:] if n["type"] != "blank"), None)
            ready = [p for p in pending if p["_pos"] <= here]
            if (b["type"] == "blank" and ready and count < limit and _last_content(out) == "line"
                    and (nxt is None or nxt["type"] not in ("photo", "link"))):
                pending.remove(ready[0])
                out += [ready[0], {"type": "blank"}]
                count += 1
        return out

    blocks = place(blocks, PHOTOS_PER_SECTION)
    if pending:  # 자리가 모자라면 소제목당 장수 제한만 풀고 한 번 더 (붙이지 않는 규칙은 그대로)
        blocks = place(blocks, 99)
    if pending and _last_content(blocks) == "line":  # 그래도 남으면 글 끝 문단 뒤에 한 장
        blocks += [{"type": "blank"}, pending.pop(0)]
    for b in blocks:
        b.pop("_pos", None)
    return blocks


def _mark_phone_lines(blocks):
    """전화번호가 들어 있는 줄은 굵게, 전화 링크 대상으로 표시한다."""
    digits = re.sub(r"\D", "", COMPANY_PHONE)
    for b in blocks:
        if b["type"] == "line" and digits and digits in re.sub(r"\D", "", b["text"]):
            b["bold"] = True
            b["phone"] = True
    return blocks


def _tidy_blanks(blocks):
    """빈 줄은 소제목 앞 2개, 그 외 1개까지만. 맨 앞, 맨 뒤 빈 줄은 없앤다."""
    result = []
    for i, block in enumerate(blocks):
        if block["type"] == "blank":
            run = 0  # 바로 앞에 이미 있는 빈 줄 개수
            for prev in reversed(result):
                if prev["type"] != "blank":
                    break
                run += 1
            nxt = next((b for b in blocks[i + 1:] if b["type"] != "blank"), None)
            allowed = 2 if nxt and nxt["type"] == "heading" else 1
            if not result or run >= allowed:
                continue
        result.append(block)
    while result and result[-1]["type"] == "blank":
        result.pop()
    return result


def opening(blocks):
    """글의 첫 문장 (다음 글이 같은 첫 문장으로 시작하지 않게 기록해 둔다)."""
    words = []
    for b in blocks:
        if b["type"] != "line":
            if words:
                break
            continue
        words.append(b["text"])
        if b["text"].endswith((".", "?", "!")):
            break
    return " ".join(words)


def preview(blocks, captions=None):
    """사람이 읽기 좋은 미리보기 글."""
    captions = captions or {}
    out = []
    for b in blocks:
        if b["type"] == "blank":
            out.append("")
        elif b["type"] == "heading":
            out.append(f"[소제목] {b['text']}")
        elif b["type"] == "photo":
            out.append(f"[사진: {b['file']} / 캡션: {captions.get(b['file'], '없음')}]")
        elif b["type"] == "link":
            out.append(f"[내부링크: {b['title']} {b['url']}]")
        else:
            out.append(f"[굵게] {b['text']}" if b["bold"] else b["text"])
    return "\n".join(out)
