"""렌더링 전에 하이라이트 목록을 메모장으로 보여주고 고르게 한다.

clips.txt에 숏폼 목록을 쓰고 메모장을 연다. 사용자가 [O]/[X]로 고르고 제목·문구·구간을
고쳐 저장하고 닫으면, 그 내용을 읽어 고른 숏폼만 돌려준다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from .highlights import Highlight

HEADER = """\
# ───────────────────────────────────────────────
#  만들 숏폼을 골라 주세요
# ───────────────────────────────────────────────
#  - 맨 앞의 [O]를 [X]로 바꾸면 그 숏폼은 만들지 않아요.
#  - 제목, 알약, 하단 문구, 구간을 직접 고칠 수 있어요.
#    제목 줄바꿈은 /, 강조할 단어는 {중괄호}로 감싸요.
#  - 다 고쳤으면 저장(Ctrl+S)하고 메모장을 닫으세요. 닫으면 바로 만들기 시작해요.
# ───────────────────────────────────────────────
"""


def _hms(t: float) -> str:
    t = round(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def _sec(text: str) -> float:
    total = 0.0
    for part in text.strip().split(":"):
        total = total * 60 + float(part)
    return total


def write(path: str, highlights: list[Highlight]) -> None:
    from .accounts import ACCOUNTS

    blocks = [HEADER]
    for i, h in enumerate(highlights, 1):
        acct = ACCOUNTS.get(h.account)
        where = f"   → {acct.no}번 {acct.name}" if acct else ""
        blocks.append(
            f"[O] {i:02}   점수 {h.score}/10{where}\n"
            f"구간: {_hms(h.start)} ~ {_hms(h.end)}   ({h.end - h.start:.0f}초)\n"
            f"제목: {h.title.replace(chr(10), ' / ')}\n"
            f"부제목: {h.sub_title}\n"
            f"알약: {h.label}\n"
            f"하단: {h.bottom}\n"
            f"이유: {h.reason}\n")
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:  # 메모장 호환
        f.write("\n".join(blocks))


def read(path: str, highlights: list[Highlight]) -> list[Highlight]:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    chosen = []
    for block in re.split(r"\n(?=\s*\[[OoXx○×]\])", text):
        m = re.match(r"\s*\[([OoXx○×])\]\s*(\d+)", block)
        if not m:
            continue
        idx = int(m.group(2)) - 1
        if not 0 <= idx < len(highlights) or m.group(1) in "Xx×":
            continue
        h = highlights[idx]
        fields = dict(re.findall(r"^(구간|제목|부제목|알약|하단):[ \t]*(.*)$", block, re.M))
        if "제목" in fields:
            h.title = "\n".join(p.strip() for p in fields["제목"].split("/") if p.strip())
        if "부제목" in fields:
            h.sub_title = fields["부제목"].strip()
        if "알약" in fields:
            h.label = fields["알약"].strip()
        if "하단" in fields:
            h.bottom = fields["하단"].strip()
        r = re.match(r"\s*([\d:.]+)\s*~\s*([\d:.]+)", fields.get("구간", ""))
        if r:
            try:
                start, end = _sec(r.group(1)), _sec(r.group(2))
                if end > start:
                    h.start, h.end = start, end
            except ValueError:
                print(f"  {idx + 1}번 구간을 읽지 못해 원래 구간을 써요: {fields['구간']}")
        chosen.append(h)
    return chosen


def review(path: str, highlights: list[Highlight]) -> list[Highlight]:
    """목록 파일을 열어 사용자가 고르게 하고, 고른 하이라이트를 돌려준다."""
    write(path, highlights)
    if os.environ.get("SHORTFORM_GUI"):
        # 프로그램 창이 이 줄을 보고 고르기 화면을 띄운다. 다 고르면 .done 파일을 만든다
        done = path + ".done"
        if os.path.exists(done):
            os.remove(done)
        print("\n[숏폼 고르기] 창에서 만들 숏폼을 골라 주세요.")
        print(f"@@REVIEW@@ {path}", flush=True)
        while not os.path.exists(done):
            time.sleep(0.3)
        os.remove(done)
    elif sys.platform == "win32":
        print(f"\n[숏폼 고르기] 메모장에서 만들 숏폼을 고르고, 저장한 뒤 메모장을 닫아 주세요.")
        print(f"  목록 파일: {path}")
        subprocess.run(["notepad.exe", path])  # 메모장을 닫을 때까지 기다린다
    else:
        print(f"\n[숏폼 고르기] 목록 파일을 고친 뒤 Enter를 누르세요: {path}")
        input()
    chosen = read(path, highlights)
    print(f"  {len(chosen)}개를 만들어요.")
    return chosen
