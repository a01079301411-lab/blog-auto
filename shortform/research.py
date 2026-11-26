"""레퍼런스 자동 조사: 영상을 만들기 전에 같은 주제로 실제로 터진 숏폼·릴스를 웹에서 찾아
그 공통 공식(훅, 구성과 타이밍, 자막, 컷 템포, 제목, 썸네일, 마무리)을 '설계도'로 정리한다.

설계도는 하이라이트 고르기·검수·제목·화면 문구·썸네일을 정할 때 AI에게 함께 주고,
결과 폴더에 '레퍼런스.txt'로 남겨 어떤 영상을 참고했는지 볼 수 있게 한다.

Claude의 웹 검색(web_search, 서버에서 실행)을 쓴다. 같은 영상 종류·주제는 7일 동안
다시 조사하지 않고 저장해 둔 설계도를 쓴다. 조사가 실패해도 편집은 그대로 진행한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .highlights import MODEL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, ".research_cache")
TTL = 7 * 24 * 3600

SYSTEM = """\
You are a short-form video research lead for a Korean creator. Before an editor cuts new
footage, you find real reference videos that performed well and turn what they have in
common into a concrete editing blueprint.

Use web search. Look for Korean YouTube Shorts, Instagram Reels and TikToks (and strong
non-Korean ones when Korean ones are scarce) on the same topic or format as the footage
described, that clearly performed well (high views, many likes or comments, featured in
articles or rankings). Prefer recent ones (last 12 months). Also look for current
guidance on what makes this genre retain viewers. Search at least 4 different queries
(Korean and English). Do not invent videos, numbers or URLs; only list what you found,
and write "unknown" for views you could not confirm.

Then write the blueprint for THIS footage: specific, measurable rules an editor can
follow (seconds, word counts, positions), not generic advice. Respect the creator's
instructions; the blueprint must never ask for things that are not in the footage, and
never anything false (exaggeration is fine, lies are not).

Finish your answer with one JSON object in a ```json block, exactly these keys:
{
 "references": [{"title": "", "url": "", "platform": "", "views": "", "why": ""}],
 "hook": "first 0-3 seconds: what is shown and said/written, with 2-3 example hook lines for this footage",
 "structure": "beat-by-beat plan with timings for the target length (e.g. 0-3s hook, 3-15s ...)",
 "pacing": "cut length, when to cut, how long any shot may stay",
 "captions": "subtitle rules: chars per line, lines on screen, position, emphasis words/colors",
 "text_overlays": "on-screen text/beat captions: how often, wording style, examples",
 "title": "title formula with 3 examples for this footage (each <= 16 Korean characters, no slashes)",
 "thumbnail": "what the cover frame and its text show, with 2 example cover texts",
 "ending": "how the last 3 seconds end (loop, payoff, question for comments)",
 "avoid": "what made weaker videos in this genre fail"
}
Write every value in Korean except URLs."""

FIELDS = [("hook", "훅(첫 3초)"), ("structure", "구성·타이밍"), ("pacing", "컷 템포"),
          ("captions", "자막"), ("text_overlays", "화면 문구"), ("title", "제목"),
          ("thumbnail", "썸네일"), ("ending", "마무리"), ("avoid", "피할 것")]


def _key(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("_saved", 0) < TTL and data.get("hook"):
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _parse(text: str) -> dict | None:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = blocks[::-1] or [text[text.find("{"): text.rfind("}") + 1]]
    for raw in candidates:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("hook"):
            return data
    return None


def _ask(client, prompt: str) -> str:
    """웹 검색을 켜고 묻는다. 검색이 길어 중간에 멈추면(pause_turn) 이어서 하게 한다."""
    messages = [{"role": "user", "content": prompt}]
    texts: list[str] = []
    for _ in range(4):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=SYSTEM,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 12}],
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        texts += [b.text for b in msg.content if b.type == "text"]
        if msg.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": msg.content}]
    return "".join(texts)


def blueprint(*, guide_key: str, guide_name: str, topic: str, direction: str = "",
              target: str = "", sample: str = "", fmt: str = "숏폼(세로, 쇼츠·릴스)",
              client=None, refresh: bool = False) -> dict | None:
    """레퍼런스를 조사해 편집 설계도를 만든다. 실패하면 None."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, _key(guide_key, topic.strip()[:400], direction.strip()[:400],
                                        target, fmt) + ".json")
    if not refresh and (data := _load(path)):
        data["_cached"] = True
        return data
    prompt = (f"<format>{fmt}, 목표 길이 {target or '자유'}</format>\n"
              f"<video_type>{guide_name}</video_type>\n"
              f"<about_footage>\n{topic.strip() or '(설명 없음)'}\n</about_footage>\n")
    if direction.strip():
        prompt += f"<creator_instructions>\n{direction.strip()}\n</creator_instructions>\n"
    if sample.strip():
        prompt += f"<what_is_said_in_the_footage>\n{sample.strip()[:3000]}\n</what_is_said_in_the_footage>\n"
    prompt += ("\nFind the best-performing reference videos for this and write the editing "
               "blueprint for this footage.")
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        data = _parse(_ask(client, prompt))
    except Exception as e:  # API 키 없음, 네트워크 오류 등: 레퍼런스 없이 진행
        print(f"  (레퍼런스 조사 건너뜀: {type(e).__name__}: {str(e)[:120]})")
        return None
    if not data:
        print("  (레퍼런스 조사 결과를 읽지 못해 건너뜀)")
        return None
    data["references"] = [r for r in data.get("references") or [] if isinstance(r, dict)][:10]
    data["_saved"] = time.time()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return data


def prompt_text(bp: dict | None) -> str:
    """하이라이트 고르기·검수에 넣을 설계도."""
    if not bp:
        return ""
    rows = [f"- {label}: {bp[k]}" for k, label in FIELDS if str(bp.get(k, "")).strip()]
    refs = [f"  · {r.get('title', '')} ({r.get('platform', '')}, {r.get('views', '')}): {r.get('why', '')}"
            for r in bp.get("references", [])[:6]]
    return ("<reference_blueprint>\nBefore editing, real top-performing videos of this kind were "
            "researched. Build every clip, title, beat caption and thumbnail to this blueprint "
            "(the creator's instructions still win when they differ). Use only moments that "
            "really exist in this footage.\n" + "\n".join(rows)
            + ("\nReferences studied:\n" + "\n".join(refs) if refs else "")
            + "\n</reference_blueprint>")


def report(bp: dict | None) -> str:
    """결과 폴더에 남길 '레퍼런스.txt' 내용."""
    if not bp:
        return ""
    out = ["[참고한 레퍼런스]"]
    for k, r in enumerate(bp.get("references", []), 1):
        out.append(f"{k}. {r.get('title', '')} — {r.get('platform', '')}, 조회수 {r.get('views', '?')}")
        if r.get("url"):
            out.append(f"   {r['url']}")
        if r.get("why"):
            out.append(f"   왜: {r['why']}")
    out.append("\n[이 영상에 적용한 편집 설계도]")
    out += [f"■ {label}\n{bp[k]}\n" for k, label in FIELDS if str(bp.get(k, "")).strip()]
    return "\n".join(out)


def log(bp: dict | None) -> None:
    if not bp:
        return
    refs = bp.get("references", [])
    how = "저장해 둔 조사 결과" if bp.get("_cached") else "새로 조사"
    print(f"  레퍼런스 {len(refs)}개 참고 ({how})")
    for r in refs[:5]:
        print(f"   · {r.get('title', '')[:40]} ({r.get('platform', '')}, {r.get('views', '?')})")
    if bp.get("hook"):
        print(f"  훅 공식: {str(bp['hook'])[:80]}")
