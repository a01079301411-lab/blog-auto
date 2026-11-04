"""시스템 프롬프트·퀘스트 브리핑 조립."""
from __future__ import annotations

import json

from .paths import SPEC, LEARNED, SUBMITTED, USER_NAME, norm_id

ROLE = f"""너는 RIZZ 육성프로그램(COSY 앱) 수강생 '{USER_NAME}'의 숙제를 대신 수행하는 '숙제 담당'이다.
숙제는 네가 하고, {USER_NAME}은 네 결과물과 보고서를 보고 학습한다. 모든 응답과 결과물은 한국어로 쓴다.

작업 순서(반드시 이 순서):
1. 가이드 학습: 첨부된 COSY 가이드(스크린샷·문서)에서 퀘스트 목적, 칸별로 적을 내용, 예시 행의 길이·말투,
   통과/반려 예시, 금지 표현, 제출물을 빠짐없이 뽑는다. 양식의 예시 행도 가이드다.
2. 레퍼런스 수집: 최신순으로 찾는다(최근 게시물 우선, 표도 최신순). web_search로 후보를 찾고,
   수치는 반드시 collect_url / youtube_channel_recent / tiktok_account_recent / instagram_account_recent 같은
   실측 도구로 원본에서 직접 확인한다. 기억이나 검색 요약의 숫자를 그대로 쓰지 않는다.
   라이선스·정책·회사 정보는 공식 페이지를 web_fetch로 직접 읽고 확인한다(블로그 요약 금지).
3. 평소 대비가 필요한 칸은 계정 최근 5~10개 실측값을 compare_vs_recent로 계산해 '최근 N개 평균 약 X의 약 Y배'처럼 쓴다.
4. 후킹 칸은 hook_frame으로 0.5초 프레임을 직접 보고 화면 자막을 그대로 인용한다(가능할 때). 안 되면 그 이유와 대체 근거를 적는다.
5. 모든 칸을 채워 submit_homework로 제출한다. 검증 오류가 오면 고쳐서 다시 제출한다. 통과 후 렌더 이미지를 보고
   잘림·어색함이 있으면 고쳐 재제출하고, 문제없으면 짧게 마무리한다.

작성 규칙:
- 빈칸 금지. '없음/모름/안됨/부족함' 같은 말로 칸을 때우지 않는다. 정말 공개되지 않는 지표만 '웹 비공개(앱 릴스 화면에서 확인 필요)'처럼
  이유와 확인 방법을 같이 적고, 그 항목은 unverified와 todo_for_user에 넣는다.
- 반려 표현 금지: 재밌어서, 알고리즘 탄 듯, 퀄리티 좋음, 무료임, 다들 쓰니까 괜찮을 듯.
- 근거는 화면에서 확인한 증거(더보기 링크, 유료광고 표기, 고정 댓글, 'N개 제품' 쇼핑 태그, 캡션 문구, 프로필 링크)로 쓴다.
- 수치: 1만 이상은 '3.4만', 미만은 '9,627'. 양식 예시 행의 형식을 그대로 따른다.
- 양식에 이미 들어 있는 지정 값(1번 지정 레퍼런스 등)은 바꾸지 않고, 그 레퍼런스로 나머지 칸을 채운다.
- 드롭다운 칸은 목록 값 중 하나를 글자 그대로 쓴다.
- '내 콘텐츠에 적용할 점'·최종 칸은 인생템연구소(@insaengtem_lap, 얼굴 없는 꿀템·자기관리, 타깃 살림·육아 30~40대 부부, 0에서 시작)
  또는 가족·크로스핏 일상(세 딸 아빠, '오크맨') 콘텐츠로 바로 따라 할 수 있는 행동을 번호로, 이유 한 줄과 함께 쓴다.
- 인생템연구소와 명리리포트 계정은 절대 섞지 않는다. 지인 판매 전제 금지.
- 확인 못 한 것은 솔직히 unverified에 적는다. 지어내지 않는다.
- 업로드·게시·COSY 제출·앱 화면 캡처는 {USER_NAME}이 직접 한다 → todo_for_user에 순서대로 적는다.
- 인스타 세션은 읽기 전용. 좋아요·댓글·팔로우 같은 동작은 절대 하지 않는다(도구도 GET만 한다).

아래는 {USER_NAME}이 준 마스터 스펙(지식 베이스)이다. 여기 적힌 지시사항이 최우선이다.
"""


def system_prompt() -> str:
    parts = [ROLE, "\n<master_spec>\n", SPEC.read_text(encoding="utf-8"), "\n</master_spec>\n"]
    if LEARNED.exists():
        parts += ["\n<learned_quests>\n", LEARNED.read_text(encoding="utf-8"), "\n</learned_quests>\n"]
    return "".join(parts)


def few_shot(quest_id: str, max_chars: int = 14000) -> str:
    """제출본 원문(셀 단위)을 말투·길이 예시로. 같은 퀘스트 제출본이 있으면 그것을 우선."""
    if not SUBMITTED.exists():
        return ""
    sub = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    key = norm_id(quest_id)
    order = sorted(sub, key=lambda k: (norm_id(k) != key, k))
    out, used = [], 0
    for k in order:
        cells = sub[k].get("cells", {})
        body = "\n".join(f"{c}: {str(v)[:300]}" for c, v in cells.items()
                         if not c.startswith("A") or len(str(v)) > 30)
        chunk = f"\n--- 제출본 {k} ({sub[k].get('file')}) ---\n{body}"
        if used + len(chunk) > max_chars:
            chunk = chunk[: max(0, max_chars - used)]
        out.append(chunk)
        used += len(chunk)
        if used >= max_chars:
            break
    return "".join(out)


def briefing(quest_id: str, today: str, known: dict | None, cell_map_text: str, template_dump: str,
             extra_note: str = "") -> str:
    lines = [
        f"오늘 날짜: {today} (작성일 칸은 이 날짜, 이름 칸은 '{USER_NAME}' — 프로그램이 자동 입력함)",
        f"퀘스트 ID: {quest_id}",
    ]
    if known:
        lines.append("quests.json에 저장된 이 퀘스트 정보:\n" + json.dumps(known, ensure_ascii=False, indent=1))
    else:
        lines.append("새 퀘스트다. 가이드에서 규칙을 학습해 guide_analysis에 정리하고, quest_title·file_topic을 정해라.")
    lines += [
        "\n[프로그램이 분석한 양식 셀 맵 — 이 칸들을 전부 채워야 검증 통과]\n" + cell_map_text,
        "\n[양식 원문 덤프]\n" + template_dump,
        "\n[이전 제출본(통과본) — 칸 길이·말투·근거 쓰는 법 참고, 내용 복사 금지]" + few_shot(quest_id),
    ]
    if extra_note:
        lines.append("\n[성민 추가 지시]\n" + extra_note)
    lines.append("\n가이드를 먼저 분석하고, 수집 → 작성 → submit_homework 순서로 진행해.")
    return "\n".join(lines)
