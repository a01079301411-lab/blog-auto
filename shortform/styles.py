"""세로 숏폼 디자인 템플릿.

화면 구성(영상 위치, 배경)과 글자(제목, 인물 소개, 말자막, 하단 문구)의
위치·크기·색을 한 곳에 모은다. 내장 프리셋을 쓰거나, 같은 항목을 가진
JSON 파일로 나만의 스타일을 만들 수 있다 (--style 내스타일.json).

좌표는 모두 1080x1920 화면 기준 픽셀이다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields, replace

from .subtitles import Cue

W, H = 1080, 1920


@dataclass
class Style:
    # 배경과 영상 상자
    background: str = "black"      # "black", "blur", 또는 "#202020" 같은 색
    video_top: int = 470           # 영상 상자 위쪽 y
    video_height: int = 1180       # 영상 상자 높이 (1920이면 화면 전체)
    video_fit: str = "fill"        # fill: 상자를 꽉 채우게 확대 후 잘라냄 / fit: 전체가 보이게

    # 글꼴 (Windows에 설치된 글꼴 이름)
    font: str = "Malgun Gothic"
    title_font: str = ""           # 비우면 font 사용

    # 제목 (영상 위). {중괄호} 친 부분이 강조색
    title_size: int = 104
    title_color: str = "#FFFFFF"
    title_highlight: str = "#FF3CF0"
    title_first_line_scale: float = 1.0  # 첫 줄을 작게 하려면 0.75 등
    title_bottom: int = 425        # 제목 마지막 줄의 아래쪽 y (위로 쌓임)
    title_top: int = 0             # 0이 아니면 이 y에서 아래로 쌓음 (영상 위에 얹을 때)
    title_outline: int = 0
    title_shadow: int = 0

    # 제목 위 알약 모양 문구 (예: "당신만 몰랐던..")
    label_enabled: bool = False
    label_size: int = 52
    label_color: str = "#FFFFFF"
    label_bg: str = "#7B2CBF"

    # 인물 소개 줄 (예: [권기준 / 꼴통사장])
    speaker_enabled: bool = True
    speaker_size: int = 56
    speaker_color: str = "#FFE600"
    speaker_format: str = "[{}]"

    # 말자막
    sub_size: int = 74
    sub_color: str = "#FFFFFF"
    sub_highlight: str = "#FFE600"
    sub_outline: int = 6
    sub_top: int = 1410            # 인물 소개 줄의 위쪽 y (말자막은 그 아래)

    # 하단 문구 (예: <나 같아도 열 받겠다>)
    bottom_enabled: bool = False
    bottom_size: int = 70
    bottom_color: str = "#2EE65A"
    bottom_format: str = "<{}>"
    bottom_y: int = 1760           # 하단 문구 가운데 y

    @property
    def video_bottom(self) -> int:
        return self.video_top + self.video_height


PRESETS: dict[str, Style] = {
    # 검은 배경, 흰 제목 + 분홍 강조, 영상 안에 노란 인물 소개 + 말자막
    "magenta": Style(),
    # 위와 같고 첫 줄이 작고 강조가 초록, 맨 아래 초록 반응 문구
    "green": Style(
        title_highlight="#2EE65A",
        title_first_line_scale=0.72,
        title_size=118,
        bottom_enabled=True,
    ),
    # 영상이 화면 전체, 그 위에 보라 알약 문구 + 테두리 두꺼운 제목
    "overlay": Style(
        video_top=0, video_height=H,
        title_top=300, title_size=120, title_highlight="#FFFFFF",
        title_outline=7, title_shadow=3,
        label_enabled=True, label_size=60,
        sub_top=1330,
    ),
    # 예전 기본값: 16:9 영상 전체가 보이고 위 제목 + 아래 자막
    "basic": Style(
        video_top=657, video_height=606, video_fit="fit",
        title_size=96, title_highlight="#FFE500", title_bottom=600,
        speaker_enabled=False, sub_top=1320,
    ),
}


def load_style(name_or_path: str, **overrides) -> Style:
    if name_or_path in PRESETS:
        style = PRESETS[name_or_path]
    elif os.path.exists(name_or_path):
        with open(name_or_path, encoding="utf-8") as f:
            data = json.load(f)
        base = PRESETS.get(data.pop("base", "magenta"), Style())
        known = {f.name for f in fields(Style)}
        unknown = set(data) - known
        if unknown:
            raise RuntimeError(f"스타일 파일에 모르는 항목이 있어요: {', '.join(sorted(unknown))}")
        style = replace(base, **data)
    else:
        raise RuntimeError(f"스타일 '{name_or_path}'을 찾을 수 없어요. "
                           f"사용 가능: {', '.join(PRESETS)} 또는 JSON 파일 경로")
    return replace(style, **{k: v for k, v in overrides.items() if v is not None})


def dump_style(style: Style) -> str:
    return json.dumps(asdict(style), ensure_ascii=False, indent=2)


# ---------- 영상 배치 (FFmpeg 필터) ----------

def video_filter(style: Style, focus: float = 0.5) -> str:
    """[v] 입력 → [vl] 출력. focus는 좌우로 잘라낼 때 남길 위치 (0=왼쪽, 1=오른쪽)."""
    bw, bh = W, style.video_height
    if style.video_fit == "fill":
        box = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
               f"crop={bw}:{bh}:(iw-{bw})*{focus:.3f}:(ih-{bh})/2")
    else:
        box = (f"scale={bw}:{bh}:force_original_aspect_ratio=decrease,"
               f"pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2")
    if bh >= H:
        return f"[v]{box},setsar=1[vl]"
    if style.background == "blur":
        return (f"[v]split[bg0][fg0];"
                f"[bg0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"boxblur=20:5,eq=brightness=-0.15[bg];"
                f"[fg0]{box}[fg];[bg][fg]overlay=0:{style.video_top},setsar=1[vl]")
    color = style.background.replace("#", "0x")
    return f"[v]{box},pad={W}:{H}:0:{style.video_top}:{color},setsar=1[vl]"


# ---------- 글자 (ASS 자막 파일) ----------

def _c(hex_color: str) -> str:
    """'#RRGGBB' → ASS 색 '&H00BBGGRR&'"""
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ts(t: float) -> str:
    cs = round(max(t, 0) * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")")


def _marked(text: str, color: str) -> str:
    """'{강조}' 표시를 색 태그로 바꾼다."""
    out = []
    for i, part in enumerate(re.split(r"[{}]", text)):
        if not part:
            continue
        out.append(f"{{\\c{_c(color)}}}{_esc(part)}{{\\r}}" if i % 2 else _esc(part))
    return "".join(out)


def _keywords(text: str, keywords: list[str], color: str) -> str:
    text = _esc(text)
    kws = sorted({_esc(k.strip()) for k in keywords if k.strip()}, key=len, reverse=True)
    if not kws:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in kws))
    return pattern.sub(lambda m: f"{{\\c{_c(color)}}}{m.group(0)}{{\\r}}", text)


def _title_text(style: Style, title: str) -> str:
    lines = [ln.strip() for ln in title.strip().split("\n") if ln.strip()][:3]
    if not any("{" in ln for ln in lines) and len(lines) > 1:
        lines[-1] = "{" + lines[-1] + "}"  # 강조 표시가 없으면 마지막 줄을 강조
    out = []
    for i, ln in enumerate(lines):
        text = _marked(ln, style.title_highlight)
        if i == 0 and len(lines) > 1 and style.title_first_line_scale != 1.0:
            size = round(style.title_size * style.title_first_line_scale)
            text = f"{{\\fs{size}}}" + text.replace("{\\r}", f"{{\\r\\fs{size}}}") + "{\\r}"
        out.append(text)
    return r"\N".join(out)


def write_ass(
    path: str,
    style: Style,
    cues: list[Cue],
    *,
    duration: float,
    title: str = "",
    label: str = "",
    speaker: str = "",
    bottom: str = "",
    keywords: list[str] | None = None,
) -> None:
    s = style
    tfont = s.title_font or s.font
    speaker_line = s.speaker_size + 22 if (s.speaker_enabled and speaker) else 0
    title_align, title_margin = ((8, s.title_top) if s.title_top else (2, H - s.title_bottom))
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
           "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")

    def st(name, font, size, color, outline, shadow, align, margin_v, border=1, back="#000000"):
        return (f"Style: {name},{font},{size},{_c(color)},&H000000FF&,{_c(back) if border == 3 else '&H00000000&'},"
                f"&H80000000&,-1,0,0,0,100,100,0,0,{border},{outline},{shadow},"
                f"{align},60,60,{margin_v},1")

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]", fmt,
        st("Title", tfont, s.title_size, s.title_color, s.title_outline, s.title_shadow,
           title_align, title_margin),
        # 알약: BorderStyle 3 = 글자 뒤에 색 상자
        st("Label", tfont, s.label_size, s.label_color, 14, 0, 2,
           H - s.title_top + 24, border=3, back=s.label_bg),
        st("Speaker", s.font, s.speaker_size, s.speaker_color, 4, 0, 8, s.sub_top),
        st("Sub", s.font, s.sub_size, s.sub_color, s.sub_outline, 0, 8, s.sub_top + speaker_line),
        st("Bottom", tfont, s.bottom_size, s.bottom_color, 0, 0, 5, 0),
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    whole = f"{_ts(0)},{_ts(duration)}"
    if title.strip():
        lines.append(f"Dialogue: 2,{whole},Title,,0,0,0,,{_title_text(s, title)}")
    if s.label_enabled and label.strip() and s.title_top:
        lines.append(f"Dialogue: 2,{whole},Label,,0,0,0,,{_esc(label.strip())}")
    if speaker_line:
        lines.append(f"Dialogue: 1,{whole},Speaker,,0,0,0,,"
                     f"{_esc(s.speaker_format.format(speaker.strip()))}")
    if s.bottom_enabled and bottom.strip():
        pos = f"{{\\pos({W // 2},{s.bottom_y})}}"
        lines.append(f"Dialogue: 1,{whole},Bottom,,0,0,0,,{pos}"
                     f"{_esc(s.bottom_format.format(bottom.strip()))}")
    for c in cues:
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Sub,,0,0,0,,"
                     + _keywords(c.text, keywords or [], s.sub_highlight))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
