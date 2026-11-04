"""양식 xlsx 분석: 전체 셀 덤프 + 채워야 할 칸(셀 맵) 자동 추출."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

LABEL_HEADER = re.compile(r"^(구분|번호|예시)$|무엇을 적나요")
EXAMPLE_HEADER = re.compile(r"^예시$")
FINAL_LABEL = re.compile(r"최종|그대로 쓸|다 보고")


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def pick_sheet(wb, sheet: str | None = None) -> Worksheet:
    if sheet and sheet in wb.sheetnames:
        return wb[sheet]
    return wb.worksheets[0]


def merged_anchor(ws: Worksheet, coord: str) -> str:
    """병합 범위 안의 셀이면 왼쪽 위(값을 쓸 수 있는) 셀 주소를 돌려준다."""
    for rng in ws.merged_cells.ranges:
        if coord in rng:
            return rng.start_cell.coordinate
    return coord


def _merge_of(ws: Worksheet, coord: str):
    for rng in ws.merged_cells.ranges:
        if coord in rng:
            return rng
    return None


def dropdowns(ws: Worksheet) -> list[dict]:
    out = []
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list" or not dv.formula1:
            continue
        f = dv.formula1.strip()
        if f.startswith('"'):
            options = [o.strip() for o in f.strip('"').split(",")]
        else:  # 범위 참조 (=Sheet!$A$1:$A$5)
            options = []
            ref = f.lstrip("=")
            sh, _, rng = ref.rpartition("!")
            tgt = ws.parent[sh.strip("'")] if sh else ws
            try:
                for row in tgt[rng.replace("$", "")]:
                    for c in (row if isinstance(row, tuple) else (row,)):
                        if c.value is not None:
                            options.append(str(c.value))
            except Exception:
                pass
        cells = []
        for rng in str(dv.sqref).split():
            c1, r1, c2, r2 = range_boundaries(rng)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    cells.append(f"{get_column_letter(c)}{r}")
        out.append({"sqref": str(dv.sqref), "options": options, "cells": cells})
    return out


@dataclass
class CellMap:
    sheet: str
    name_cell: str | None = None
    date_cell: str | None = None
    header_row: int | None = None
    headers: dict = field(default_factory=dict)        # 열 → 머리글(+설명행)
    label_cols: list = field(default_factory=list)
    example_col: str | None = None                      # 1-4처럼 '예시' 열이 있는 양식
    example_rows: list = field(default_factory=list)
    data_rows: list = field(default_factory=list)
    row_labels: dict = field(default_factory=dict)      # 행 → 행 라벨(구분/무엇을 적나요/번호)
    final_cells: list = field(default_factory=list)
    final_label: str = ""
    fillable: list = field(default_factory=list)        # 비어 있으면 안 되는 모든 칸(이름·작성일 포함)
    prefilled: dict = field(default_factory=dict)       # 양식에 이미 들어 있는 지정 값(건드리지 않음)
    dropdowns: list = field(default_factory=list)
    merged: list = field(default_factory=list)

    def example_rows_cells(self) -> set:
        """예시 행에 속한 칸(드롭다운 검사 제외용)."""
        out = set()
        for d in self.dropdowns:
            for c in d["cells"]:
                if int(re.sub(r"[A-Z]+", "", c)) in self.example_rows:
                    out.add(c)
        return out

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(path: str, sheet: str | None = None) -> CellMap:
    wb = openpyxl.load_workbook(path)
    ws = pick_sheet(wb, sheet)
    cm = CellMap(sheet=ws.title)
    cm.merged = sorted(str(r) for r in ws.merged_cells.ranges)
    cm.dropdowns = dropdowns(ws)

    # 1) 이름·작성일 칸: 라벨 오른쪽 첫 칸(병합이면 병합 끝 다음 칸)
    name_row = None
    for row in ws.iter_rows():
        for c in row:
            t = _txt(c.value)
            if t in ("이름", "작성일"):
                rng = _merge_of(ws, c.coordinate)
                nxt_col = (rng.max_col if rng else c.column) + 1
                target = f"{get_column_letter(nxt_col)}{c.row}"
                if t == "이름":
                    cm.name_cell, name_row = target, c.row
                else:
                    cm.date_cell = target

    # 2) 머리글 행: 이름 행 아래에서 값이 4개 이상인 첫 행
    start = (name_row or 1) + 1
    for r in range(start, ws.max_row + 1):
        vals = [c for c in ws[r] if _txt(c.value)]
        if len(vals) >= 4:
            cm.header_row = r
            break
    if cm.header_row is None:
        return cm
    h = cm.header_row
    header_cols = []
    for c in ws[h]:
        t = _txt(c.value)
        if t:
            header_cols.append(c.column)
            cm.headers[c.column_letter] = t
            if LABEL_HEADER.search(t) or c.column == 1:
                cm.label_cols.append(c.column_letter)
            if EXAMPLE_HEADER.search(t):
                cm.example_col = c.column_letter
    # 머리글 바로 아래 설명행(라벨 열이 비어 있고 내용 칸에 글이 있는 행)
    r = h + 1
    while r <= ws.max_row:
        labels = [_txt(ws[f"{L}{r}"].value) for L in cm.label_cols]
        others = [_txt(ws.cell(r, ci).value) for ci in header_cols if get_column_letter(ci) not in cm.label_cols]
        if not any(labels) and any(others) and not any(merged_anchor(ws, f"{L}{r}") != f"{L}{r}" for L in cm.label_cols[:1]):
            for ci in header_cols:
                t = _txt(ws.cell(r, ci).value)
                if t:
                    cm.headers[get_column_letter(ci)] += f" ({t})"
            r += 1
            continue
        break
    first_body = r
    content_cols = [ci for ci in header_cols if get_column_letter(ci) not in cm.label_cols]

    # 3) 본문 행: 예시행·최종행 분리
    final_rows: list[int] = []
    for r in range(first_body, ws.max_row + 1):
        a = _txt(ws[merged_anchor(ws, f"A{r}")].value)
        if FINAL_LABEL.search(a):
            final_rows.append(r)
            cm.final_label = a
            continue
        if _txt(ws[f"A{r}"].value) == "예":
            cm.example_rows.append(r)
            continue
        labels = [_txt(ws[merged_anchor(ws, f"{L}{r}")].value) for L in cm.label_cols if L != cm.example_col]
        if any(labels):
            cm.data_rows.append(r)
            lab = " / ".join(x for x in labels if x)
            if cm.example_col and _txt(ws[f"{cm.example_col}{r}"].value):
                lab += f" (예시: {_txt(ws[f'{cm.example_col}{r}'].value)})"
            cm.row_labels[r] = lab

    # 4) 채울 칸
    fill: list[str] = []
    for coord in (cm.name_cell, cm.date_cell):
        if coord:
            fill.append(coord)
    for r in cm.data_rows:
        for ci in content_cols:
            a = merged_anchor(ws, f"{get_column_letter(ci)}{r}")
            if a not in fill:
                fill.append(a)
    label_set = {column_index_from_string(L) for L in cm.label_cols}
    for r in final_rows:
        for c in ws[r]:
            if c.column in label_set or c.column > max(header_cols):
                continue
            a = merged_anchor(ws, c.coordinate)
            a_col = column_index_from_string(re.match(r"[A-Z]+", a).group())
            if a_col in label_set or a in fill:
                continue
            # 최종 라벨 병합(A~C) 안이면 제외
            rng = _merge_of(ws, c.coordinate)
            if rng and rng.min_col == 1:
                continue
            fill.append(a)
            cm.final_cells.append(a)
    cm.fillable = fill
    for coord in fill:
        v = ws[coord].value
        if v is not None and _txt(v):
            cm.prefilled[coord] = v
    return cm


def dump(path: str, sheet: str | None = None, limit: int = 400) -> str:
    """양식 전체를 사람이·AI가 읽을 수 있게 텍스트로 (모든 시트)."""
    wb = openpyxl.load_workbook(path)
    lines = [f"[파일] {path}", f"[시트] {wb.sheetnames}"]
    for ws in wb.worksheets:
        if sheet and ws.title != sheet and ws.title != pick_sheet(wb, sheet).title:
            pass
        lines.append(f"\n=== 시트 '{ws.title}' (행 {ws.max_row}, 열 {ws.max_column}) ===")
        n = 0
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and _txt(c.value):
                    lines.append(f"{c.coordinate}: {_txt(c.value)}")
                    n += 1
                    if n >= limit:
                        lines.append("... (생략)")
                        break
            if n >= limit:
                break
        if ws.merged_cells.ranges:
            lines.append("병합: " + ", ".join(sorted(str(r) for r in ws.merged_cells.ranges)))
        dd = dropdowns(ws)
        for d in dd:
            lines.append(f"드롭다운 {d['sqref']}: {d['options']}")
    return "\n".join(lines)


def describe(cm: CellMap) -> str:
    """셀 맵을 AI용 작업 지시 텍스트로."""
    out = [f"시트: {cm.sheet}", f"이름 칸: {cm.name_cell} / 작성일 칸: {cm.date_cell}"]
    out.append("열 머리글: " + "; ".join(f"{k}={v}" for k, v in cm.headers.items()))
    if cm.example_rows:
        out.append(f"예시 행(참고만, 수정 금지): {cm.example_rows}")
    out.append("데이터 행: " + "; ".join(f"{r}({cm.row_labels.get(r, '')})" for r in cm.data_rows))
    if cm.final_cells:
        out.append(f"최종 칸: {cm.final_cells} — 질문: {cm.final_label}")
    for d in cm.dropdowns:
        out.append(f"드롭다운 {d['sqref']} → 반드시 이 중 하나: {d['options']}")
    if cm.prefilled:
        out.append("양식에 이미 들어 있는 지정 값(그대로 둘 것): " + "; ".join(f"{k}={str(v)[:60]}" for k, v in cm.prefilled.items()))
    empties = [c for c in cm.fillable if c not in cm.prefilled]
    out.append(f"채워야 할 빈칸 {len(empties)}개: {', '.join(empties)}")
    return "\n".join(out)
