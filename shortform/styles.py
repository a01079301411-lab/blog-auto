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
    sub_bottom: int = 1480         # 말자막 아래쪽 y: 숏폼 데드존(설명·좋아요 버튼) 바로 위
    sub_top: int = 0               # 예전 설정 (지금은 안 씀)

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
    ),
    # 예전 기본값: 16:9 영상 전체가 보이고 위 제목 + 아래 자막
    "basic": Style(
        video_top=657, video_height=606, video_fit="fit",
        title_size=96, title_highlight="#FFE500", title_bottom=600,
        speaker_enabled=False,
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

def _piecewise(points: list[tuple[float, float]], var: str = "t") -> str:
    """(시간, 값) 점들을 잇는 꺾은선을 FFmpeg 수식으로 만든다 (중첩 없이 구간별 합)."""
    if len(points) == 1:
        return f"{points[0][1]:.4f}"
    terms = [f"lt({var},{points[0][0]:.3f})*{points[0][1]:.4f}"]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t1 <= t0:
            continue
        slope = (v1 - v0) / (t1 - t0)
        terms.append(f"gte({var},{t0:.3f})*lt({var},{t1:.3f})*({v0:.4f}+{slope:.5f}*({var}-{t0:.3f}))")
    terms.append(f"gte({var},{points[-1][0]:.3f})*{points[-1][1]:.4f}")
    return "+".join(terms)


def _simplify(points: list[tuple[float, float]], tol: float = 0.004) -> list[tuple[float, float]]:
    """거의 일직선인 중간 점은 빼서 수식을 짧게 한다."""
    if len(points) <= 2:
        return points
    out = [points[0]]
    for prev, cur, nxt in zip(points, points[1:], points[2:]):
        (t0, v0), (t1, v1), (t2, v2) = out[-1], cur, nxt
        expect = v0 + (v2 - v0) * (t1 - t0) / (t2 - t0) if t2 > t0 else v1
        if abs(v1 - expect) > tol:
            out.append(cur)
    out.append(points[-1])
    return out


def view_ratio(style: Style, w: int, h: int) -> float:
    """원본 가로 중 숏폼 화면(꽉 채우기)에 보이는 비율."""
    if not w or not h or style.video_fit != "fill":
        return 1.0
    bw, bh = W, style.video_height
    scale = max(bw / w, bh / h)
    return min(1.0, bw / (w * scale))


def video_filter(
    style: Style,
    focus: float = 0.5,
    *,
    path: list[tuple[float, float]] | None = None,
    span: float | None = None,
    aspect: float = 16 / 9,
    keep_bottom: float | None = None,
) -> str:
    """[v] 입력 → [vl] 출력.

    focus: 좌우로 잘라낼 때 남길 위치 (0=왼쪽, 1=오른쪽).
    path: (숏폼 시간, 화면 가운데 x 비율) 목록. 있으면 화면이 얼굴을 따라간다.
    span: 원본 가로 중 보여줄 비율. 원본 자막이 다 보이도록 화면을 넓게 잡을 때 쓴다.
      (그만큼 영상이 작아지고 남는 위아래는 검은색)
    aspect: 원본 가로/세로 비율. keep_bottom: 위아래를 자를 때 이 높이(비율)까지는 남긴다.
    """
    bw, bh = W, style.video_height
    if style.video_fit == "fill":
        if path:
            c = _piecewise(_simplify(path))
            x = f"'clip(({c})*iw-ow/2,0,iw-ow)'"
        elif span:
            x = f"'clip({focus:.4f}*iw-ow/2,0,iw-ow)'"
        else:
            x = f"(iw-{bw})*{focus:.3f}"
        sw = round(bw / span / 2) * 2 if span else 0
        sh = round(sw / aspect / 2) * 2 if span else 0
        if span and sh < bh:  # 넓게 보여주기: 가로를 맞추고 위아래는 검은 띠
            box = (f"scale={sw}:{sh},crop={bw}:{sh}:{x}:0,"
                   f"pad={bw}:{bh}:0:(oh-ih)/2:black")
        else:
            y = "(ih-oh)/2"
            if keep_bottom is not None:  # 원본 자막이 아래에서 잘리지 않게
                y = f"'min((ih-oh)/2,max(0,ih*{keep_bottom:.4f}-oh))'"
            box = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                   f"crop={bw}:{bh}:{x}:{y}")
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


def _keywords(text: str, keywords: list[str], color: str, reset: str = "{\\r}") -> str:
    text = _esc(text)
    kws = sorted({_esc(k.strip()) for k in keywords if k.strip()}, key=len, reverse=True)
    if not kws:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in kws))
    return pattern.sub(lambda m: f"{{\\c{_c(color)}}}{m.group(0)}{reset}", text)


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


OTHER_COLOR = "#FFE14D"  # 묻는 사람·진행자 말 (주인공 말은 흰색)
NOTE_COLOR = "#C8C8C8"   # (고민) 같은 표정 자막


KARAOKE_COLOR = "#4DFF7A"  # 단어마다 색 채우기: 지금 말하는 단어 (노란 자막과 겹치지 않는 초록)
POP = "{\\fscx82\\fscy82\\t(0,120,\\fscx100\\fscy100)}"  # 자막이 살짝 튀어나오기


def _note(c: Cue, size: int, color: str | None = None) -> str:
    """(고민) 같은 표정 자막: 자막 앞에 작은 회색 글자로."""
    if not c.note:
        return ""
    reset = f"{{\\fs{size}\\c{_c(color)}}}" if color else "{\\r}"
    return f"{{\\fs{round(size * 0.72)}\\c{_c(NOTE_COLOR)}}}{_esc(c.note)}{reset} "


def sub_events(c: Cue, name: str, size: int, color: str, *, keywords: list[str] | None = None,
               kw_color: str = "", karaoke: bool = False, pop: bool = False) -> list[str]:
    """자막 한 줄의 Dialogue 줄들.

    karaoke: 캡컷 자동 자막처럼 지금 말하는 단어에 색을 칠한다 (단어마다 한 줄씩).
    pop: 자막이 나올 때 살짝 튀어나온다.
    """
    reset = f"{{\\c{_c(color)}}}"  # \r을 쓰면 튀어나오기 효과까지 지워져서 색만 되돌린다
    fx = POP if pop else ""
    note = _note(c, size, color)
    toks = c.text.split()
    if karaoke and len(toks) > 1 and len(c.words) == len(toks):
        out = []
        for k in range(len(toks)):
            t0 = c.start if k == 0 else max(c.words[k][0], c.start)
            t1 = c.end if k == len(toks) - 1 else min(max(c.words[k + 1][0], t0), c.end)
            if t1 - t0 < 0.01:
                continue
            text = " ".join(f"{{\\c{_c(KARAOKE_COLOR)}}}{_esc(t)}{reset}" if j == k else _esc(t)
                            for j, t in enumerate(toks))
            out.append(f"Dialogue: 0,{_ts(t0)},{_ts(t1)},{name},,0,0,0,,"
                       f"{fx if k == 0 else ''}{note}{text}")
        if out:
            return out
    text = _keywords(c.text, keywords or [], kw_color, reset) if kw_color else _esc(c.text)
    return [f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},{name},,0,0,0,,{fx}{note}{text}"]


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
    karaoke: bool = False,
    pop: bool = False,
) -> None:
    s = style
    tfont = s.title_font or s.font
    speaker_line = s.speaker_size + 22 if (s.speaker_enabled and speaker) else 0
    title_align, title_margin = ((8, s.title_top) if s.title_top else (2, H - s.title_bottom))
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
           "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")

    def st(name, font, size, color, outline, shadow, align, margin_v, border=1, back="#000000",
           margin_l=60, margin_r=60):
        return (f"Style: {name},{font},{size},{_c(color)},&H000000FF&,{_c(back) if border == 3 else '&H00000000&'},"
                f"&H80000000&,-1,0,0,0,100,100,0,0,{border},{outline},{shadow},"
                f"{align},{margin_l},{margin_r},{margin_v},1")

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]", fmt,
        st("Title", tfont, s.title_size, s.title_color, s.title_outline, s.title_shadow,
           title_align, title_margin),
        # 알약: BorderStyle 3 = 글자 뒤에 색 상자
        st("Label", tfont, s.label_size, s.label_color, 14, 0, 2,
           H - s.title_top + 24, border=3, back=s.label_bg),
        # 말자막은 아래쪽을 데드존 바로 위에 맞추고(길면 위로), 인물 소개는 그 바로 위
        st("Speaker", s.font, s.speaker_size, s.speaker_color, 4, 0, 2,
           H - s.sub_bottom + round(s.sub_size * 1.25) + 12, margin_r=150),
        st("Sub", s.font, s.sub_size, s.sub_color, s.sub_outline, 0, 2, H - s.sub_bottom,
           margin_r=150),
        st("SubOther", s.font, s.sub_size, OTHER_COLOR, s.sub_outline, 0, 2, H - s.sub_bottom,
           margin_r=150),
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
        other = c.who == "other"
        lines += sub_events(c, "SubOther" if other else "Sub", s.sub_size,
                            OTHER_COLOR if other else s.sub_color, keywords=keywords,
                            kw_color=s.sub_highlight, karaoke=karaoke, pop=pop)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_account_subs(path: str, acct, cues: list[Cue], *, font_path: str,
                       karaoke: bool = False, pop: bool = False) -> None:
    """계정 가이드의 말자막 (하얀 글자, 설명자막 바로 아래). 글자 모양은 계정 글꼴 그대로."""
    from . import fonts
    from .accounts import SAFE_BOTTOM, SUB_MARGIN_L, SUB_MARGIN_R

    t = acct.sub
    fam = fonts.family(font_path)
    if acct.sub_box:  # 3번: 어두운 상자 위 하얀 글자
        border, outline, outline_c = 3, 12, acct.sub_box
    else:
        border, outline, outline_c = 1, t.stroke, t.stroke_color
    margin = H - SAFE_BOTTOM  # 아래쪽을 데드존 바로 위에 맞춘다 (길면 위로 늘어난다)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{fam},{t.size},{_c(t.color)},&H000000FF&,{_c(outline_c)},&H80000000&,"
        f"0,0,0,0,100,100,0,0,{border},{outline},0,2,{SUB_MARGIN_L},{SUB_MARGIN_R},{margin},1",
        f"Style: SubOther,{fam},{t.size},{_c(OTHER_COLOR)},&H000000FF&,{_c(outline_c)},&H80000000&,"
        f"0,0,0,0,100,100,0,0,{border},{outline},0,2,{SUB_MARGIN_L},{SUB_MARGIN_R},{margin},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in cues:
        other = c.who == "other"
        lines += sub_events(c, "SubOther" if other else "Sub", t.size,
                            OTHER_COLOR if other else t.color, karaoke=karaoke, pop=pop)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def account_box_style(vertical: bool) -> Style:
    """계정 가이드 영상 배치: N-3(세로 촬영본)은 화면 가득, N-4(롱폼)는 가운데 상자."""
    from .accounts import BOX_BOTTOM, BOX_TOP

    if vertical:
        return Style(video_top=0, video_height=H, video_fit="fill")
    return Style(background="black", video_top=BOX_TOP, video_height=BOX_BOTTOM - BOX_TOP,
                 video_fit="fill")


# ---------- 시청 지속 장치 (훅 자막, 중간 한마디, 진행 막대) ----------

def add_retention(path: str, *, duration: float, font: str, hook: str = "", rehook: str = "",
                  rehook_at: float | None = None, video_top: int = 0, video_height: int = H,
                  bar: bool = True, color: str = "#FFE600") -> None:
    """이미 만든 ASS 자막 파일에 이탈을 막는 장치를 더한다.

    - 훅 자막: 처음 2.2초 동안 영상 위쪽에 크게 '툭' 튀어나오는 한 줄 (끝까지 볼 이유)
    - 중간 한마디: 결론 직전에 '진짜는 지금부터' 같은 짧은 예고
    - 진행 막대: 영상 위 가장자리에서 차오르는 얇은 막대 (얼마 안 남은 게 보이면 끝까지 본다)
    """
    events = []
    styles = [
        f"Style: Hook,{font},96,{_c('#FFFFFF')},&H000000FF&,&H00000000&,&H00000000&,"
        f"-1,0,0,0,100,100,0,0,1,9,3,5,40,40,0,1",
        f"Style: Rehook,{font},62,{_c('#FFFFFF')},&H000000FF&,&HC0000000&,&H00000000&,"
        f"-1,0,0,0,100,100,0,0,3,16,0,5,40,40,0,1",
        f"Style: Bar,{font},20,{_c(color)},&H000000FF&,&H00000000&,&H00000000&,"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
    ]
    y = int(video_top + video_height * (0.24 if video_top else 0.30))
    if hook.strip():
        end = min(2.2, duration)
        # 작게 시작해 살짝 커졌다가 제자리로 (눈길을 끄는 '툭')
        pop = r"{\fscx70\fscy70\t(0,140,\fscx108\fscy108)\t(140,260,\fscx100\fscy100)\fad(0,250)}"
        text = _esc(hook.strip().replace("{", "").replace("}", ""))
        events.append(f"Dialogue: 5,{_ts(0)},{_ts(end)},Hook,,0,0,0,,{{\\pos({W // 2},{y})}}{pop}{text}")
    if rehook.strip() and rehook_at is not None and 2.5 < rehook_at < duration - 1.0:
        end = min(rehook_at + 2.0, duration)
        events.append(f"Dialogue: 5,{_ts(rehook_at)},{_ts(end)},Rehook,,0,0,0,,"
                      f"{{\\pos({W // 2},{y})\\fad(150,200)}}{_esc(rehook.strip())}")
    if bar and duration > 3:
        top = max(video_top, 0)
        ms = int(duration * 1000)
        shape = f"m 0 0 l {W} 0 l {W} 10 l 0 10"
        events.append(f"Dialogue: 4,{_ts(0)},{_ts(duration)},Bar,,0,0,0,,"
                      f"{{\\pos(0,{top})\\clip(0,{top},1,{top + 10})"
                      f"\\t(0,{ms},\\clip(0,{top},{W},{top + 10}))\\p1}}{shape}")
    if not events:
        return
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    text = text.replace("\n[Events]", "\n" + "\n".join(styles) + "\n\n[Events]", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n" + "\n".join(events) + "\n")
