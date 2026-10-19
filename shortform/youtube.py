"""유튜브 쇼츠 업로드 (YouTube Data API).

처음 한 번은 구글 클라우드에서 만든 client_secret.json이 프로그램 폴더에 있어야 하고,
브라우저에서 구글 계정으로 로그인해 허용하면 youtube_token.json에 저장되어 다음부터는
자동으로 올라간다. 설정 방법은 README의 "유튜브 자동 업로드"를 참고.
"""
from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_SECRET = os.path.join(ROOT, "client_secret.json")
TOKEN = os.path.join(ROOT, "youtube_token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not os.path.exists(CLIENT_SECRET):
        raise RuntimeError(
            "유튜브 업로드에 필요한 client_secret.json이 없어요. "
            "README의 '유튜브 자동 업로드' 설정을 먼저 해 주세요.")
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("  브라우저가 열리면 유튜브 채널의 구글 계정으로 로그인하고 '허용'을 눌러 주세요.")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def plain_title(title: str) -> str:
    """'사장님 속터지는\\n{진상 직원}의 한마디' → '사장님 속터지는 진상 직원의 한마디'"""
    return re.sub(r"\s+", " ", title.replace("{", "").replace("}", "").replace("\n", " ")).strip()


def upload(video: str, *, title: str, description: str, privacy: str = "private",
           thumbnail: str | None = None) -> str:
    """영상을 올리고 영상 주소를 돌려준다."""
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    title = plain_title(title)
    if "#shorts" not in title.lower() and len(title) <= 90:
        title += " #shorts"
    tags = re.findall(r"#(\w+)", description)
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": tags[:15], "categoryId": "22"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video, chunksize=8 * 1024 * 1024,
                                                        resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"\r  업로드 중... {int(status.progress() * 100)}%", end="", flush=True)
    print()
    vid = resp["id"]
    if thumbnail and os.path.exists(thumbnail):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumbnail)).execute()
        except Exception as e:  # 채널 인증 전에는 썸네일 설정이 막혀 있다
            print(f"  (썸네일은 올리지 못했어요: 채널 전화번호 인증이 필요할 수 있어요. {e})")
    return f"https://youtube.com/shorts/{vid}"


READ_TOKEN = os.path.join(ROOT, "youtube_read_token.json")
READ_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def statistics(video_ids: list[str]) -> dict[str, dict]:
    """영상들의 조회수·좋아요 ({영상ID: {"viewCount": "123", ...}}). 처음 한 번 로그인 필요."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(READ_TOKEN):
        creds = Credentials.from_authorized_user_file(READ_TOKEN, READ_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("  조회수를 가져오려면 브라우저에서 유튜브 계정으로 한 번 허용해 주세요.")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, READ_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(READ_TOKEN, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    yt = build("youtube", "v3", credentials=creds)
    out = {}
    for i in range(0, len(video_ids), 50):
        resp = yt.videos().list(part="statistics", id=",".join(video_ids[i:i + 50])).execute()
        for item in resp.get("items", []):
            out[item["id"]] = item.get("statistics", {})
    return out
