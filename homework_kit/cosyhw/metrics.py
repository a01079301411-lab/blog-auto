"""실측 데이터 저장소: 성민 PC의 collector.py가 만든 results.json + shots/ 를 읽는다.

원칙(SOLUTION_차단문제해결.md 5장)
- 클라우드/프로그램은 인스타·유튜브에 직접 접속하지 않는다. 수치는 results.json에서만 가져온다.
- results.json에 없는 수치는 절대 추정하지 않는다 → missing 목록에 올리고 PC에서 다시 collect.
- '평소 대비'는 계정 수집 결과에서 고정 게시물·대상 게시물을 빼고 최근 5~10개 평균으로 계산.
- 후킹 칸은 shots/의 0.5초 캡처로만 쓴다. 캡처가 없으면 '캡처 필요'.
- collected_at이 3일 넘으면 경고.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .fmt import fmt_count, parse_count
from .paths import KIT

COLLECTOR_DIR = KIT / "collector"
DEFAULT_RESULTS = COLLECTOR_DIR / "results.json"
SHOTS_DIR = COLLECTOR_DIR / "shots"
STALE_DAYS = 3


def norm_url(u: str) -> str:
    """비교용 키: 스킴·www·m.·끝 슬래시·추적 파라미터 제거. 유튜브는 영상 ID, 인스타는 게시물 코드로."""
    u = (u or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    p = urlparse(u)
    host = (p.hostname or "").lower()
    for pre in ("www.", "m.", "mobile."):
        if host.startswith(pre):
            host = host[len(pre):]
    path = p.path.rstrip("/")
    if host in ("youtube.com", "youtu.be"):
        if host == "youtu.be":
            return "yt:" + path.strip("/")
        v = parse_qs(p.query).get("v")
        if v:
            return "yt:" + v[0]
        m = re.search(r"/(?:shorts|live|embed)/([\w-]{11})", path)
        if m:
            return "yt:" + m.group(1)
        m = re.search(r"/post/([\w-]+)", path)
        if m:
            return "ytpost:" + m.group(1)
        return "yt:" + path.lower()
    if host == "instagram.com":
        m = re.search(r"/(?:p|reel|reels|tv)/([\w-]+)", path)
        if m:
            return "ig:" + m.group(1)
        return "ig:@" + path.strip("/").split("/")[0].lower()
    if host == "tiktok.com":
        m = re.search(r"/(?:video|photo)/(\d+)", path)
        if m:
            return "tt:" + m.group(1)
        m = re.search(r"@([\w.]+)", path)
        return "tt:@" + (m.group(1).lower() if m else path)
    return host + path


def _parse_time(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:16], fmt)
        except ValueError:
            continue
    return None


@dataclass
class Store:
    path: Path
    data: dict = field(default_factory=dict)          # 원래 키(수집한 URL) → 결과
    index: dict = field(default_factory=dict)         # 정규화 키 → 원래 키
    missing: dict = field(default_factory=dict)       # 정규화 키 → (url, 이유)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Store":
        p = Path(path) if path else DEFAULT_RESULTS
        st = cls(path=p)
        if p.exists():
            st.data = json.loads(p.read_text(encoding="utf-8"))
            for k in st.data:
                st.index[norm_url(k)] = k
        return st

    # ---- 조회
    def get(self, url: str) -> dict | None:
        k = self.index.get(norm_url(url))
        if k is None:
            return None
        r = self.data[k]
        return None if "err" in r else r

    def has(self, url: str) -> bool:
        return self.get(url) is not None

    def error_of(self, url: str) -> str | None:
        k = self.index.get(norm_url(url))
        return self.data[k].get("err") if k and "err" in self.data[k] else None

    def need(self, url: str, reason: str) -> None:
        if not self.has(url):
            self.missing.setdefault(norm_url(url), (url.strip(), reason))

    # ---- 최신성
    def stale(self, days: int = STALE_DAYS) -> list[str]:
        now = dt.datetime.now()
        old = []
        for k, r in self.data.items():
            t = _parse_time(r.get("collected_at"))
            if t and (now - t).days >= days:
                old.append(f"{k} (수집 {r.get('collected_at')})")
        return old

    def summary(self) -> str:
        ok = sum(1 for r in self.data.values() if "err" not in r)
        err = len(self.data) - ok
        times = sorted(filter(None, (_parse_time(r.get("collected_at")) for r in self.data.values())))
        span = f"{times[0]:%Y-%m-%d %H:%M} ~ {times[-1]:%Y-%m-%d %H:%M}" if times else "수집 시각 없음"
        return f"results.json: 성공 {ok}건 / 실패 {err}건 / 수집 {span} ({self.path})"

    # ---- 평소 대비
    def baseline(self, target_url: str, account_url: str, n_min: int = 5, n_max: int = 10) -> dict:
        acct = self.get(account_url)
        if not acct:
            self.need(account_url, "평소 대비 계산용 계정 최근 게시물")
            return {"error": f"results.json에 계정 수집 결과가 없음 → PC에서 collect 필요: {account_url}"}
        target = self.get(target_url)
        if not target:
            self.need(target_url, "평소 대비 대상 게시물")
            return {"error": f"results.json에 대상 게시물이 없음 → PC에서 collect 필요: {target_url}"}
        tkey = norm_url(target_url)
        tval = target.get("views") or parse_count(target.get("likes"))
        items = acct.get("recent_reels") or acct.get("recent") or []
        vals = []
        for i, it in enumerate(items):
            if acct.get("recent_reels") and i < 3:      # 릴스 탭 앞 3개는 고정 게시물일 수 있음
                continue
            href = it.get("href") or it.get("url") or (f"https://www.tiktok.com/video/{it['id']}" if it.get("id") else "")
            if href and norm_url(href if "://" in href else "https://www.instagram.com" + href) == tkey:
                continue
            if it.get("id") and tkey.endswith(str(it.get("id"))):
                continue
            v = it.get("views")
            v = parse_count(v) if not isinstance(v, int) else v
            if v:
                vals.append(v)
            if len(vals) >= n_max:
                break
        if len(vals) < n_min:
            return {"error": f"고정·대상 제외 후 최근 게시물이 {len(vals)}개뿐(5개 이상 필요)", "recent": vals}
        avg = sum(vals) / len(vals)
        mult = tval / avg if (tval and avg) else None
        return {"target": fmt_count(tval) if tval else "미확인", "n": len(vals), "recent": [fmt_count(v) for v in vals],
                "avg": fmt_count(avg), "multiple": round(mult, 1) if mult else None,
                "sentence": f"최근 {len(vals)}개 평균 약 {fmt_count(avg)}의 약 {mult:.1f}배" if mult else "",
                "source": f"{account_url} (수집 {acct.get('collected_at')})"}

    # ---- 캡처
    def shot(self, url: str) -> Path | None:
        key = norm_url(url).split(":", 1)[-1].lstrip("@")
        if not SHOTS_DIR.exists():
            return None
        for pat in (f"{key}_0.5s.jpg", f"{key}_cover.jpg", f"{key}.jpg"):
            p = SHOTS_DIR / pat
            if p.exists():
                return p
        return None

    # ---- 누락 목록 출력
    def write_missing(self, out: str | Path) -> Path | None:
        if not self.missing:
            return None
        out = Path(out)
        lines = ["# PC에서: python collector/collector.py collect 이파일 collector/results.json",
                 "# 아래 링크의 실측이 results.json에 없어 숙제를 완성할 수 없습니다 (추정 금지)"]
        for _, (u, why) in self.missing.items():
            lines.append(f"# {why}")
            lines.append(u if u.startswith("http") else "https://" + u)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out
