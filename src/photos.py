"""사진 폴더에서 이번 글에 맞는 사진을 고르고, 다 쓴 폴더는 '사용완료'로 옮긴다.

폴더 규칙 (사장님이 지킬 것):
  PHOTO_DIR/
  ├─ 2026-10-01_수성구_보관이사/   ← 날짜_지역_작업종류 (폴더 이름만 규칙대로)
  │   ├─ IMG_1234.jpg             ← 사진 파일 이름은 아무거나 괜찮다. AI가 사진을 보고 무슨 사진인지 알아낸다.
  │   └─ ...
  ├─ 공용/                         ← 어느 글에나 쓸 수 있는 회사 사진 (맞는 현장 폴더가 없을 때 사용)
  └─ 사용완료/                     ← 다 쓴 폴더는 프로그램이 여기로 옮긴다
"""
import base64
import io
import json
import logging
import random
import shutil

from PIL import Image, ImageOps

try:  # 아이폰 사진(.heic)도 열 수 있게
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from config import MODEL, OUTPUT_DIR, PHOTO_DIR

log = logging.getLogger(__name__)

USED_DIR_NAME = "사용완료"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_PHOTOS = 10
MAX_WIDTH = 1600
DESC_FILE = "_사진설명.json"  # AI가 본 사진 설명을 폴더 안에 저장해 두고 다시 쓴다 (비용 절약)
DESC_SCHEMA = {
    "type": "object",
    "properties": {
        "photos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "description": {"type": "string"},
                    "usable": {"type": "boolean"},
                },
                "required": ["file", "description", "usable"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["photos"],
    "additionalProperties": False,
}


def _folder_info(folder):
    parts = folder.name.split("_")
    return {
        "folder": folder,
        "region": parts[1] if len(parts) >= 3 else "",
        "kind": parts[2] if len(parts) >= 3 else "",
    }


# 폴더 작업종류 이름이 어느 서비스 묶음인지 알아보는 말들 (topics.md 섹션 이름 맨 앞 단어와 같다)
SERVICE_WORDS = {
    "보관이사": ["보관", "창고"],
    "포장이사": ["포장", "가정", "일반이사", "원룸", "아파트", "반포장"],
    "기업이사": ["사무실", "관공서", "공공기관", "청사", "기관", "기업", "학원", "병원", "학교", "회사"],
    "이전설치": ["이전설치", "침대", "에어컨", "가구", "헹거", "행거", "분해", "조립"],
}
SHARED_DIR_NAME = "공용"  # 어느 글에나 쓸 수 있는 회사 사진 (창고 전경, 차량, 작업 모습)
SHARED_COUNT = 4


def _group(text):
    for group, words in SERVICE_WORDS.items():
        if any(w in text for w in words):
            return group
    return None


def _matches(kind, topic):
    """폴더 작업종류(보관이사, 사무실이사, 관공서이전 ...)가 주제와 맞는지."""
    if not kind:
        return False
    text = topic["topic"] + topic["keyword"] + topic["section"]
    short = kind.replace("이사", "")  # '보관이사' 폴더는 '실내보관' 주제와도 맞게
    if kind in text or (len(short) >= 2 and short in text):
        return True
    # 서비스 묶음으로 비교: '관공서이전' 폴더는 '기업이사' 주제와 맞는다
    topic_group = topic["section"].split(" ")[0] if topic.get("section") else None
    return topic_group in SERVICE_WORDS and _group(kind) == topic_group


def _images(folder):
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def pick(topic):
    """주제에 맞는 안 쓴 현장 폴더를 고른다.
    없으면 '공용' 폴더에서 몇 장을 고른다. 그것도 없으면 None (아무 사진이나 넣지 않음)."""
    if not PHOTO_DIR.is_dir():
        log.info("사진 폴더를 찾지 못했어요: %s (.env의 PHOTO_DIR 확인)", PHOTO_DIR)
        return None
    folders = sorted(
        f for f in PHOTO_DIR.iterdir()
        if f.is_dir() and f.name not in (USED_DIR_NAME, SHARED_DIR_NAME)
    )
    for folder in folders:  # 날짜가 이름 앞에 있어서 오래된 폴더부터
        info = _folder_info(folder)
        if not _matches(info["kind"], topic):
            continue
        files = _images(folder)
        if files:
            return {**info, "files": files[:MAX_PHOTOS]}

    names = ", ".join(f.name for f in folders) or "없음"
    log.info("이번 주제(%s)에 맞는 현장 사진 폴더가 없어요. 지금 있는 폴더: %s", topic["topic"], names)
    shared = PHOTO_DIR / SHARED_DIR_NAME
    if shared.is_dir() and _images(shared):
        files = random.sample(_images(shared), min(SHARED_COUNT, len(_images(shared))))
        log.info("공용 사진 폴더에서 %s장을 씁니다.", len(files))
        return {"folder": shared, "region": "", "kind": "회사 사진", "files": files, "shared": True}
    return None


def _thumbnail_b64(path, width=800):
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")  # 휴대폰 사진 회전 정보 반영
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)))
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=80)
    return base64.standard_b64encode(buffer.getvalue()).decode()


def _ask_ai(folder, files):
    """AI가 사진을 보고 한 줄 설명과 사용 가능 여부를 돌려준다."""
    import anthropic

    content = []
    for path in files:
        content.append({"type": "text", "text": f"사진 파일: {path.name}"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": _thumbnail_b64(path)}})
    content.append({"type": "text", "text": (
        f"이사 회사 블로그에 쓸 현장 사진이다. 폴더 이름: {folder.name}\n"
        "각 사진에 무엇이 보이는지 한국어 한 문장(25자 안팎)으로 설명한다. 보이는 것만 쓰고 추측하지 않는다.\n"
        "사람 얼굴, 차량 번호판, 집 호수나 주소, 고객 이름이 알아볼 수 있게 보이거나, "
        "흔들려서 알아볼 수 없거나, 이사와 관계없는 사진이면 usable을 false로 한다."
    )})
    client = anthropic.Anthropic(max_retries=3)
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": DESC_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    return {p["file"]: p for p in json.loads(text)["photos"]}


def add_descriptions(photo_set):
    """사진마다 AI 설명을 붙이고, 쓰면 안 되는 사진(개인정보 등)은 뺀다. 한 번 본 사진은 다시 묻지 않는다."""
    if not photo_set:
        return photo_set
    cache_path = photo_set["folder"] / DESC_FILE
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    new = [p for p in photo_set["files"] if p.name not in cache]
    if new:
        log.info("AI가 사진 %s장을 보고 있어요...", len(new))
        try:
            cache.update(_ask_ai(photo_set["folder"], new))
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # 실패해도 사진 이름만으로 계속한다
            log.warning("사진 설명을 만들지 못했어요: %s", e)
    skipped = [p.name for p in photo_set["files"] if not cache.get(p.name, {}).get("usable", True)]
    if skipped:
        log.info("개인정보가 보이거나 쓰기 어려운 사진은 뺐어요: %s", ", ".join(skipped))
    files = [p for p in photo_set["files"] if p.name not in skipped]
    if not files:
        return None
    return {**photo_set, "files": files,
            "descriptions": {name: c["description"] for name, c in cache.items()}}


def describe(photo_set):
    """AI에게 알려줄 사진 목록 글."""
    if not photo_set:
        return "(이번 글은 사진 없음. [사진:...] 표시를 쓰지 않는다.)"
    descriptions = photo_set.get("descriptions", {})
    lines = [
        f"폴더: {photo_set['folder'].name} (지역: {photo_set['region']}, 작업: {photo_set['kind']})"
    ]
    lines += [
        f"- {p.name}" + (f": {descriptions[p.name]}" if p.name in descriptions else "")
        for p in photo_set["files"]
    ]
    return "\n".join(lines)


def prepare_upload(path):
    """가로가 1600px보다 크면 줄인 복사본을 만들어 그 경로를 돌려준다. 원본은 건드리지 않는다."""
    with Image.open(path) as img:
        if img.width <= MAX_WIDTH and path.suffix.lower() != ".heic":
            return path
        upload_dir = OUTPUT_DIR / "_upload"
        upload_dir.mkdir(exist_ok=True)
        img = ImageOps.exif_transpose(img)  # 휴대폰 사진 회전 정보 반영 (안 하면 옆으로 누워서 올라간다)
        width = min(img.width, MAX_WIDTH)
        height = round(img.height * width / img.width)
        resized = img.convert("RGB").resize((width, height), Image.LANCZOS)
        target = upload_dir / (path.stem + ".jpg")
        resized.save(target, "JPEG", quality=90)
        return target


def mark_used(photo_set):
    if not photo_set or photo_set.get("shared"):  # 공용 사진은 계속 다시 쓴다
        return
    used_dir = PHOTO_DIR / USED_DIR_NAME
    used_dir.mkdir(exist_ok=True)
    shutil.move(str(photo_set["folder"]), str(used_dir / photo_set["folder"].name))
