# homework_kit — COSY 숙제 프로그램용 자료 묶음

- HOMEWORK_SPEC.md : 마스터 스펙. 프로그램(AI 프롬프트)에 그대로 붙여넣는 지식 베이스 (지시사항·퀘스트 규칙·수집 방법·검증 절차·진행 현황)
- quests.json : 퀘스트별 양식 셀 맵(이름/작성일 칸, 데이터 행, 칸 설명, 최종 칸) — 코드에서 읽어서 자동 채우기
- templates/ : COSY 원본 양식 xlsx
- submitted/ : 실제 제출본 xlsx + submitted_cells.json(셀 단위 원문, few-shot 예시용)
- scripts/ : 각 퀘스트를 채운 openpyxl 스크립트 (사용: python3 스크립트 원본양식.xlsx 결과.xlsx, 2-1 q1q2는 인자 4개: `2-1_q2_template.xlsx 2-1_q1_template.xlsx 결과_q2.xlsx 결과_q1.xlsx` 순서 — q1·q2 순서를 바꾸면 MergedCell 오류)
- docs/ : 글로우업리즈 회사·프로그램 정리, 2-2 퀘스트 가이드·업로드 키트, 무료 소스 즐겨찾기 파일

새 퀘스트 추가 순서: 가이드 스크린샷 → HOMEWORK_SPEC 4장에 규칙 추가 → quests.json에 셀 맵 추가 → 스크립트 작성 → 렌더 확인 → 제출
