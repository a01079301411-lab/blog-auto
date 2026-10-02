"""전체 실행: 주제 고르기 → 사진 고르기 → AI 글쓰기 → 품질 검사 → 줄바꿈 → 미리보기 저장
           → 네이버에 입력 → 임시저장(AUTO_PUBLISH=false) 또는 발행(true) → 기록·알림

사용법
  python src/main.py --preview          글만 만들어 output 폴더에 저장 (네이버에는 안 올림)
  python src/main.py                    지금 바로 실행
  python src/main.py --schedule         발행 시간대(08:30~11:30) 안의 무작위 시각까지 기다렸다 실행
  python src/main.py --topic 장마철     특정 주제로 쓰기 (topics.md의 주제·키워드 일부 글자)
"""
import argparse
import logging
import random
import sys
import time
from datetime import datetime

import checker
import formatter
import generator
import history
import notifier
import photos
import publisher
import topics
from config import (
    ANTHROPIC_API_KEY, AUTO_PUBLISH, BLOG_ID, COMPANY_PHONE, DAILY_LIMIT, LOGS_DIR,
    OUTPUT_DIR, PUBLISH_WINDOW_END, PUBLISH_WINDOW_START,
)

log = logging.getLogger("main")


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


def write_with_check(topic, photo_set):
    """글을 만들고 검사한다. 떨어지면 이유를 알려주고 1번 다시 쓴다."""
    post = generator.generate(topic, photo_set)
    fails = checker.check(post, topic, photo_set)
    if fails:
        log.info("품질 검사 실패, 다시 씁니다:\n- %s", "\n- ".join(fails))
        post = generator.generate(topic, photo_set, feedback=fails)
        fails = checker.check(post, topic, photo_set)
    return post, fails


def save_preview(post, topic, blocks, fails):
    path = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d_%H%M}_{topic['topic'].replace(' ', '')}.md"
    check_text = "통과" if not fails else "실패\n" + "\n".join(f"- {f}" for f in fails)
    path.write_text(
        f"# {post['title']}\n\n"
        f"주제: {topic['topic']} / 키워드: {topic['keyword']} / "
        f"제목 유형: {topic['title_type']} / 구조: {topic['variant']}\n"
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

    if not ANTHROPIC_API_KEY:
        stop(".env에 ANTHROPIC_API_KEY가 없어요.")
    if not COMPANY_PHONE:
        stop(".env에 COMPANY_PHONE(회사 전화번호)이 없어요.")
    if not args.preview and not BLOG_ID:
        stop(".env에 BLOG_ID가 없어요.")

    if not args.preview:
        done_today = history.count_today(history.load())
        if done_today >= DAILY_LIMIT:
            log.info("오늘은 이미 %s개를 올렸어요. (하루 최대 %s개)", done_today, DAILY_LIMIT)
            return
        if args.schedule:
            wait_for_window()

    topic = topics.pick(args.topic)
    log.info("주제: %s / 키워드: %s / %s / 구조 %s",
             topic["topic"], topic["keyword"], topic["title_type"], topic["variant"])
    photo_set = photos.pick(topic)
    log.info("사진: %s", f"{photo_set['folder'].name} ({len(photo_set['files'])}장)" if photo_set else "없음")

    try:
        post, fails = write_with_check(topic, photo_set)
    except Exception as e:
        stop(f"AI 글쓰기 실패: {e}")
    blocks = formatter.format_body(post["body"])
    preview_path = save_preview(post, topic, blocks, fails)
    log.info("미리보기 저장: %s", preview_path)
    if fails:
        stop("품질 검사를 2번 통과하지 못했어요. 미리보기 파일을 확인해 주세요: " + preview_path.name)
    if args.preview:
        log.info("미리보기만 만들었어요. 위 파일을 열어 확인해 주세요.")
        return

    photo_paths = {p.name: photos.prepare_upload(p) for p in photo_set["files"]} if photo_set else {}
    with publisher.open_browser() as page:
        if not publisher.is_logged_in(page):
            stop("네이버 로그인이 풀렸어요. 1_네이버로그인.bat 을 실행해 주세요.")
        try:
            result = publisher.post(
                page, post["title"], blocks, post["tags"],
                photo_paths, post["photo_captions"], publish=AUTO_PUBLISH,
            )
        except publisher.PublishError as e:
            stop(str(e))

    history.add({
        "topic": topic["topic"], "keyword": topic["keyword"], "title": post["title"],
        "title_type": topic["title_type"], "variant": topic["variant"],
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
