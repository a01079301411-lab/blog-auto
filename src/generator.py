"""Anthropic API로 블로그 글을 만든다.

보내는 것: prompts/moving_post.md + data/company_facts.md + samples/sample_storage_post.md
          (매번 같은 부분이라 프롬프트 캐싱으로 비용을 줄인다)
          + 이번 주제 + 사진 목록
받는 것:   {"title", "body", "photo_captions", "tags", "used_facts"} JSON
"""
import json
import logging

import anthropic

import photos
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


def request_text(topic, photo_set, feedback=None):
    """이번 글마다 달라지는 부분."""
    text = (
        "이번 글 정보\n"
        f"- topic: {topic['topic']}\n"
        f"- keyword: {topic['keyword']}\n"
        f"- 이 글이 답하는 단 하나의 질문: {topic['question']}\n"
        f"- title_type: {topic['title_type']}\n"
        f"- variant: {topic['variant']}\n"
        f"- 회사 전화번호: {COMPANY_PHONE}\n\n"
        f"photos\n{photos.describe(photo_set)}\n"
    )
    if feedback:
        text += (
            "\n지난번에 쓴 글이 품질 검사에서 아래 이유로 떨어졌다. "
            "이 문제를 모두 고쳐서 처음부터 다시 써라.\n"
            + "\n".join(f"- {f}" for f in feedback)
        )
    return text


def generate(topic, photo_set, feedback=None):
    client = anthropic.Anthropic(max_retries=3)  # .env의 ANTHROPIC_API_KEY 사용, 오류 시 3회 재시도
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": request_text(topic, photo_set, feedback)}],
        output_config={"format": {"type": "json_schema", "schema": POST_SCHEMA}},
    )
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
    post["photo_captions"] = {c["file"]: c["caption"] for c in post["photo_captions"]}
    post["tags"] = [t.replace(" ", "").lstrip("#") for t in post["tags"] if t.strip()]
    return post
