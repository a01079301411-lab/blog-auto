"""'최근 1개월 잘 터진 콘텐츠' 수집·분석 → 패턴 가중치 갱신 → 원고 생성에 반영.

소스
- 인스타: 공식 해시태그 검색(ig_hashtag_search → top_media). 좋아요·댓글 수 제공.
- 스레드: 공식 keyword_search(TOP). 권한(threads_keyword_search) 필요.
- 수동: 사람이 본 게시물을 `trends add` 로 추가(링크·조회수·첫 줄).
결과
- data/trends/latest.json  : 레퍼런스(출처 링크·날짜·지표·패턴)
- data/trends/patterns.json: 패턴 weight 갱신(지수 평활)
- data/trends/report_YYYY-MM-DD.md : 레퍼런스 → 빌린 패턴 → 우리 버전
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import timedelta

from .config import TRENDS, now, settings
from .ops import meta_ts

RULES = {
    "IG_UNIT_PRICE": r"(1|한)\s?(개|알|포|팩|회|번|장|롤|봉|병)\s?(당|에)?\s?(약\s?)?\d[\d,]*\s?원|\d[\d,]*\s?원\s?(꼴|씩)",
    "IG_QUIZ_3S": r"퀴즈|정답|맞혀|맞춰|몇\s?(g|ml|개|원|번)|뭘까|어느\s?쪽|제일\s?(싼|비싼)",
    "IG_CHECK3_SAVE": r"\d\s?가지|체크\s?리스트|이것만|이\s?\d개만|꼭\s?(보|확인)|저장",
    "IG_COMPARE_AB": r"\bvs\b|VS|비교|차이",
    "IG_SEND_CTA": r"보내|공유|태그",
    "TH_CONFESS_Q": r"저만|나만|다들|여러분|있으세요\?|하세요\?|그래요\?",
    "TH_PICK_ONE": r"(^|\s)[1-3]\s?[).번]|번호|골라|고르",
    "TH_TOPIC_VOTE": r"추천\s?해\s?주|자랑|뭐\s?(살|사|할)까",
    "HOOK_WARNING": r"하지\s?마세요|절대|모르면\s?손해|속지|후회",
    "HOOK_TWIST": r"알고\s?보니|사실은|반전|몰랐",
}


def classify(text: str) -> list[str]:
    t = text or ""
    return [k for k, rx in RULES.items() if re.search(rx, t, re.I)]


def first_line(text: str) -> str:
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if ln:
            return ln[:80]
    return ""


def fetch() -> list[dict]:
    from .publish.meta_api import Instagram, Threads
    s = settings()["trends"]
    since = now() - timedelta(days=s["window_days"])
    refs: list[dict] = []
    try:
        ig = Instagram()
        for tag in s["instagram_hashtags"]:
            try:
                items = [m for m in ig.hashtag_top(tag) if meta_ts(m["timestamp"]) >= since]
            except Exception as e:  # noqa: BLE001
                print(f"[trends] #{tag} 실패: {e}")
                continue
            eng = [(m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0) for m in items]
            med = statistics.median(eng) if eng else 1
            for m, e in zip(items, eng):
                refs.append({"platform": "instagram", "source": f"#{tag}", "permalink": m.get("permalink"),
                             "timestamp": m["timestamp"], "type": m.get("media_product_type") or m.get("media_type"),
                             "likes": m.get("like_count"), "comments": m.get("comments_count"),
                             "score": round(e / (med or 1), 2), "text": (m.get("caption") or "")[:400]})
    except SystemExit as e:
        print(f"[trends] 인스타 API 미설정: {e}")
    try:
        th = Threads()
        for kw in s["threads_keywords"]:
            try:
                items = [m for m in th.keyword_search(kw) if meta_ts(m["timestamp"]) >= since]
            except Exception as e:  # noqa: BLE001
                print(f"[trends] '{kw}' 실패: {e}")
                continue
            for rank, m in enumerate(items):
                refs.append({"platform": "threads", "source": kw, "permalink": m.get("permalink"),
                             "timestamp": m["timestamp"], "type": m.get("media_type"),
                             "score": round(len(items) / (rank + 1) / max(1, len(items)) * 3, 2),
                             "text": (m.get("text") or "")[:400]})
    except SystemExit as e:
        print(f"[trends] 스레드 API 미설정: {e}")
    return refs


def load_latest() -> dict:
    p = TRENDS / "latest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"references": []}


def add_manual(url: str, platform: str, text: str, views: int | None = None, note: str = "") -> None:
    data = load_latest()
    data["references"].append({"platform": platform, "source": "manual", "permalink": url,
                               "timestamp": now().strftime("%Y-%m-%dT%H:%M:%S%z"), "views": views,
                               "score": 3.0 if views else 1.5, "text": text[:400], "note": note})
    analyze(data["references"])


def analyze(refs: list[dict], top: int = 30) -> dict:
    for r in refs:
        r["first_line"] = first_line(r.get("text", ""))
        r["patterns"] = classify(r.get("text", ""))
    refs.sort(key=lambda r: r.get("score") or 0, reverse=True)
    top_refs = refs[:top]
    stats: dict[str, float] = {}
    for r in top_refs:
        for p in r["patterns"]:
            stats[p] = stats.get(p, 0) + (r.get("score") or 1)
    total = sum(stats.values()) or 1
    share = {k: round(v / total, 3) for k, v in sorted(stats.items(), key=lambda x: -x[1])}
    data = {"updated": now().strftime("%Y-%m-%d %H:%M"), "pattern_share": share, "references": refs}
    TRENDS.mkdir(parents=True, exist_ok=True)
    (TRENDS / "latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _update_weights(share)
    _report(data)
    return data


def _update_weights(share: dict) -> None:
    p = TRENDS / "patterns.json"
    lib = json.loads(p.read_text(encoding="utf-8"))
    for plat in ("instagram", "threads"):
        ids = [x["id"] for x in lib[plat]]
        n = len(ids)
        for x in lib[plat]:
            target = 1.0 + (share.get(x["id"], 0) * n - (1 / n) * n) * 0.5   # 평균 점유=1.0 기준
            x["weight"] = round(max(0.3, min(2.5, 0.7 * x["weight"] + 0.3 * target)), 2)
    lib["updated"] = now().strftime("%Y-%m-%d")
    p.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")


def _report(data: dict) -> str:
    lib = json.loads((TRENDS / "patterns.json").read_text(encoding="utf-8"))
    ours = {x["id"]: x for plat in ("instagram", "threads") for x in lib[plat]}
    lines = [f"# 트렌드 리포트 {data['updated']}", "",
             "> 레퍼런스 → 빌린 패턴 → 우리 버전. 문구·장면은 복사하지 않는다.", "",
             "## 패턴 점유율(상위 레퍼런스 가중)", ""]
    lines += [f"- {k}: {v:.0%}" for k, v in data["pattern_share"].items()]
    lines += ["", "## 상위 레퍼런스", "", "| # | 플랫폼 | 출처 | 날짜 | 점수 | 첫 줄 | 빌린 패턴 | 우리 버전 |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(data["references"][:15], 1):
        pat = ", ".join(r["patterns"]) or "-"
        mine = next((ours[p]["example_ours"] for p in r["patterns"] if p in ours), "-")
        fl = r["first_line"].replace("|", "/")
        lines.append(f"| {i} | {r['platform']} | [{r['source']}]({r.get('permalink')}) | {str(r.get('timestamp'))[:10]} | "
                     f"{r.get('score')} | {fl} | {pat} | {mine} |")
    path = TRENDS / f"report_{now():%Y-%m-%d}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def run() -> dict:
    refs = fetch()
    old = [r for r in load_latest().get("references", []) if r.get("source") == "manual"]
    if not refs and not old:
        print("[trends] 수집된 레퍼런스 없음 (API 설정 필요). 기존 patterns.json 유지.")
        return {}
    return analyze(refs + old)
