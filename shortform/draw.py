"""계정 가이드대로 글자 그리기 (Pillow).

영상 위에 내내 고정으로 보이는 것(제목, 부제목, 설명자막, 하단자막)은 투명한
1080x1920 PNG 한 장으로 그려서 영상에 얹고, 썸네일은 영상 장면 위에 그려 PNG로 저장한다.
말자막처럼 시간에 따라 바뀌는 글자는 ASS 자막으로 따로 넣는다(styles 쪽).
"""
from __future__ import annotations

import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts
from .accounts import BOTTOM_Y, SPEAKER_Y, Account, Layout, Txt

W, H = 1080, 1920
MAX_W = 1000  # 한 줄 최대 너비

_missing: set[str] = set()


def _font(txt: Txt, size: int) -> ImageFont.FreeTypeFont:
    path, ok = fonts.find_or_fallback(txt.fonts)
    if not ok and txt.fonts[0] not in _missing:
        _missing.add(txt.fonts[0])
        print(f"  (글꼴 '{txt.fonts[1] if len(txt.fonts) > 1 else txt.fonts[0]}'이 없어서 "
              f"비슷한 굵은 글꼴로 대신 써요. fonts 폴더에 넣거나 설치하면 가이드와 똑같아져요)")
    return ImageFont.truetype(path, size)


def _segments(line: str) -> list[tuple[str, bool]]:
    """'사장님 {진상 직원}의' → [('사장님 ', False), ('진상 직원', True), ('의', False)]"""
    out = []
    for i, part in enumerate(re.split(r"[{}]", line)):
        if part:
            out.append((part, i % 2 == 1))
    return out


def _rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def render_line(line: str, txt: Txt, max_w: int = MAX_W) -> Image.Image:
    """글자 한 줄을 투명 배경 이미지로 그린다 (상자·알약·테두리·그림자·기울임 포함)."""
    segs = _segments(line) or [(" ", False)]
    size = txt.size
    while True:  # 너무 길면 글자를 줄여 한 줄에 맞춘다 (최소 60%)
        font = _font(txt, size)
        width = sum(font.getlength(s) for s, _ in segs)
        if width <= max_w - 2 * (txt.stroke + 20) or size <= txt.size * 0.6:
            break
        size = int(size * 0.94)
    ascent, descent = font.getmetrics()
    lh = ascent + descent
    padx, pady = (32 if txt.pill else 14 if (txt.box or txt.hl_box) else 0), (8 if txt.pill or txt.box else 0)
    m = txt.stroke + 24  # 테두리·그림자 여유
    img = Image.new("RGBA", (int(width) + 2 * (padx + m), lh + 2 * (pady + m)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = padx + m, pady + m

    # 글자 실제 세로 범위 (상자를 글자에 맞추기 위해)
    top, bottom = font.getbbox("가나다", anchor="ls")[1], font.getbbox("가나다", anchor="ls")[3]
    base = y0 + ascent
    if txt.pill:
        d.rounded_rectangle((m, base + top - pady - 6, img.width - m, base + bottom + pady + 6),
                            radius=(bottom - top) // 2 + pady + 6, fill=_rgba(txt.pill))
    if txt.box:
        d.rectangle((m, base + top - pady - 4, img.width - m, base + bottom + pady + 4),
                    fill=_rgba(txt.box))
    x = x0
    for s, hl in segs:
        w = font.getlength(s)
        if hl and txt.hl_box and txt.hl:
            d.rectangle((x - 6, base + top - 10, x + w + 6, base + bottom + 10), fill=_rgba(txt.hl))
        x += w
    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    x = x0
    for s, hl in segs:
        color = txt.hl if (hl and txt.hl and not txt.hl_box) else txt.color
        td.text((x, base), s, font=font, fill=_rgba(color), anchor="ls",
                stroke_width=txt.stroke, stroke_fill=_rgba(txt.stroke_color))
        x += font.getlength(s)
    if txt.shadow:
        alpha = text_layer.getchannel("A").filter(ImageFilter.GaussianBlur(7))
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow.putalpha(alpha.point(lambda a: int(a * 0.75)))
        img.alpha_composite(shadow, (6, 7))
    img.alpha_composite(text_layer)
    if txt.italic:  # 위쪽을 오른쪽으로 기울인다
        k = 0.18
        extra = int(k * img.height)
        wide = Image.new("RGBA", (img.width + extra, img.height), (0, 0, 0, 0))
        wide.paste(img, (0, 0))
        img = wide.transform(wide.size, Image.AFFINE, (1, k, -k * img.height, 0, 1, 0),
                             resample=Image.BICUBIC)
    return img.crop(img.getbbox() or (0, 0, 1, 1))


def _paper(block: Image.Image) -> Image.Image:
    """5번 계정: 모눈종이 같은 흰 상자 위에 글자."""
    pad_x, pad_y = 56, 34
    w, h = block.width + 2 * pad_x, block.height + 2 * pad_y
    paper = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    d = ImageDraw.Draw(paper)
    for gx in range(0, w, 16):
        d.line((gx, 0, gx, h), fill=(225, 225, 225, 255), width=1)
    for gy in range(0, h, 16):
        d.line((0, gy, w, gy), fill=(225, 225, 225, 255), width=1)
    d.rectangle((0, 0, w - 1, h - 1), outline=(200, 200, 200, 255), width=2)
    paper.alpha_composite(block, (pad_x, pad_y))
    return paper


def _stack(images: list[Image.Image], gap: int, align: str) -> Image.Image:
    w = max(i.width for i in images)
    h = sum(i.height for i in images) + gap * (len(images) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for im in images:
        x = 0 if align == "left" else (w - im.width) // 2
        out.alpha_composite(im, (x, y))
        y += im.height + gap
    return out


def title_block(lay: Layout, title: str, sub_title: str = "") -> Image.Image | None:
    """부제목/알약 + 제목 여러 줄을 하나의 묶음 이미지로."""
    lines = [ln.strip() for ln in title.split("\n") if ln.strip()][:3]
    parts: list[Image.Image] = []
    if sub_title.strip() and (lay.pill or lay.sub_title):
        parts.append(render_line(sub_title.strip(), lay.pill or lay.sub_title))
    if lines:
        t = lay.title
        if not any("{" in ln for ln in lines) and t.hl and len(lines) > 1 and not t.paper:
            lines[-1] = "{" + lines[-1] + "}"  # 강조 표시가 없으면 마지막 줄을 강조
        if t.paper:
            lines = [ln.replace("{", "").replace("}", "") for ln in lines]
        block = _stack([render_line(ln, t) for ln in lines], t.gap, lay.align)
        parts.append(_paper(block) if t.paper else block)
    if not parts:
        return None
    return _stack(parts, 18, lay.align)


def _place(canvas: Image.Image, img: Image.Image, lay: Layout) -> None:
    if lay.anchor == "center":
        y = lay.title_y - img.height // 2
    else:
        y = lay.title_y - img.height
    x = lay.x if lay.align == "left" else lay.x - img.width // 2
    x = max(0, min(x, W - img.width))
    canvas.alpha_composite(img, (x, max(0, y)))


def _center_line(canvas: Image.Image, text: str, txt: Txt, y: int) -> None:
    img = render_line(text, txt)
    canvas.alpha_composite(img, ((W - img.width) // 2, y - img.height // 2))


def overlay(acct: Account, *, title: str, sub_title: str = "", speaker: str = "",
            bottom: str = "", boxed: bool = True) -> Image.Image:
    """영상 위에 고정으로 얹을 글자들 (투명 PNG). boxed=True면 N-4(가운데 상자) 배치."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    block = title_block(acct.video, title, sub_title)
    if block:
        _place(canvas, block, acct.video)
    if speaker.strip():
        s = speaker.strip().strip("[]")
        _center_line(canvas, f"[{s}]", acct.speaker, SPEAKER_Y)
    if bottom.strip() and acct.bottom and boxed:
        b = bottom.strip().strip("<>")
        _center_line(canvas, f"<{b}>", acct.bottom, BOTTOM_Y)
    return canvas


def thumbnail(acct: Account, frame: Image.Image, *, title: str, sub_title: str = "") -> Image.Image:
    """영상 장면(1080x1920) 위에 계정 썸네일 디자인을 얹는다."""
    img = frame.convert("RGBA").resize((W, H))
    lay = acct.thumb
    if lay.shade == "bottom":  # 아래쪽을 점점 어둡게
        grad = Image.new("L", (1, H))
        for y in range(H):
            grad.putpixel((0, y), int(max(0, (y - H * 0.45) / (H * 0.55)) * 200))
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        shade.putalpha(grad.resize((W, H)))
        img.alpha_composite(shade)
    elif lay.shade == "dim":
        img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 150)))
    block = title_block(lay, title, sub_title)
    if block:
        _place(img, block, lay)
    return img.convert("RGB")
