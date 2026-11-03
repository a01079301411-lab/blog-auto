"""스레드 API 는 video_url(공개 주소)만 받는다 → 영상을 공개 URL 로 만들어 준다.

1) MEDIA_BASE_URL : out/ 폴더를 이미 공개 호스팅 중이면 그 주소 + 상대경로
2) S3 호환(Cloudflare R2 등) : boto3 로 업로드 후 S3_PUBLIC_BASE_URL + key
"""
from __future__ import annotations

from pathlib import Path

from ..config import ROOT, env


def public_url(rel_video: str) -> str:
    base = env("MEDIA_BASE_URL")
    if base:
        return base.rstrip("/") + "/" + rel_video.removeprefix("out/")
    if env("S3_BUCKET"):
        try:
            import boto3
        except ImportError:
            raise SystemExit("pip install boto3 필요 (S3/R2 업로드)")
        s3 = boto3.client("s3", endpoint_url=env("S3_ENDPOINT_URL"), aws_access_key_id=env("S3_ACCESS_KEY_ID"),
                          aws_secret_access_key=env("S3_SECRET_ACCESS_KEY"))
        key = "insaengtem/" + Path(rel_video).name
        s3.upload_file(str(ROOT / rel_video), env("S3_BUCKET"), key, ExtraArgs={"ContentType": "video/mp4"})
        return env("S3_PUBLIC_BASE_URL", required=True).rstrip("/") + "/" + key
    raise SystemExit("스레드 영상 게시엔 공개 URL 필요: .env 에 MEDIA_BASE_URL 또는 S3_* 설정 "
                     "(또는 publish_mode.threads='web' 으로 브라우저 업로드)")
