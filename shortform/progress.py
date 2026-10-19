"""진행률 알리기: 작업 프로그램이 '@@PROGRESS@@ 0.42 설명' 줄을 내보내면 프로그램 창이
막대와 %, 남은 시간으로 보여 준다. (명령어 창에서 실행할 때는 아무것도 하지 않는다)

전체 작업을 구간으로 나눠 쓴다: set_range(0.0, 0.4) 다음 report(0.5) → 전체의 20%.
"""
from __future__ import annotations

import os
import time

_base = (0.0, 1.0)   # set_range로 정한 구간
_range = (0.0, 1.0)  # 지금 보고하는 구간 (sub로 더 잘게 나눌 수 있다)
_last = 0.0


def set_range(start: float, end: float) -> None:
    global _base, _range
    _base = _range = (start, end)
    report(0.0)


def sub(index: int, count: int) -> None:
    """지금 구간을 count개로 나눠 index번째(0부터)를 보고 구간으로 (예: 촬영본 여러 개)."""
    global _range
    a, b = _base
    step = (b - a) / max(count, 1)
    _range = (a + step * index, a + step * (index + 1))


def report(frac: float, label: str = "") -> None:
    global _last
    if not os.environ.get("SHORTFORM_GUI"):
        return
    a, b = _range
    value = a + (b - a) * min(max(frac, 0.0), 1.0)
    now = time.time()
    if now - _last < 0.5 and frac < 1.0:  # 너무 자주 보내지 않는다
        return
    _last = now
    print(f"@@PROGRESS@@ {value:.4f} {label}".rstrip(), flush=True)
