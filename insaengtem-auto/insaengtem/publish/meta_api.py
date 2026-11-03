"""Instagram Graph API(REELS) + Threads API 게시·조회.

[업데이트 필요] 착수 전 Meta 최신 문서로 버전·필드명 재확인 (config/settings.json api.*).
- 인스타: Instagram API with Facebook Login. 리일 업로드는 resumable(rupload.facebook.com)이라 공개 URL 불필요.
  계정당 API 게시 100건/24시간.
- 스레드: 영상은 video_url(공개 URL) 필요 → media_host.py. 게시 250건/24시간. 2번째 칸은 reply_to_id.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import ROOT, env, settings


class ApiError(RuntimeError):
    pass


def _check(r: requests.Response) -> dict:
    try:
        j = r.json()
    except ValueError:
        raise ApiError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in j:
        e = j.get("error", {})
        raise ApiError(f"HTTP {r.status_code} {e.get('type', '')} {e.get('code', '')}: {e.get('message', j)}")
    return j


# ------------------------------------------------------------------ Instagram
class Instagram:
    def __init__(self):
        a = settings()["api"]
        self.base = f"{a['graph_base']}/{a['graph_version']}"
        self.ver = a["graph_version"]
        self.uid = env("IG_USER_ID", required=True)
        self.token = env("IG_ACCESS_TOKEN", required=True)

    def _get(self, path, **params):
        params["access_token"] = self.token
        return _check(requests.get(f"{self.base}/{path}", params=params, timeout=60))

    def _post(self, path, **data):
        data["access_token"] = self.token
        return _check(requests.post(f"{self.base}/{path}", data=data, timeout=120))

    def publish_reel(self, video: Path, caption: str, cover_offset_ms: int = 0) -> dict:
        size = video.stat().st_size
        c = self._post(f"{self.uid}/media", media_type="REELS", upload_type="resumable", caption=caption,
                       share_to_feed="true", thumb_offset=str(cover_offset_ms))
        cid = c["id"]
        upload_uri = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.ver}/{cid}"
        with open(video, "rb") as fh:
            r = requests.post(upload_uri, data=fh, timeout=600, headers={
                "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)})
        _check(r)
        self._wait(cid)
        pub = self._post(f"{self.uid}/media_publish", creation_id=cid)
        mid = pub["id"]
        info = self._get(mid, fields="permalink,shortcode,timestamp")
        return {"remote_id": mid, "permalink": info.get("permalink")}

    def _wait(self, cid: str, timeout: int = 600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self._get(cid, fields="status_code,status")
            code = st.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise ApiError(f"컨테이너 {code}: {st.get('status')}")
            time.sleep(8)
        raise ApiError("업로드 처리 시간 초과")

    def publishing_limit(self) -> dict:
        return self._get(f"{self.uid}/content_publishing_limit", fields="config,quota_usage")

    def recent_media(self, limit: int = 50) -> list[dict]:
        return self._get(f"{self.uid}/media", fields="id,caption,permalink,timestamp,media_product_type,media_type",
                         limit=limit).get("data", [])

    METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions",
               "ig_reels_avg_watch_time", "profile_visits", "follows"]

    def insights(self, media_id: str) -> dict:
        """지원 안 되는 지표가 섞이면 400 → 하나씩 재시도해서 되는 것만 모은다."""
        try:
            data = self._get(f"{media_id}/insights", metric=",".join(self.METRICS)).get("data", [])
        except ApiError:
            data = []
            for m in self.METRICS:
                try:
                    data += self._get(f"{media_id}/insights", metric=m).get("data", [])
                except ApiError:
                    pass
        raw = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value")) for d in data}
        return {"views": raw.get("views"), "reach": raw.get("reach"), "likes": raw.get("likes"),
                "comments": raw.get("comments"), "saves": raw.get("saved"), "shares": raw.get("shares"),
                "profile_visits": raw.get("profile_visits"), "follows": raw.get("follows"),
                "avg_watch_ms": raw.get("ig_reels_avg_watch_time"), "raw": raw}

    def followers(self) -> int | None:
        return self._get(self.uid, fields="followers_count").get("followers_count")

    def comments(self, media_id: str) -> list[dict]:
        return self._get(f"{media_id}/comments", fields="id,text,username,timestamp").get("data", [])

    def hashtag_top(self, tag: str, limit: int = 50) -> list[dict]:
        """공식 해시태그 검색(7일간 고유 해시태그 30개 한도)."""
        hid = self._get("ig_hashtag_search", user_id=self.uid, q=tag.lstrip("#"))["data"][0]["id"]
        return self._get(f"{hid}/top_media", user_id=self.uid, limit=limit,
                         fields="id,caption,media_type,media_product_type,like_count,comments_count,permalink,timestamp").get("data", [])


# ------------------------------------------------------------------ Threads
class Threads:
    def __init__(self):
        a = settings()["api"]
        self.base = f"{a['threads_base']}/{a['threads_version']}"
        self.uid = env("THREADS_USER_ID", required=True)
        self.token = env("THREADS_ACCESS_TOKEN", required=True)

    def _get(self, path, **params):
        params["access_token"] = self.token
        return _check(requests.get(f"{self.base}/{path}", params=params, timeout=60))

    def _post(self, path, **data):
        data["access_token"] = self.token
        return _check(requests.post(f"{self.base}/{path}", data=data, timeout=120))

    def _create_and_publish(self, **data) -> str:
        c = self._post(f"{self.uid}/threads", **data)
        cid = c["id"]
        t0 = time.time()
        while time.time() - t0 < 600:
            st = self._get(cid, fields="status,error_message")
            if st.get("status") == "FINISHED":
                break
            if st.get("status") in ("ERROR", "EXPIRED"):
                raise ApiError(f"스레드 컨테이너 {st}")
            time.sleep(5 if data.get("media_type") == "VIDEO" else 2)
        return self._post(f"{self.uid}/threads_publish", creation_id=cid)["id"]

    def publish(self, text: str, video_url: str | None = None, reply: str | None = None) -> dict:
        if video_url:
            pid = self._create_and_publish(media_type="VIDEO", video_url=video_url, text=text)
        else:
            pid = self._create_and_publish(media_type="TEXT", text=text)
        rid = None
        if reply:
            time.sleep(3)
            rid = self._create_and_publish(media_type="TEXT", text=reply, reply_to_id=pid)
        info = self._get(pid, fields="permalink,timestamp")
        return {"remote_id": pid, "reply_remote_id": rid, "permalink": info.get("permalink")}

    def recent(self, limit: int = 50) -> list[dict]:
        return self._get(f"{self.uid}/threads", fields="id,text,permalink,timestamp,media_type", limit=limit).get("data", [])

    def insights(self, media_id: str) -> dict:
        data = self._get(f"{media_id}/insights", metric="views,likes,replies,reposts,quotes,shares").get("data", [])
        raw = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value")) for d in data}
        return {"views": raw.get("views"), "likes": raw.get("likes"), "replies": raw.get("replies"),
                "reposts": raw.get("reposts"), "quotes": raw.get("quotes"), "shares": raw.get("shares"), "raw": raw}

    def user_insights(self) -> dict:
        data = self._get(f"{self.uid}/threads_insights", metric="views,likes,replies,reposts,quotes,followers_count").get("data", [])
        return {d["name"]: d.get("total_value", {}).get("value", (d.get("values") or [{}])[-1].get("value")) for d in data}

    def replies(self, media_id: str) -> list[dict]:
        return self._get(f"{media_id}/replies", fields="id,text,username,timestamp").get("data", [])

    def keyword_search(self, q: str, limit: int = 50) -> list[dict]:
        """공개 게시물 키워드 검색(TOP). threads_keyword_search 권한 필요."""
        return self._get("keyword_search", q=q, search_type="TOP", limit=limit,
                         fields="id,text,permalink,timestamp,username,media_type").get("data", [])


def abs_video(rel: str) -> Path:
    p = ROOT / rel
    if not p.exists():
        raise ApiError(f"영상 없음: {rel} (render 먼저)")
    return p
