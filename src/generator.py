"""Anthropic API로 블로그 글을 만든다.

보내는 것: prompts/moving_post.md + data/company_facts.md + samples/sample_storage_post.md
          (매번 같은 부분이라 프롬프트 캐싱으로 비용을 줄인다)
          + 이번 주제 + 사진 목록 + 내부링크 후보 + 최근 글 목록
받는 것:   {"title", "body", "photo_captions", "tags", "used_facts"} JSON
"""
import json
import logging

import anthropic

import formatter
import history
import links
import photos
import season
from config import COMPANY_PHONE, DATA_DIR, MODEL, PROMPTS_DIR, SAMPLES_DIR

log = logging.getLogger(__name__)

# AI가 반드시 이 모양의 JSON으로만 답하게 한다
POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "photo_captions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"file": {"type": "string"}, "caption": {"type": "string"}},
                "required": ["file", "caption"],
                "additionalProperties": False,
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "used_facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "body", "photo_captions", "tags", "used_facts"],
    "additionalProperties": False,
}


def _read(path):
    return path.read_text(encoding="utf-8").replace("{{전화번호}}", COMPANY_PHONE)


def system_prompt():
    """매번 똑같은 부분. 글자가 하나도 안 바뀌어야 캐싱이 된다."""
    return (
        _read(PROMPTS_DIR / "moving_post.md")
        + "\n\n---\n\n# company_facts (회사 팩트 모음)\n\n"
        + _read(DATA_DIR / "company_facts.md")
        + "\n\n---\n\n# sample (기준 샘플 글)\n\n"
        + _read(SAMPLES_DIR / "sample_storage_post.md")
    )


def recent_posts_text(limit=10):
    """최근 글의 제목과 첫 문장. AI가 이것과 다르게 쓰도록 보여준다."""
    records = history.load()[-limit:]
    if not records:
        return "(아직 없음)"
    return "\n".join(f"- 제목: {r['title']} / 첫 문장: {r.get('opening', '')}" for r in reversed(records))


# 발행 전 검토에서 자주 걸린 것들. 프롬프트 파일을 사장님이 고쳐 써도 항상 지키게 여기에 둔다.
EXTRA_RULES = """추가 규칙 (꼭 지킨다)
- 제목에 'N가지'를 쓰면 소제목도 '## 1. ~'부터 '## N. ~'까지 번호를 붙여 정확히 N개로 쓴다. 각 소제목이 그 기준 하나다. 자주 묻는 질문, 마무리 소제목은 번호 없이.
- 한 소제목에는 그 소제목이 묻는 이야기만 쓴다. 다른 소제목이 맡은 이야기(예: 보관 환경 소제목 안의 포장 이야기)는 그 소제목으로 옮긴다.
- 사진은 사진 설명이 그 소제목 내용과 맞는 곳에만 넣는다. 가격 이야기 소제목에 정리 모습 사진처럼 상관없는 사진은 넣지 않는다.
- 다른 업체나 컨테이너와 가격을 비교할 때는 회사 팩트의 숫자로 근거를 든다. 숫자가 없으면 '어느 쪽이 싸다'고 단정하지 말고 판단 기준만 알려 준다.
- 다른 업체나 보관 방식을 단정적으로 깎아내리지 않는다. ('~할 수 있습니다'처럼 쓴다)
- 같은 숫자 사실(예: 제습기 24시간, 바닥 20cm)은 글 전체에서 2번까지만 쓴다. FAQ 답이 본문 문장을 되풀이하지 않는다.
"""


def request_text(topic, photo_set, related=None, feedback=None):
    """이번 글마다 달라지는 부분."""
    text = (
        "이번 글 정보\n"
        f"- topic: {topic['topic']}\n"
        f"- keyword: {topic['keyword']}\n"
        f"- 이 글이 답하는 단 하나의 질문: {topic['question']}\n"
        f"- title_type: {topic['title_type']}\n"
        f"- hook_type: {topic['hook_type']}\n"
        f"- variant: {topic['variant']}\n"
        f"- 회사 전화번호: {COMPANY_PHONE}\n"
        f"- 오늘: {season.describe()}\n\n"
        f"{EXTRA_RULES}\n"
        f"photos\n{photos.describe(photo_set)}\n\n"
        f"related_posts\n{links.describe(related)}\n\n"
        f"recent_posts (이 제목, 첫 문장과 다르게 쓴다)\n{recent_posts_text()}\n"
    )
    if feedback:
        text += (
            "\n지난번에 쓴 글이 품질 검사에서 아래 이유로 떨어졌다. "
            "이 문제를 모두 고쳐서 처음부터 다시 써라.\n"
            + "\n".join(f"- {f}" for f in feedback)
        )
    return text


def generate(topic, photo_set, related=None, feedback=None):
    client = anthropic.Anthropic(max_retries=3)  # .env의 ANTHROPIC_API_KEY 사용, 오류 시 3회 재시도
    # AI는 글을 쓰기 전에 생각도 하는데, 그 생각도 글자 수 한도에 포함된다.
    # 한도가 작으면 글이 중간에 끊기므로 넉넉히 주고, 오래 걸려도 끊기지 않게 스트리밍으로 받는다.
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": request_text(topic, photo_set, related, feedback)}],
        output_config={"format": {"type": "json_schema", "schema": POST_SCHEMA}},
    ) as stream:
        response = stream.get_final_message()
    usage = response.usage
    log.info(
        "AI 사용량: 입력 %s, 캐시 읽음 %s, 캐시 저장 %s, 출력 %s",
        usage.input_tokens, usage.cache_read_input_tokens,
        usage.cache_creation_input_tokens, usage.output_tokens,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("AI가 글쓰기를 거절했어요.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("글이 너무 길어서 중간에 끊겼어요.")

    text = next(b.text for b in response.content if b.type == "text")
    post = json.loads(text)
    post["title"] = formatter.sanitize(post["title"])
    # 제목의 쉼표, 마침표는 띄어쓰기로 바꾼다 (검색 결과 제목은 깔끔하게)
    post["title"] = " ".join(post["title"].replace(",", " ").replace(".", " ").split())
    post["photo_captions"] = {c["file"]: formatter.sanitize(c["caption"]) for c in post["photo_captions"]}
    post["tags"] = [t.replace(" ", "").lstrip("#") for t in post["tags"] if t.strip()]
    return post
