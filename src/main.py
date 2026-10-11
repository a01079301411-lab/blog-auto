"""전체 실행: 주제 고르기 → 사진 고르기 → AI 글쓰기 → 품질 검사 → 줄바꿈 → 미리보기 저장
           → 네이버에 입력 → 임시저장(AUTO_PUBLISH=false) 또는 발행(true) → 기록·알림

사용법
  python src/main.py --preview          글만 만들어 output 폴더에 저장 (네이버에는 안 올림)
  python src/main.py                    지금 바로 실행
  python src/main.py --schedule         발행 시간대(08:30~11:30) 안의 무작위 시각까지 기다렸다 실행
  python src/main.py --topic 장마철     특정 주제로 쓰기 (topics.md의 주제·키워드 일부 글자)
"""
import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import checker
import formatter
import generator
import history
import links
import notifier
import photos
import publisher
import topics
from config import (
    ANTHROPIC_API_KEY, AUTO_PUBLISH, BLOG_ID, COMPANY_PHONE, DAILY_LIMIT, LOGS_DIR,
    OUTPUT_DIR, PUBLISH_WINDOW_END, PUBLISH_WINDOW_START,
)

log = logging.getLogger("main")

# 올리다가 실패한 글. 다음 실행 때 AI를 다시 부르지 않고 이 글을 다시 올린다.
PENDING_FILE = OUTPUT_DIR / "pending.json"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8"),
        ],
    )
    # AI 연결 라이브러리의 기술 메시지(HTTP Request ...)는 숨긴다
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def keep_awake():
    """노트북이 프로그램 도중에 절전 모드로 들어가지 않게 한다. (윈도우 전용, 프로그램이 끝나면 자동 해제)"""
    if sys.platform != "win32":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def stop(message):
    notifier.notify(f"[블로그 자동화] 중단: {message}")
    sys.exit(1)


def wait_for_window():
    """오늘 발행 시간대 안의 무작위 시각까지 기다린다. 이미 지났으면 바로 실행."""
    today = datetime.now().strftime("%Y-%m-%d")
    start = datetime.strptime(f"{today} {PUBLISH_WINDOW_START}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{today} {PUBLISH_WINDOW_END}", "%Y-%m-%d %H:%M")
    now = datetime.now()
    if now >= end:
        return
    target = datetime.fromtimestamp(random.uniform(max(start, now).timestamp(), end.timestamp()))
    log.info("%s 까지 기다렸다가 실행합니다.", target.strftime("%H:%M"))
    time.sleep(max(0, (target - datetime.now()).total_seconds()))


def write_with_check(topic, photo_set, related):
    """글을 만들고 검사한다. 떨어지면 이유를 알려주고 1번 다시 쓴다."""
    post = generator.generate(topic, photo_set, related)
    fails = checker.check(post, topic, photo_set, related)
    if fails:
        log.info("품질 검사 실패, 다시 씁니다:\n- %s", "\n- ".join(fails))
        post = generator.generate(topic, photo_set, related, feedback=fails)
        fails = checker.check(post, topic, photo_set, related)
    return post, fails


def check_login():
    """화면 없이 몇 초 만에 로그인 상태만 확인한다."""
    with publisher.open_browser(headless=True) as page:
        return publisher.is_logged_in(page)


def save_pending(topic, photo_set, related, post, blocks):
    data = {
        "topic": topic, "related": related, "post": post, "blocks": blocks,
        "photo_set": None if not photo_set else {
            "folder": str(photo_set["folder"]), "region": photo_set["region"],
            "kind": photo_set["kind"], "files": [str(f) for f in photo_set["files"]],
            "shared": bool(photo_set.get("shared")),
        },
    }
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending():
    """올리지 못한 글이 있으면 (topic, photo_set, related, post, blocks)를 돌려준다."""
    if not PENDING_FILE.exists():
        return None
    data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    photo_set = data["photo_set"]
    if photo_set:
        photo_set = {**photo_set, "folder": Path(photo_set["folder"]),
                     "files": [Path(f) for f in photo_set["files"]]}
        if not all(f.exists() for f in photo_set["files"]):
            photo_set = None  # 사진이 옮겨졌으면 사진 없이 올린다
    topic, related, post = data["topic"], data["related"], data["post"]
    # 프로그램이 바뀌었을 수 있으니 지금 규칙으로 다시 정리하고 검사한다
    fails = checker.check(post, topic, photo_set, related)
    if fails:
        log.info("저장해 둔 글이 지금 기준에 맞지 않아 새로 씁니다:\n- %s", "\n- ".join(fails))
        PENDING_FILE.unlink(missing_ok=True)
        return None
    return topic, photo_set, related, post, formatter.format_body(post["body"], related)


def make_post(topic, photo_set, related):
    """글을 만들고 검사한 뒤 미리보기를 저장한다. 검사를 통과하지 못하면 멈춘다."""
    try:
        post, fails = write_with_check(topic, photo_set, related)
    except Exception as e:
        stop(f"AI 글쓰기 실패: {e}")
    blocks = formatter.format_body(post["body"], related)
    preview_path = save_preview(post, topic, blocks, fails)
    log.info("미리보기 저장: %s", preview_path)
    if fails:
        stop("품질 검사를 2번 통과하지 못했어요. 미리보기 파일을 확인해 주세요: " + preview_path.name)
    return post, blocks


def save_preview(post, topic, blocks, fails):
    path = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d_%H%M}_{topic['topic'].replace(' ', '')}.md"
    check_text = "통과" if not fails else "실패\n" + "\n".join(f"- {f}" for f in fails)
    path.write_text(
        f"# {post['title']}\n\n"
        f"주제: {topic['topic']} / 키워드: {topic['keyword']} / 카테고리: {topic['category'] or '기본'} / "
        f"제목 유형: {topic['title_type']} / 도입: {topic['hook_type']} / 구조: {topic['variant']}\n"
        f"품질 검사: {check_text}\n"
        f"사용한 회사 팩트: {', '.join(post['used_facts'])}\n"
        f"태그: {' '.join('#' + t for t in post['tags'])}\n\n"
        "=============== 블로그에 올라갈 모습 ===============\n\n"
        f"{formatter.preview(blocks, post['photo_captions'])}\n\n"
        "=============== AI가 쓴 원본 ===============\n\n"
        f"{post['body']}\n",
        encoding="utf-8",
    )
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="글만 만들고 네이버에는 올리지 않음")
    parser.add_argument("--schedule", action="store_true", help="발행 시간대 안 무작위 시각에 실행")
    parser.add_argument("--topic", help="특정 주제로 쓰기")
    args = parser.parse_args()
    setup_logging()
    keep_awake()

    if not ANTHROPIC_API_KEY:
        stop(".env에 ANTHROPIC_API_KEY가 없어요.")
    if not COMPANY_PHONE:
        stop(".env에 COMPANY_PHONE(회사 전화번호)이 없어요.")
    if not args.preview and not BLOG_ID:
        stop(".env에 BLOG_ID가 없어요.")

    if not args.preview:
        done_today = history.count_today(history.load())
        if done_today >= DAILY_LIMIT:
            if args.schedule:  # 자동 실행은 하루 개수 제한을 지킨다
                log.info("오늘은 이미 %s개를 올렸어요. (하루 최대 %s개)", done_today, DAILY_LIMIT)
                return
            # 사장님이 직접 실행할 때는 막지 않고 알려만 준다
            log.info("참고: 오늘 %s개째 글이에요. (자동 실행은 하루 %s개까지)", done_today + 1, DAILY_LIMIT)
        if args.schedule:
            wait_for_window()

    if not args.preview and not check_login():
        stop("네이버 로그인이 풀렸어요. 1_네이버로그인.bat 을 실행해 주세요.")

    pending = None if args.preview else load_pending()
    if pending:
        topic, photo_set, related, post, blocks = pending
        log.info("지난번에 올리지 못한 글을 다시 올립니다: %s", post["title"])
    else:
        topic = topics.pick(args.topic)
        log.info("주제: %s / 키워드: %s / %s / %s / 구조 %s", topic["topic"], topic["keyword"],
                 topic["title_type"], topic["hook_type"], topic["variant"])
        photo_set = photos.add_descriptions(photos.pick(topic))
        log.info("사진: %s", f"{photo_set['folder'].name} ({len(photo_set['files'])}장)" if photo_set else "없음")
        related = links.related(topic)
        log.info("내부링크 후보: %s개", len(related))
        post, blocks = make_post(topic, photo_set, related)
        if args.preview:
            log.info("미리보기만 만들었어요. 위 파일을 열어 확인해 주세요.")
            return
        save_pending(topic, photo_set, related, post, blocks)

    log.info("크롬을 열어 네이버에 입력합니다. 끝날 때까지 크롬 창 안을 클릭하지 마세요.")
    photo_paths = {p.name: photos.prepare_upload(p) for p in photo_set["files"]} if photo_set else {}
    try:
        with publisher.open_browser() as page:
            try:
                result = publisher.post(
                    page, post["title"], blocks, post["tags"],
                    photo_paths, post["photo_captions"], publish=AUTO_PUBLISH, category=topic["category"],
                )
            except publisher.PublishError as e:
                stop(f"{e}\n다시 실행하면 이 글을 그대로 다시 올립니다.")
            except Exception as e:
                shot = publisher.screenshot(page, "error")
                log.error("예상하지 못한 오류: %r", e)
                where = f" 그때 화면: {shot}" if shot else ""
                stop(f"네이버에 입력하다 멈췄어요. 크롬 창이 닫혔거나 화면이 바뀌었을 수 있어요.{where}"
                     "\n다시 실행하면 이 글을 그대로 다시 올립니다.")
    except SystemExit:
        raise
    except Exception as e:
        log.error("예상하지 못한 오류: %r", e)
        stop("크롬을 열거나 닫다가 문제가 생겼어요. 다시 실행하면 이 글을 그대로 다시 올립니다.")
    PENDING_FILE.unlink(missing_ok=True)

    history.add({
        "topic": topic["topic"], "keyword": topic["keyword"], "title": post["title"],
        "title_type": topic["title_type"], "hook_type": topic["hook_type"], "variant": topic["variant"],
        "opening": formatter.opening(blocks),
        "result": result["result"], "url": result["url"],
        "photo_folder": photo_set["folder"].name if photo_set else "",
    })
    photos.mark_used(photo_set)

    done = "발행 완료" if result["result"] == "published" else "임시저장 완료 (검수 대기)"
    message = f"[블로그 자동화] {done}\n제목: {post['title']}\n{result['url']}"
    if result["warnings"]:
        message += "\n주의: " + " / ".join(result["warnings"])
    notifier.notify(message)


if __name__ == "__main__":
    main()
