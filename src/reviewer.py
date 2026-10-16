"""AI 편집장 검토: 규칙 검사(checker)로는 못 잡는 문제를 사람 편집자처럼 한 번 더 본다.

- 제목이 약속한 것(예: 기준 4가지)을 본문이 그대로 지키는지
- 사진 설명이 그 사진이 들어간 소제목 내용과 맞는지
- 한 소제목 안에 다른 소제목 이야기가 섞였는지
- 근거 없는 비교·단정, 다른 업체를 깎아내리는 말
- 지금 계절과 안 맞는 말, 같은 말 반복

꼭 고쳐야 하는 문제(must_fix)가 있으면 그 내용을 넣어 글을 다시 쓰게 한다.
"""
import json
import logging

import anthropic

import season
from config import DATA_DIR, MODEL

log = logging.getLogger(__name__)

KINDS = ["제목 약속", "사진 위치", "주제 섞임", "근거 없는 주장", "단정·비방", "계절", "반복", "기타"]

SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": KINDS},
                    "where": {"type": "string", "description": "문제가 있는 소제목이나 문장 (짧게 인용)"},
                    "problem": {"type": "string"},
                    "fix": {"type": "string", "description": "어떻게 고치면 되는지 구체적으로"},
                    "must_fix": {"type": "boolean"},
                },
                "required": ["kind", "where", "problem", "fix", "must_fix"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

SYSTEM = """\
너는 이사 회사 사장님의 네이버 블로그 글을 발행 전에 검토하는 꼼꼼한 편집장이다.
글은 대구의 이사 회사 사장이 직접 쓴 목소리이고, 목표는 읽은 사람이 전화로 견적을 문의하게 하는 것이다.

아래 기준으로만 본다. 문체 취향, 사소한 표현은 지적하지 않는다.
1. 제목 약속: 제목이 약속한 것(예: '기준 4가지', '비용 계산법')을 본문이 그대로 지키는가.
   'N가지'면 번호 붙은 소제목이 정확히 N개이고 각각이 그 기준인가.
2. 사진 위치: [사진: 파일] 표시가 들어간 소제목의 내용과 그 사진의 설명(캡션)이 맞는가.
   예: 가격 이야기 소제목에 '옷장 정리 모습' 사진이면 문제. 어디로 옮기면 맞는지 알려 준다.
3. 주제 섞임: 한 소제목 안에 다른 소제목이 맡은 이야기가 섞였는가. (예: 보관 환경 소제목 안의 포장 이야기)
4. 근거 없는 주장: 다른 업체·컨테이너와 가격이나 품질을 비교하면서 숫자나 사실 근거가 없는 문장,
   회사 팩트에 없는 숫자나 사례를 지어낸 문장.
   회사 팩트 모음에 있는 숫자(운영 11년, 예약 45일 전과 30일 전, 하루 7,000원 등)는 근거 있는 사실이다.
   이런 숫자는 근거 없는 주장으로 지적하지 않는다.
5. 단정·비방: 다른 업체나 보관 방식을 단정적으로 깎아내리는 표현 (예: '컨테이너는 무조건 상한다').
   '~할 수 있다'처럼 부드럽게 바꾸게 한다.
6. 계절: 오늘 날짜와 계절에 맞지 않는 말 (태그, 댓글 보기 포함).
7. 반복: 같은 사실이나 같은 뜻의 문장이 세 번 이상 되풀이됨.
8. 숫자 부족: 회사 팩트 숫자로 바꿀 수 있는데 추상적으로 쓴 문장 (예: 경험이 많습니다 → 5,200벌, 빨리 끝납니다 → 10분에서 15분).
   어느 팩트 숫자로 바꾸면 되는지 fix에 적는다. must_fix는 false. 종류는 '기타'로 한다.

must_fix는 독자가 실망하거나(제목 약속 불이행), 사실이 틀릴 수 있거나(근거 없는 주장),
글이 어색하게 보이는(계절, 사진 위치가 엉뚱함) 문제만 true로 한다. 다듬으면 좋은 정도는 false.
문제가 없으면 issues를 빈 목록으로 돌려준다. 최대 8개, 중요한 것부터. 모두 한국어로 쓴다."""


def _photo_text(post):
    captions = post.get("photo_captions") or {}
    if not captions:
        return "(사진 없음)"
    return "\n".join(f"- {name}: {cap}" for name, cap in captions.items())


def review(post, topic, client=None):
    """검토 결과 목록. 검토를 못 하면(인터넷, API 오류) 빈 목록."""
    content = (
        f"오늘: {season.describe()}\n\n"
        f"회사 팩트 모음 (여기 있는 사실은 근거가 있다)\n{(DATA_DIR / 'company_facts.md').read_text(encoding='utf-8')}\n\n"
        f"주제: {topic['topic']} / 메인 키워드: {topic['keyword']}\n"
        f"이 글이 답하는 질문: {topic['question']}\n"
        f"제목 유형: {topic.get('title_type', '')}\n\n"
        f"사진 설명\n{_photo_text(post)}\n\n"
        f"태그: {' '.join('#' + t for t in post.get('tags', []))}\n\n"
        f"제목: {post['title']}\n\n본문 (##은 소제목, [사진: 파일]은 사진 자리, [링크: 번호]는 내부링크)\n"
        f"{post['body']}"
    )
    try:
        client = client or anthropic.Anthropic(max_retries=2)
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "end_turn":
            log.info("AI 검토를 건너뜁니다 (%s)", response.stop_reason)
            return []
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)["issues"]
    except Exception as e:  # 검토가 안 돼도 글쓰기는 계속
        log.warning("AI 검토를 못 했어요: %s", e)
        return []


def as_feedback(issues):
    """다시 쓰기 지시로 바꾼 문장 목록."""
    return [f"[{i['kind']}] {i['where']} → {i['problem']} 고치는 법: {i['fix']}" for i in issues]
