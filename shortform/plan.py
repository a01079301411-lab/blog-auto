"""기획안 파일 읽기: txt / md / docx / hwp 에서 글자만 뽑는다.

롱폼 편집 때 Claude에게 기획안(콘텐츠 순서, 오프닝, 세부 기획)을 같이 보내
촬영본을 그 순서대로 고르고 배치하게 한다.
"""
from __future__ import annotations

import os
import re
import struct
import zipfile
import zlib
from html import unescape


def _docx(path: str) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    out = []
    # 문단(<w:p>)마다 한 줄, 표 칸(<w:tc>)은 ' | '로 잇는다
    for para in re.findall(r"<w:p[ >].*?</w:p>|<w:tc>|</w:tr>", xml, re.S):
        if para == "<w:tc>":
            out.append(" | ")
        elif para == "</w:tr>":
            out.append("\n")
        else:
            text = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", para))
            out.append(unescape(text) + "\n")
    text = "".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# HWP 본문 레코드 중 문단 글자(HWPTAG_PARA_TEXT)
_PARA_TEXT = 67
# 글자 사이에 끼어 있는 조판 부호: 이 번호들은 한 글자, 나머지(1~31)는 8글자 차지
_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _hwp_para(data: bytes) -> str:
    chars = struct.unpack(f"<{len(data) // 2}H", data[:len(data) // 2 * 2])
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c >= 32:
            out.append(chr(c))
            i += 1
        elif c in _CHAR_CTRL:
            if c in (10, 13):
                out.append("\n")
            elif c == 24:  # 하이픈
                out.append("-")
            elif c in (30, 31):  # 묶음 빈칸, 고정폭 빈칸
                out.append(" ")
            i += 1
        else:
            if c == 9:  # 탭
                out.append("\t")
            i += 8
    return "".join(out)


def _hwp(path: str) -> str:
    try:
        import olefile
    except ImportError as e:
        raise RuntimeError("한글(hwp) 기획안을 읽으려면 olefile 패키지가 필요해요. "
                           "update.bat을 한 번 실행하거나, 기획안을 txt/docx로 저장해 주세요.") from e
    with olefile.OleFileIO(path) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        compressed, encrypted = flags & 1, flags & 2
        if encrypted:
            raise RuntimeError("암호가 걸린 한글 파일은 읽을 수 없어요.")
        sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"),
                          key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
        paras = []
        for entry in sections:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                head = struct.unpack("<I", data[pos:pos + 4])[0]
                tag, size = head & 0x3FF, head >> 20
                pos += 4
                if size == 0xFFF:
                    size = struct.unpack("<I", data[pos:pos + 4])[0]
                    pos += 4
                if tag == _PARA_TEXT:
                    paras.append(_hwp_para(data[pos:pos + size]).strip())
                pos += size
        if not paras and ole.exists("PrvText"):  # 본문을 못 읽으면 미리보기 글자라도
            return ole.openstream("PrvText").read().decode("utf-16-le", errors="replace")
    return "\n".join(p for p in paras if p)


def read(path: str) -> str:
    """기획안 파일의 글자. 모르는 형식이면 그냥 텍스트로 읽어 본다."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return _docx(path)
    if ext == ".hwp":
        return _hwp(path)
    if ext in (".hwpx", ".pdf", ".doc"):
        raise RuntimeError(f"{ext} 기획안은 아직 못 읽어요. 한글이나 워드에서 "
                           "'다른 이름으로 저장'으로 hwp / docx / txt 파일로 저장해 주세요.")
    for enc in ("utf-8-sig", "cp949"):  # 메모장 저장 형식 둘 다
        try:
            with open(path, encoding=enc) as f:
                return f.read().strip()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().strip()
