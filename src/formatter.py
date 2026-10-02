"""AI가 쓴 본문을 사장님 블로그 줄바꿈 규칙에 맞게 바꾼다.

- 한 줄은 공백 포함 22~28자, 어절(띄어쓰기) 단위로 끊는다. 단어 중간에서 자르지 않는다.
- 문장이 끝나면 새 줄에서 시작한다.
- 2~3줄 쓰고 한 줄 비운다.
- 소제목 앞에는 빈 줄 2개.

결과는 '블록' 목록이다. 발행 프로그램이 이 목록을 보고 한 줄씩 입력한다.
  {"type": "line", "text": "...", "bold": False}
  {"type": "heading", "text": "..."}
  {"type": "photo", "file": "창고_01.jpg"}
  {"type": "blank"}
"""
import re

LINE_MIN, LINE_MAX = 22, 28
PHOTO_RE = re.compile(r"^\[사진:\s*([^\]]+?)\s*\]$")
LIST_RE = re.compile(r"^(- |[A-Z]\. |Q\. |\*\*Q)")


def _clean(text):
    return text.replace("**", "").strip()


def wrap(sentence):
    """한 문장을 22~28자 줄로 나눈다."""
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
    # 마지막 줄이 너무 짧으면 앞줄 끝 단어를 내려서 균형을 맞춘다
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
    """문장(줄 묶음) 목록을 최대 3줄 묶음으로 모은다. 문장 중간에서는 절대 띄우지 않는다."""
    groups, cur = [], []
    for lines in sentences:
        if cur and len(cur) + len(lines) > 3:
            groups.append(cur)
            cur = []
        cur = cur + lines
    if cur:
        groups.append(cur)
    return groups


def _paragraph_blocks(paragraph):
    blocks = []
    is_list = any(LIST_RE.match(line) for line in paragraph)
    if is_list:
        # 목록·FAQ·보기(A/B/C)는 줄을 합치거나 사이를 띄우지 않는다
        for line in paragraph:
            bold = line.startswith("**") and line.endswith("**")
            for sentence in _split_sentences(_clean(line)):
                for part in wrap(sentence):
                    blocks.append({"type": "line", "text": part, "bold": bold})
        return blocks

    sentences = [wrap(s) for line in paragraph for s in _split_sentences(_clean(line))]
    for i, group in enumerate(_chunks(sentences)):
        if i:
            blocks.append({"type": "blank"})
        blocks += [{"type": "line", "text": t, "bold": False} for t in group]
    return blocks


def format_body(body):
    blocks, paragraph = [], []

    def flush():
        if paragraph:
            blocks.extend(_paragraph_blocks(paragraph))
            blocks.append({"type": "blank"})
            paragraph.clear()

    for raw in body.splitlines():
        line = raw.strip()
        photo = PHOTO_RE.match(line)
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            blocks += [{"type": "blank"}, {"type": "blank"}]
            blocks.append({"type": "heading", "text": _clean(line.lstrip("#"))})
            blocks.append({"type": "blank"})
        elif photo:
            flush()
            blocks += [{"type": "photo", "file": photo.group(1)}, {"type": "blank"}]
        else:
            paragraph.append(line)
    flush()
    return _tidy_blanks(blocks)


def _tidy_blanks(blocks):
    """빈 줄은 소제목 앞 2개, 그 외 1개까지만. 맨 앞·맨 뒤 빈 줄은 없앤다."""
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


def preview(blocks, captions=None):
    """사람이 읽기 좋은 미리보기 글."""
    captions = captions or {}
    out = []
    for b in blocks:
        if b["type"] == "blank":
            out.append("")
        elif b["type"] == "heading":
            out.append(f"■ {b['text']}")
        elif b["type"] == "photo":
            out.append(f"[사진: {b['file']} — {captions.get(b['file'], '캡션 없음')}]")
        else:
            out.append(f"**{b['text']}**" if b["bold"] else b["text"])
    return "\n".join(out)
