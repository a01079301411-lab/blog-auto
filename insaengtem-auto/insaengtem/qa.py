"""검수(자동 체크리스트). docs/DESIGN.md 5-5 + 2026-11 트렌드 규칙.

반환: list[Issue]. level = 'error'(게시 차단) | 'warn'(사람 확인).
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import settings

_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
_URL = re.compile(r"https?://\S+")
_HASHTAG = re.compile(r"#[^\s#]+")


@dataclass
class Issue:
    level: str
    code: str
    msg: str
    where: str = ""

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.code} {self.where}: {self.msg}"


def amounts(text: str) -> list[int]:
    return [int(x.replace(",", "")) for x in _AMOUNT.findall(text or "")]


def check_text(text: str, *, where: str, is_ad: bool, allowed: set[int] | None = None,
               platform: str = "", references: list[str] | None = None) -> list[Issue]:
    s = settings()
    out: list[Issue] = []
    if text is None:
        return out
    if unicodedata.normalize("NFC", text) != text:
        out.append(Issue("error", "UNICODE_NFC", "자모 분리(NFD) 문자가 섞여 있음 → 화면에서 글자가 깨질 수 있음", where))
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Co", "Cn") or (0x1100 <= ord(ch) <= 0x11FF):
            out.append(Issue("error", "ODD_CHAR", f"비정상 문자 {ch!r} (U+{ord(ch):04X})", where))
            break
        if 0x3130 <= ord(ch) <= 0x318F:
            out.append(Issue("warn", "JAMO", f"낱자 {ch!r} 포함(ㅋㅋ 등) — 의도한 것인지 확인", where))
            break
        if 0x4E00 <= ord(ch) <= 0x9FFF:
            out.append(Issue("warn", "HANJA", f"한자 {ch!r} 포함 — 의도한 것인지 확인", where))
            break
    first = text.strip().split("\n", 1)[0]
    if is_ad and not first.startswith("[광고]"):
        out.append(Issue("error", "AD_LABEL", "첫 줄이 [광고]로 시작하지 않음", where))
    for w in s["banned_phrases"]:
        if w in text:
            out.append(Issue("error", "BANNED", f"금지 표현 '{w}' (사용 경험·효능 보장 표현 금지)", where))
    for w in s.get("caution_phrases", []):
        if w in text:
            out.append(Issue("warn", "CAUTION", f"근거 필요 표현 '{w}'", where))
    for w in s.get("typo_watch", []):
        if w in text:
            out.append(Issue("error", "TYPO", f"오타 의심 '{w}'", where))
    if allowed is not None:
        for a in amounts(text):
            if a not in allowed and a >= 100:
                out.append(Issue("error", "NUMBER", f"수집 데이터에 없는 금액 {a:,}원", where))
    if platform == "instagram":
        tags = _HASHTAG.findall(text)
        mx = s["instagram"]["hashtag_max"]
        if len(tags) > mx:
            out.append(Issue("error", "HASHTAG_MAX", f"해시태그 {len(tags)}개 > {mx}개 (인스타 제한)", where))
        if tags and tags[-1] != s["instagram"]["hashtag_last"]:
            out.append(Issue("warn", "HASHTAG_LAST", f"마지막 해시태그가 {s['instagram']['hashtag_last']} 아님", where))
        if _URL.search(text):
            out.append(Issue("warn", "IG_LINK", "인스타 캡션 링크는 클릭 불가 → '프로필 링크' 안내로", where))
        if "보내" not in text and is_ad:
            out.append(Issue("warn", "SEND_CTA", "보내기(DM 공유) CTA 없음 — sends 신호용 1줄 권장", where))
    if platform == "threads_root":
        if _URL.search(text):
            out.append(Issue("error", "TH_ROOT_LINK", "스레드 본문(1번째 칸)에 링크 금지 → 2번째 칸으로", where))
        if len(text) > settings()["threads"]["max_chars"]:
            out.append(Issue("error", "TH_LEN", f"{len(text)}자 > 500자", where))
    if platform == "threads_reply" and text and "{link}" not in text and not _URL.search(text):
        out.append(Issue("error", "TH_NO_LINK", "2번째 칸에 링크가 없음", where))
    for ref in references or []:
        r = difflib.SequenceMatcher(None, _norm(text), _norm(ref)).ratio()
        if r >= 0.6:
            out.append(Issue("error", "COPY", f"레퍼런스와 유사도 {r:.0%} — 패턴만 빌리고 문구는 새로", where))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+|\[광고\]|#\S+", "", s or "")


def check_product_cfg(cfg: dict, facts: dict | None, allowed: set[int] | None, key: str) -> list[Issue]:
    """제품 영상 JSON(화면에 들어갈 텍스트) 검수."""
    out: list[Issue] = []
    texts: list[tuple[str, str]] = []
    texts += [(f"hook[{i}]", h["t"]) for i, h in enumerate(cfg.get("hook", []))]
    m = cfg.get("math", {})
    texts += [("math.formula", m.get("formula", "")), ("math.sub", m.get("sub", ""))]
    texts += [(f"usp.rows[{i}]", " ".join(r)) for i, r in enumerate(cfg.get("usp", {}).get("rows", []))]
    o = cfg.get("offer", {})
    texts += [("offer", " ".join(str(o.get(k, "")) for k in ("orig", "price", "note")))]
    texts += [(f"offer.rows[{i}]", " ".join(r)) for i, r in enumerate(o.get("rows", []))]
    for v, d in cfg.get("variants", {}).items():
        c = d.get("cover", {})
        texts.append((f"{v}.cover", " ".join([c.get("top", ""), c.get("big", ""), c.get("sticker", "")])))
        if len(c.get("big", "")) > 7:
            out.append(Issue("warn", "COVER_BIG", f"커버 big '{c.get('big')}' 7자 초과", f"{key}.{v}"))
        if len(c.get("top", "")) > 15:
            out.append(Issue("warn", "COVER_TOP", f"커버 top '{c.get('top')}' 15자 초과", f"{key}.{v}"))
        q = d.get("quiz")
        if q:
            texts += [(f"{v}.quiz", q["question"] + " " + q["note"])]
            texts += [(f"{v}.quiz.opt{i}", " ".join(x)) for i, x in enumerate(q["options"])]
            if not 0 <= q["answer"] < len(q["options"]):
                out.append(Issue("error", "QUIZ_ANSWER", "정답 인덱스 범위 밖", f"{key}.{v}"))
            elif facts is not None:
                ans = q["options"][q["answer"]][0]
                hay = " ".join(facts.get("bullets", [])) + " " + facts.get("name", "") + json.dumps(facts.get("options", []), ensure_ascii=False)
                if not any(tok in hay for tok in re.findall(r"\d+\s*(?:g|ml|구|팩|포|개)", ans)) and not amounts(ans):
                    out.append(Issue("warn", "QUIZ_FACT", f"정답 '{ans}' 이 수집 데이터에서 확인되지 않음", f"{key}.{v}"))
        for i, r in enumerate(d.get("reasons", [])):
            texts.append((f"{v}.reason{i}", " ".join(r)))
        if d.get("layout", v) == "v3" and len(d.get("reasons", [])) != 3:
            out.append(Issue("error", "REASONS", "v3 이유는 정확히 3개", f"{key}.{v}"))
    for where, t in texts:
        out += check_text(t, where=f"{key}.{where}", is_ad=False, allowed=allowed)
    # 계산식 검증: '4팩 30,800원 ÷ 4' == value
    f = m.get("formula", "")
    mm = re.search(r"(\d[\d,]*)\s*원\s*÷\s*(\d+)", f)
    if mm and m.get("value"):
        total, n = int(mm.group(1).replace(",", "")), int(mm.group(2))
        exact = total / n
        if round(exact) != m["value"]:
            out.append(Issue("error", "MATH", f"{f} = {exact:.2f} 인데 화면 값 {m['value']}", key))
        elif total % n and "약" not in m.get("fmt", ""):
            out.append(Issue("warn", "MATH_APPROX", f"{f} 는 나눠떨어지지 않음 → '약' 표기 권장 (fmt: {m.get('fmt')})", key))
    if facts and facts.get("soldout"):
        out.append(Issue("error", "SOLDOUT", "품절 제품", key))
    img = cfg.get("image")
    from .config import ROOT
    if img and not (ROOT / img).exists():
        out.append(Issue("error", "IMAGE", f"이미지 없음 {img}", key))
    return out


def ffprobe(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        raise SystemExit("ffprobe 가 필요합니다 (ffmpeg 설치).")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def check_video(path: Path) -> list[Issue]:
    v = settings()["video"]
    out: list[Issue] = []
    if not path.exists():
        return [Issue("error", "VIDEO_MISSING", "영상 파일 없음", str(path))]
    info = ffprobe(path)
    dur = float(info["format"]["duration"])
    if abs(dur - v["duration"]) > 0.15:
        out.append(Issue("error", "DURATION", f"{dur:.2f}초 (기준 {v['duration']}초)", path.name))
    vs = [s for s in info["streams"] if s["codec_type"] == "video"]
    au = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not vs:
        out.append(Issue("error", "NO_VIDEO", "비디오 스트림 없음", path.name))
    else:
        s = vs[0]
        if (s["width"], s["height"]) != (v["width"], v["height"]):
            out.append(Issue("error", "SIZE", f"{s['width']}x{s['height']}", path.name))
        if s.get("codec_name") != "h264":
            out.append(Issue("warn", "CODEC", s.get("codec_name", "?"), path.name))
    if not au:
        out.append(Issue("error", "NO_AUDIO", "오디오 트랙 없음", path.name))
    if path.with_name("cover_9x16.jpg").exists() is False:
        out.append(Issue("warn", "COVER", "커버 이미지 없음", path.name))
    return out


def summarize(issues: list[Issue]) -> tuple[int, int]:
    return sum(i.level == "error" for i in issues), sum(i.level == "warn" for i in issues)
