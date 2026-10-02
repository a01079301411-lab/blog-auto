"""사진 폴더에서 이번 글에 맞는 사진을 고르고, 다 쓴 폴더는 '사용완료'로 옮긴다.

폴더 규칙 (사장님이 지킬 것):
  PHOTO_DIR/
  ├─ 2026-10-01_수성구_보관이사/   ← 날짜_지역_작업종류
  │   ├─ 창고_01.jpg              ← 파일 이름 앞 단어: 창고, 제습기, 적재, 포장 ...
  │   └─ ...
  └─ 사용완료/
"""
import shutil

from PIL import Image

from config import OUTPUT_DIR, PHOTO_DIR

USED_DIR_NAME = "사용완료"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS = 10
MAX_WIDTH = 1600


def _folder_info(folder):
    parts = folder.name.split("_")
    return {
        "folder": folder,
        "region": parts[1] if len(parts) >= 3 else "",
        "kind": parts[2] if len(parts) >= 3 else "",
    }


def _matches(kind, topic):
    """폴더 작업종류(보관이사, 포장이사, 이전설치 ...)가 주제와 맞는지."""
    if not kind:
        return False
    text = topic["topic"] + topic["keyword"] + topic["section"]
    short = kind.replace("이사", "")  # '보관이사' 폴더는 '실내보관' 주제와도 맞게
    return kind in text or (len(short) >= 2 and short in text)


def pick(topic):
    """주제에 맞는 안 쓴 사진 폴더를 고른다. 맞는 폴더가 없으면 None (아무 사진이나 넣지 않음)."""
    if not PHOTO_DIR.is_dir():
        return None
    folders = sorted(
        f for f in PHOTO_DIR.iterdir() if f.is_dir() and f.name != USED_DIR_NAME
    )
    for folder in folders:  # 날짜가 이름 앞에 있어서 오래된 폴더부터
        info = _folder_info(folder)
        if not _matches(info["kind"], topic):
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if files:
            return {**info, "files": files[:MAX_PHOTOS]}
    return None


def describe(photo_set):
    """AI에게 알려줄 사진 목록 글."""
    if not photo_set:
        return "(이번 글은 사진 없음. [사진:...] 표시를 쓰지 않는다.)"
    lines = [
        f"폴더: {photo_set['folder'].name} (지역: {photo_set['region']}, 작업: {photo_set['kind']})"
    ]
    lines += [f"- {p.name}" for p in photo_set["files"]]
    return "\n".join(lines)


def prepare_upload(path):
    """가로가 1600px보다 크면 줄인 복사본을 만들어 그 경로를 돌려준다. 원본은 건드리지 않는다."""
    with Image.open(path) as img:
        if img.width <= MAX_WIDTH:
            return path
        upload_dir = OUTPUT_DIR / "_upload"
        upload_dir.mkdir(exist_ok=True)
        height = round(img.height * MAX_WIDTH / img.width)
        resized = img.convert("RGB").resize((MAX_WIDTH, height), Image.LANCZOS)
        target = upload_dir / (path.stem + ".jpg")
        resized.save(target, "JPEG", quality=90)
        return target


def mark_used(photo_set):
    if not photo_set:
        return
    used_dir = PHOTO_DIR / USED_DIR_NAME
    used_dir.mkdir(exist_ok=True)
    shutil.move(str(photo_set["folder"]), str(used_dir / photo_set["folder"].name))
