"""LibreOffice로 xlsx → PDF → PNG 렌더 (잘림 확인용). Windows/맥/리눅스 공통."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CANDIDATES = [
    "soffice", "libreoffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def find_soffice() -> str | None:
    env = os.environ.get("SOFFICE")
    if env and Path(env).exists():
        return env
    for c in CANDIDATES:
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    return None


def to_pdf(xlsx: str, outdir: str) -> str | None:
    soffice = find_soffice()
    if not soffice:
        return None
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, xlsx],
                   check=False, capture_output=True, timeout=180)
    pdf = Path(outdir) / (Path(xlsx).stem + ".pdf")
    return str(pdf) if pdf.exists() else None


def to_png(pdf: str, outdir: str, dpi: int = 70, max_pages: int = 4) -> list[str]:
    stem = Path(outdir) / Path(pdf).stem
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-l", str(max_pages), pdf, str(stem)],
                       check=False, capture_output=True, timeout=120)
        return sorted(str(p) for p in Path(outdir).glob(Path(pdf).stem + "-*.png"))
    try:  # pdftoppm 없으면 PyMuPDF
        import fitz  # type: ignore
    except ImportError:
        return []
    out = []
    doc = fitz.open(pdf)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        p = f"{stem}-{i + 1}.png"
        page.get_pixmap(dpi=dpi).save(p)
        out.append(p)
    return out


def render(xlsx: str, outdir: str, dpi: int = 70) -> tuple[str | None, list[str], str]:
    """(pdf, png 목록, 안내문)."""
    Path(outdir).mkdir(parents=True, exist_ok=True)
    pdf = to_pdf(xlsx, outdir)
    if not pdf:
        return None, [], "LibreOffice(soffice)를 찾지 못해 렌더를 건너뜀 — 설치하거나 SOFFICE 환경변수에 경로 지정"
    pngs = to_png(pdf, outdir, dpi=dpi)
    note = "" if pngs else "PDF는 만들었지만 PNG 변환 도구(pdftoppm 또는 pip install pymupdf)가 없음"
    return pdf, pngs, note
