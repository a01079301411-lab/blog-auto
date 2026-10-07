"""AI가 쓴 본문을 사장님 블로그 규칙에 맞게 바꾼다.

- 한 줄은 공백 포함 22~28자, 어절(띄어쓰기) 단위로 끊는다. 단어 중간에서 자르지 않는다.
- 문장이 끝나면 새 줄에서 시작한다.
- 같은 내용(한 문단)은 3~4줄로 묶고, 내용이 바뀔 때(문단이 바뀔 때)만 한 줄 띄운다.
- 소제목 앞에는 빈 줄 2개.
- 특수문자는 모두 뺀다.

결과는 '블록' 목록이다. 발행 프로그램이 이 목록을 보고 한 줄씩 입력한다.
  {"type": "line", "text": "...", "bold": False}
  {"type": "heading", "text": "..."}
  {"type": "photo", "file": "창고_01.jpg"}
  {"type": "link", "title": "...", "url": "https://..."}
  {"type": "blank"}
"""
import re

LINE_MAX = 28
PARAGRAPH_MAX_LINES = 4
PHOTO_RE = re.compile(r"^\[사진:\s*([^\]]+?)\s*\]$")
LINK_RE = re.compile(r"^\[링크:\s*(\d+)\s*\]$")
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


def wrap(sentence):
    """한 문장을 28자 이하 줄로 나눈다. 마지막 줄이 너무 짧으면 앞줄과 균형을 맞춘다."""
    lines, cur = [], ""
    for word in sentence.split():
        candidate = f"{cur} {word}" if cur else word
        if len(candidate) <= LINE_MAX or not cur:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    while len(lines) >= 2 and len(lines[-1]) < 10:
        prev_words = lines[-2].split()
        moved = prev_words[-1]
        if len(prev_words) < 2 or len(lines[-2]) - len(moved) - 1 < 15:
            break
        lines[-2] = " ".join(prev_words[:-1])
        lines[-1] = f"{moved} {lines[-1]}"
    return lines


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

    for raw in body.splitlines():
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
    return _tidy_blanks(blocks)


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
