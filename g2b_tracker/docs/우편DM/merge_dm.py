"""편지 PDF + 제안서 PDF → 우편 DM 봉투용 PDF (python merge_dm.py, render_dm.js 다음에)."""
from pathlib import Path
from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).parent
PROPOSAL = PdfReader(HERE.parent / "소개서" / "로젠이사_기관이전_제안서.pdf")
for letter, kind in (("편지", "학교"), ("편지_기관", "기관"), ("편지_병원", "병원"), ("편지_도서관", "도서관")):
    for name, pages in (("간편_1장양면", PROPOSAL.pages[:1]), ("표준_편지+제안서4쪽", PROPOSAL.pages)):
        w = PdfWriter()
        w.append(PdfReader(HERE / f"{letter}.pdf"))
        for p in pages:
            w.add_page(p)
        w.write(HERE / f"우편DM_{kind}_{name}.pdf")
        print("만듦:", f"우편DM_{kind}_{name}.pdf")
