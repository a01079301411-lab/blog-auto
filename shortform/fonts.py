"""글꼴 파일 찾기.

가이드의 글꼴(강한육군, 페이퍼로지 등)을 이름으로 찾는다. Windows 글꼴 폴더
(모든 사용자용·내 계정용)와 프로그램의 fonts 폴더를 뒤져서, 글꼴 파일 안에 적힌
이름(한글 이름, 영문 이름, PostScript 이름)과 비교한다. 설치하지 않고 fonts 폴더에
글꼴 파일만 넣어 둬도 된다.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(ROOT, "fonts")
CACHE = os.path.join(ROOT, ".font_index.json")
EXT = (".ttf", ".otf", ".ttc")

# 원하는 글꼴이 없을 때 쓸 굵은 한글 글꼴
FALLBACK = ["Malgun Gothic Bold", "malgunbd", "맑은 고딕 Bold", "Apple SD Gothic Neo Bold",
            "Noto Sans CJK KR Bold", "NanumGothicBold", "WenQuanYi Zen Hei"]

_WEIGHT = ["black", "heavy", "extrabold", "bold", "semibold", "medium", "regular", "light", "thin"]


def _dirs() -> list[str]:
    dirs = [LOCAL_DIR]
    if sys.platform == "win32":
        dirs.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs += ["/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return [d for d in dirs if os.path.isdir(d)]


def _norm(name: str) -> str:
    return re.sub(r"[\s\-_.()]+", "", name).lower()


def _names(path: str) -> list[str]:
    """글꼴 파일 안의 이름들 (가족 이름, 전체 이름, PostScript 이름, 한글 이름 포함)."""
    from fontTools.ttLib import TTFont

    names = {os.path.splitext(os.path.basename(path))[0]}
    try:
        f = TTFont(path, fontNumber=0, lazy=True)
        for rec in f["name"].names:
            if rec.nameID in (1, 2, 4, 6, 16, 17):
                try:
                    names.add(rec.toUnicode())
                except Exception:
                    pass
        f.close()
    except Exception:
        pass
    return sorted(n for n in names if n)


def _index() -> dict[str, list[str]]:
    files = []
    for d in _dirs():
        for root, _, fs in os.walk(d):
            files += [os.path.join(root, f) for f in fs if f.lower().endswith(EXT)]
    stamp = [len(files), max((os.path.getmtime(f) for f in files), default=0)]
    try:
        with open(CACHE, encoding="utf-8") as fp:
            data = json.load(fp)
        if data.get("stamp") == stamp:
            return data["fonts"]
    except (OSError, ValueError):
        pass
    fonts = {f: _names(f) for f in files}
    try:
        with open(CACHE, "w", encoding="utf-8") as fp:
            json.dump({"stamp": stamp, "fonts": fonts}, fp, ensure_ascii=False)
    except OSError:
        pass
    return fonts


_INDEX: dict[str, list[str]] | None = None


def find(candidates: list[str]) -> str | None:
    """후보 이름 중 처음으로 찾은 글꼴 파일 경로. 없으면 None."""
    global _INDEX
    if _INDEX is None:
        _INDEX = _index()
    keyed = [(path, [_norm(n) for n in names]) for path, names in _INDEX.items()]
    for cand in candidates:  # 1) 이름이 정확히 같은 것
        c = _norm(cand)
        for path, names in keyed:
            if c in names:
                return path
    for cand in candidates:  # 2) 이름에 포함된 것 중 가장 굵은 것
        c = _norm(cand)
        hits = [(path, names) for path, names in keyed if any(c in n for n in names)]
        if hits:
            def weight(item):
                joined = " ".join(item[1])
                return next((i for i, w in enumerate(_WEIGHT) if w in joined), len(_WEIGHT))
            return min(hits, key=weight)[0]
    return None


def find_or_fallback(candidates: list[str]) -> tuple[str, bool]:
    """(글꼴 경로, 원래 글꼴을 찾았는지)."""
    path = find(candidates)
    if path:
        return path, True
    path = find(FALLBACK)
    if not path:
        raise RuntimeError("한글 글꼴을 하나도 찾지 못했어요. fonts 폴더에 글꼴 파일을 넣어 주세요.")
    return path, False


def family(path: str) -> str:
    """ASS 자막에 적을 글꼴 가족 이름."""
    from fontTools.ttLib import TTFont

    try:
        f = TTFont(path, fontNumber=0, lazy=True)
        name = f["name"]
        for nid in (16, 1):
            rec = name.getName(nid, 3, 1, 0x409) or name.getName(nid, 3, 1)
            if rec:
                return rec.toUnicode()
    except Exception:
        pass
    return os.path.splitext(os.path.basename(path))[0]
