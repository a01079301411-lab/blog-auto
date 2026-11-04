"""셀 값 → 양식 xlsx 채우기 (줄바꿈·행 높이 자동)."""
from __future__ import annotations

import math
import re

import openpyxl
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter, column_index_from_string

from .template import pick_sheet, merged_anchor, _merge_of

WRAP = Alignment(wrap_text=True, vertical="center", horizontal="left")


def _width_chars(ws, coord: str) -> float:
    """셀(병합이면 병합 전체) 폭을 '한글 글자 수'로 대략 환산."""
    rng = _merge_of(ws, coord)
    col_letter = re.match(r"[A-Z]+", coord).group()
    cols = range(rng.min_col, rng.max_col + 1) if rng else [column_index_from_string(col_letter)]
    w = 0.0
    for ci in cols:
        cd = ws.column_dimensions.get(get_column_letter(ci))
        w += (cd.width if cd is not None and cd.width else 8.43)
    return max(4.0, w / 1.9)  # 한글 1자 ≈ 영문 1.9자 폭


def _lines(v, width: float) -> int:
    if v is None:
        return 1
    return sum(max(1, math.ceil(len(seg) / width)) for seg in str(v).split("\n"))


def fill(template: str, out: str, cells: dict[str, str], sheet: str | None = None,
         keep_prefilled: dict | None = None) -> list[str]:
    """cells: {"D12": "값"}. 병합 안쪽 주소는 왼쪽 위 칸으로 옮겨 씀. 경고 목록 반환."""
    wb = openpyxl.load_workbook(template)
    ws = pick_sheet(wb, sheet)
    warnings: list[str] = []
    rows_touched: set[int] = set()
    for coord, value in cells.items():
        coord = coord.strip().upper()
        if "!" in coord:  # '시트!B4' 형식
            sh, coord = coord.split("!", 1)
            target_ws = wb[sh.strip("'")] if sh.strip("'") in wb.sheetnames else ws
        else:
            target_ws = ws
        anchor = merged_anchor(target_ws, coord)
        if anchor != coord:
            warnings.append(f"{coord}는 병합 칸 안쪽이라 {anchor}에 썼습니다")
        if keep_prefilled and anchor in keep_prefilled and str(keep_prefilled[anchor]).strip() != str(value).strip():
            warnings.append(f"{anchor}는 양식 지정 값이라 바꾸지 않았습니다")
            continue
        c = target_ws[anchor]
        c.value = value
        c.alignment = WRAP
        if target_ws is ws:
            rows_touched.add(c.row)
    # 행 높이: 그 행에서 가장 줄 수가 많은 칸 기준
    for r in rows_touched:
        need = 1
        for c in ws[r]:
            if c.value is None or type(c).__name__ == "MergedCell":
                continue
            need = max(need, _lines(c.value, _width_chars(ws, c.coordinate)))
        h = min(409, max(ws.row_dimensions[r].height or 15, need * 15 + 8))
        ws.row_dimensions[r].height = h
    wb.save(out)
    return warnings


def read_cells(path: str, sheet: str | None = None) -> dict[str, str]:
    wb = openpyxl.load_workbook(path)
    ws = pick_sheet(wb, sheet)
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None}
