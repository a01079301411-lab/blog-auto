"""대문(타이틀) 사진 만들기: 사진을 밝고 선명하게 다듬고 네이버 블로그 타이틀 크기로 자른다.

사용: python src\\banner.py "사진 경로"   (확장자는 빼도 된다)
결과: 같은 폴더에 대문_위.jpg, 대문_가운데.jpg, 대문_아래.jpg (자르는 위치만 다름), 대문_보정원본.jpg
- 네이버 PC 타이틀 사진은 가로 966px, 세로 50~600px. 여기서는 966 x 400 으로 만든다.
- 원본은 건드리지 않는다.
"""
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

TITLE_SIZE = (966, 400)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp")


def find(path):
    """확장자 없이 줘도 찾는다."""
    path = Path(str(path).strip().strip('"'))
    if path.is_file():
        return path
    for ext in IMAGE_EXTS:
        for candidate in (path.with_name(path.name + ext), path.with_name(path.name + ext.upper())):
            if candidate.is_file():
                return candidate
    matches = sorted(p for p in path.parent.glob(path.name + "*") if p.suffix.lower() in IMAGE_EXTS)
    return matches[0] if matches else None


def clean(image):
    """밝기, 대비, 색, 선명도를 자연스럽게 다듬는다 (카톡으로 받은 흐린 사진 기준)."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    # 색이 한쪽으로 쏠린 사진(노란 조명 등)을 살짝 바로잡는다
    r, g, b = ImageStat.Stat(image).mean
    gray = (r + g + b) / 3
    channels = [ch.point(lambda v, k=min(1.15, max(0.87, gray / max(m, 1))): min(255, int(v * (1 + (k - 1) * 0.6))))
                for ch, m in zip(image.split(), (r, g, b))]
    image = Image.merge("RGB", channels)
    image = ImageOps.autocontrast(image, cutoff=1)
    light = ImageStat.Stat(image.convert("L")).mean[0]
    if light < 125:
        image = ImageEnhance.Brightness(image).enhance(min(1.3, 135 / max(light, 1)))
    image = ImageEnhance.Color(image).enhance(1.12)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=3))
    return image


def crops(image, size=TITLE_SIZE):
    """가로세로 비율을 맞춰 위, 가운데, 아래 세 가지로 자른다."""
    width, height = image.size
    want = size[0] / size[1]
    results = {}
    if width / height > want:  # 옆으로 긴 사진: 가로를 자른다 (왼쪽, 가운데, 오른쪽)
        new_w = int(height * want)
        spots = {"왼쪽": 0, "가운데": (width - new_w) // 2, "오른쪽": width - new_w}
        for name, x in spots.items():
            results[name] = image.crop((x, 0, x + new_w, height)).resize(size, Image.LANCZOS)
    else:
        new_h = int(width / want)
        spots = {"위": 0, "가운데": (height - new_h) // 2, "아래": height - new_h}
        for name, y in spots.items():
            results[name] = image.crop((0, y, width, y + new_h)).resize(size, Image.LANCZOS)
    return results


def make(path):
    """보정하고 잘라서 저장한다. 만든 파일 목록을 돌려준다 (첫 번째가 보정 원본)."""
    source = find(path)
    if source is None:
        raise FileNotFoundError(f"사진을 찾지 못했어요: {path}")
    image = clean(Image.open(source))
    made = []
    full = source.with_name("대문_보정원본.jpg")
    image.save(full, quality=93)
    made.append(full)
    for name, cropped in crops(image).items():
        out = source.with_name(f"대문_{name}.jpg")
        cropped.save(out, quality=93)
        made.append(out)
    return made


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('사용법: python src\\banner.py "사진 경로"')
        sys.exit(1)
    for made_file in make(sys.argv[1]):
        print(made_file)
