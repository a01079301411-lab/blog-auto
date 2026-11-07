"""자체 검증 (스펙 8장 6단계): 빈칸 0, 금지 표현 0, 드롭다운·이름·날짜·수치 형식."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

from .paths import forbidden_phrases, USER_NAME
from .template import CellMap, pick_sheet

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 1만 이상인데 '34,000'처럼 쓴 경우 → '3.4만' 규칙 위반
BIG_COMMA = re.compile(r"(?<![\d.,])(\d{2,3}(?:,\d{3})+)(?![\d,]|\s*원)")
# 칸을 '없음/모름'으로 때우는 것만 금지 (문장 속 '링크가 없음' 같은 근거 서술은 허용 — 제출본 기준)
PLACEHOLDER_WORDS = {"없음", "모름", "안됨", "안 됨", "부족함", "네가해", "해당없음", "해당 없음", "미정",
                     "모르겠음", "확인불가", "확인 불가", "n/a", "na", "-", "."}
PLACEHOLDER_ONLY = {"없음", "모름", "안됨", "부족함", "네가해"}


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    filled: int = 0
    total: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines = [f"검증 결과: {'통과' if self.ok else '실패'} — 채운 칸 {self.filled}/{self.total}"]
        lines += [f"[오류] {e}" for e in self.errors]
        lines += [f"[주의] {w}" for w in self.warnings]
        return "\n".join(lines)


REF_URL = re.compile(r"(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|youtube\.com|youtu\.be|tiktok\.com|threads\.(?:com|net)|blog\.naver\.com)/[^\s,)'\"]+")


def check(xlsx: str, cm: CellMap, fixed: dict | None = None, extra_forbidden: list | None = None,
          store=None) -> Report:
    wb = openpyxl.load_workbook(xlsx)
    ws = pick_sheet(wb, cm.sheet)
    rep = Report(total=len(cm.fillable))
    phrases = list(dict.fromkeys(forbidden_phrases() + (extra_forbidden or [])))

    for coord in cm.fillable:
        v = ws[coord].value
        t = "" if v is None else str(v).strip()
        if not t:
            rep.errors.append(f"{coord} 빈칸")
            continue
        rep.filled += 1
        core = re.sub(r"[\s.·,!?()\[\]'\"]+", " ", t).strip().lower()
        if core in PLACEHOLDER_WORDS or (len(core) <= 8 and any(w in core for w in PLACEHOLDER_ONLY)):
            rep.errors.append(f"{coord} 칸을 '{t}'(으)로 때움 — 실측·근거로 채울 것")
        for p in phrases:
            if p and p not in PLACEHOLDER_ONLY and p in t:
                rep.errors.append(f"{coord} 금지 표현 '{p}': {t[:40]}")
        if core.startswith("미확인") and len(core) < 12:
            rep.warnings.append(f"{coord} '미확인'만 적음 — 이유(웹 비공개 등)와 확인 방법을 같이 적을 것")
        for m in BIG_COMMA.finditer(t):
            n = int(m.group(1).replace(",", ""))
            if n >= 10_000:
                rep.warnings.append(f"{coord} '{m.group(1)}' → 1만 이상은 '만' 단위로 (예: 3.4만)")

    if cm.name_cell and str(ws[cm.name_cell].value or "").strip() != USER_NAME:
        rep.errors.append(f"{cm.name_cell} 이름은 '{USER_NAME}'이어야 함")
    if cm.date_cell and not DATE_RE.match(str(ws[cm.date_cell].value or "").strip()):
        rep.errors.append(f"{cm.date_cell} 작성일은 YYYY-MM-DD 형식")

    for d in cm.dropdowns:
        if not d["options"]:
            continue
        for coord in d["cells"]:
            v = ws[coord].value
            if v is None or coord in cm.example_rows_cells():
                continue
            if str(v).strip() not in d["options"]:
                rep.errors.append(f"{coord} 드롭다운 값 '{v}'은 목록 {d['options']}에 없음")

    for coord, want in {**cm.prefilled, **(fixed or {})}.items():
        got = ws[coord].value
        if str(got or "").strip() != str(want).strip():
            rep.errors.append(f"{coord} 지정 값이 바뀜: '{str(want)[:30]}' → '{str(got)[:30]}'")
    # 실측 근거: 데이터 행의 레퍼런스 링크는 모두 results.json(성민 PC 수집)에 있어야 함 — 추정 금지
    if store is not None:
        from openpyxl.utils import get_column_letter
        for r in cm.data_rows:
            for ci in range(1, ws.max_column + 1):
                v = ws.cell(r, ci).value
                for m in REF_URL.finditer(str(v or "")):
                    u = m.group(0).strip()
                    if not store.has(u):
                        store.need(u, f"{get_column_letter(ci)}{r} 레퍼런스 실측")
                        rep.errors.append(f"{get_column_letter(ci)}{r} 링크의 실측이 results.json에 없음 → PC 수집 필요: {u}")
                    else:
                        rep.filled_sources = getattr(rep, "filled_sources", 0) + 1
        old = store.stale()
        if old:
            rep.warnings.append(f"수집 후 3일 넘은 수치 {len(old)}건 — 재수집 권장 (예: {old[0]})")
    return rep
