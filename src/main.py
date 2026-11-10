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
import re
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
import reviewer
import topics
from config import (
    ANTHROPIC_API_KEY, AUTO_PUBLISH, BLOG_ID, COMPANY_PHONE, DAILY_LIMIT, LOGS_DIR,
    OUTPUT_DIR, PHOTO_DIR, PUBLISH_WINDOW_END, PUBLISH_WINDOW_START,
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
    """글을 만들고 규칙 검사 + AI 편집장 검토를 한다. 고칠 게 있으면 이유를 알려주고 1번 다시 쓴다.

    돌려주는 것: (글, 규칙 검사 실패 목록, AI 검토 메모 목록)
    규칙 검사 실패 중 [권장]이 아닌 것만 발행을 멈추고, 다시 쓴 뒤의 AI 검토 메모는 미리보기와 알림에만 남긴다.
    """
    post = generator.generate(topic, photo_set, related)
    fails = checker.check(post, topic, photo_set, related)
    # 발행을 막는 규칙 실패가 없는 글만 AI가 본다
    issues = [] if checker.hard_fails(fails) else reviewer.review(post, topic)
    must = [i for i in issues if i["must_fix"]]
    if issues:
        log.info("AI 검토:\n- %s", "\n- ".join(reviewer.as_feedback(issues)))
    # 다시 쓰기는 발행을 막는 문제나 편집장이 꼭 고치라는 문제가 있을 때만 한다.
    # (권장 기준까지 다 고치게 하면 글이 누더기처럼 어색해진다)
    # 분량(2,000자에서 2,500자)이 벗어난 것도 다시 쓴다. 다시 써도 벗어나면 그대로 발행은 한다.
    length = [f for f in fails if f.startswith(checker.SOFT + "본문이")]
    redo = checker.rewrite_fails(fails)
    if redo or must or length:
        feedback = redo + length + reviewer.as_feedback(must)
        log.info("고칠 점이 있어 다시 씁니다:\n- %s", "\n- ".join(feedback))
        first = (post, fails, issues)
        try:
            post = generator.generate(topic, photo_set, related, feedback=feedback)
        except Exception as e:
            if checker.hard_fails(fails):
                raise
            # 다시 쓰기가 실패해도 첫 글이 발행 기준은 통과했으면 첫 글로 간다
            log.info("다시 쓰기에 실패해서 처음 쓴 글로 진행합니다: %s", e)
            return first[0], first[1], reviewer.as_feedback(first[2])
        fails = checker.check(post, topic, photo_set, related)
        issues = reviewer.review(post, topic)
        if issues:
            log.info("다시 쓴 글의 AI 검토 메모:\n- %s", "\n- ".join(reviewer.as_feedback(issues)))
        soft = [f for f in fails if f not in checker.hard_fails(fails)]
        if soft and not checker.hard_fails(fails):
            log.info("권장 기준 일부는 못 맞췄지만 발행에는 문제없어서 진행합니다:\n- %s", "\n- ".join(soft))
    notes = reviewer.as_feedback(issues)
    return post, fails, notes


def check_login():
    """화면 없이 몇 초 만에 로그인 상태만 확인한다."""
    with publisher.open_browser(headless=True) as page:
        return publisher.is_logged_in(page)


def save_pending(topic, photo_set, related, post, blocks, attempted=False):
    """attempted=True: 발행 버튼까지 누를 수 있는 단계에 들어갔다는 표시.
    다음 실행 때 이 글이 이미 블로그에 올라가 있는지 먼저 확인해서, 같은 글이 두 번 올라가지 않게 한다."""
    data = {
        "topic": topic, "related": related, "post": post, "blocks": blocks, "attempted": attempted,
        "photo_set": None if not photo_set else {
            "folder": str(photo_set["folder"]), "region": photo_set["region"],
            "kind": photo_set["kind"], "files": [str(f) for f in photo_set["files"]],
            "shared": bool(photo_set.get("shared")),
        },
    }
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending():
    """올리지 못한 글이 있으면 (topic, photo_set, related, post, blocks, attempted)를 돌려준다."""
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
    fails = checker.hard_fails(checker.check(post, topic, photo_set, related))
    if fails:
        log.info("저장해 둔 글이 지금 기준에 맞지 않아 새로 씁니다:\n- %s", "\n- ".join(fails))
        PENDING_FILE.unlink(missing_ok=True)
        return None
    return (topic, photo_set, related, post, formatter.format_body(post["body"], related),
            bool(data.get("attempted")))


def find_on_blog(title):
    """이 제목의 글이 블로그에 올라가 있으면 그 글 정보, 없으면 False, 블로그를 못 읽으면 None."""
    posts = links.blog_posts()
    if posts is None:
        return None
    want = re.sub(r"\s", "", title)
    return next((p for p in posts if re.sub(r"\s", "", p["title"]) == want), False)


def finish(topic, photo_set, post, blocks, result, note=""):
    """올린 글을 기록하고, 다시 올리지 않게 대기 글을 지우고, 사진 폴더를 정리하고, 알린다."""
    PENDING_FILE.unlink(missing_ok=True)
    history.add({
        "topic": topic["topic"], "keyword": topic["keyword"], "title": post["title"],
        "title_type": topic["title_type"], "hook_type": topic["hook_type"], "variant": topic["variant"],
        "opening": formatter.opening(blocks),
        "result": result["result"], "url": result["url"],
        "photo_folder": photo_set["folder"].name if photo_set else "",
        "facts": post.get("used_facts", []),
        "photos": re.findall(r"\[사진:\s*([^\]]+?)\s*\]", post["body"]),
    })
    try:
        photos.mark_used(photo_set)
    except Exception as e:  # 사진 폴더 정리에 실패해도 글은 이미 올라갔다
        log.warning("사진 폴더를 사용완료로 옮기지 못했어요: %s", e)

    done = "발행 완료" if result["result"] == "published" else "임시저장 완료 (검수 대기)"
    message = f"[블로그 자동화] {done}\n제목: {post['title']}\n{result['url']}"
    if note:
        message += "\n" + note
    if result["warnings"]:
        message += "\n주의: " + " / ".join(result["warnings"])
    if post.get("review_notes"):
        message += "\nAI 편집장 메모: " + " / ".join(post["review_notes"][:3])
    notifier.notify(message)


def make_post(topic, photo_set, related):
    """글을 만들고 검사한 뒤 미리보기를 저장한다. 검사를 통과하지 못하면 멈춘다."""
    try:
        post, fails, notes = write_with_check(topic, photo_set, related)
    except Exception as e:
        stop(f"AI 글쓰기 실패: {e}")
    blocks = formatter.format_body(post["body"], related)
    post["review_notes"] = notes  # 발행 알림에도 남긴다
    preview_path = save_preview(post, topic, blocks, fails, notes)
    log.info("미리보기 저장: %s", preview_path)
    hard = checker.hard_fails(fails)
    if hard:
        stop("품질 검사를 2번 통과하지 못했어요. 미리보기 파일을 확인해 주세요: " + preview_path.name
             + "\n이유:\n- " + "\n- ".join(hard[:3]))
    return post, blocks


def save_preview(post, topic, blocks, fails, notes=None):
    path = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d_%H%M}_{topic['topic'].replace(' ', '')}.md"
    if not fails:
        check_text = "통과"
    else:
        check_text = ("실패" if checker.hard_fails(fails) else "통과 (권장 기준 일부 미달)") + "\n" + \
            "\n".join(f"- {f}" for f in fails)
    if notes:
        check_text += "\nAI 편집장 메모 (발행 전에 한 번 봐 주세요)\n" + "\n".join(f"- {n}" for n in notes)
    else:
        check_text += " / AI 편집장 검토: 고칠 점 없음"
    path.write_text(
        f"# {post['title']}\n\n"
        f"인용구: {post.get('quote', '')}\n\n"
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
    # 나중에 이 글을 다시 입력(고치기)할 때 쓰는 원본
    path.with_suffix(".json").write_text(json.dumps({"post": post, "blocks": blocks}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return path


def _find_saved_post(title):
    """발행한 글을 미리보기 파일에서 찾는다. 없으면 None.
    돌려주는 값: {"blocks", "captions", "quote", "tags", "category"}"""
    for md in sorted(OUTPUT_DIR.glob("*.md"), reverse=True):
        text = md.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith(f"# {title}\n"):
            continue
        tags = re.search(r"^태그: (.*)$", text, re.M)
        category = re.search(r"/ 카테고리: (.*?) / ", text)
        found = {
            "tags": [t.lstrip("#") for t in tags.group(1).split()] if tags else [],
            "category": category.group(1).strip() if category and category.group(1).strip() != "기본" else "",
        }
        sidecar = md.with_suffix(".json")
        if sidecar.exists():
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            post = data["post"]
            # 예전에 만든 블록에도 번호 목록 막기를 다시 적용한다
            return {**found, "blocks": formatter._no_auto_format(data["blocks"]),
                    "captions": post.get("photo_captions", {}), "quote": post.get("quote", ""),
                    "tags": post.get("tags") or found["tags"]}
        quote = re.search(r"^인용구: (.*)$", text, re.M)
        shown = text.split("=============== 블로그에 올라갈 모습 ===============", 1)[-1]
        shown = shown.split("=============== AI가 쓴 원본 ===============", 1)[0].strip("\n")
        blocks, captions = formatter.parse_preview(shown)
        return {**found, "blocks": blocks, "captions": captions, "quote": quote.group(1).strip() if quote else ""}
    return None


def _find_photos(files, folder_name):
    """사진 파일 이름으로 실제 파일을 찾는다. 사용한 사진은 '사용완료' 폴더로 옮겨져 있을 수 있다."""
    found = {}
    folders = [d for d in PHOTO_DIR.rglob(folder_name) if d.is_dir()] if folder_name else []
    for name in files:
        hits = [p for d in folders for p in d.glob(name)] or list(PHOTO_DIR.rglob(name))
        if hits:
            found[name] = photos.prepare_upload(hits[0])
    return found


def fix_last():
    """가장 최근에 발행한 글을 고친 방식으로 새로 발행하고, 예전 글은 삭제한다.
    새 글이 제대로 발행된 것을 확인한 뒤에만 예전 글을 지운다 (발행이 안 되면 예전 글은 그대로)."""
    records = history.load()
    published = [r for r in records
                 if r.get("result") == "published" and re.search(r"/\d{9,}|logNo=\d+", r.get("url", ""))]
    if not published:
        stop("다시 올릴 발행 글을 기록에서 찾지 못했어요.")
    record = published[-1]
    saved = _find_saved_post(record["title"])
    if saved is None:
        stop(f"이 글의 미리보기 파일을 output 폴더에서 찾지 못했어요: {record['title']}")
    blocks = saved["blocks"]
    files = [b["file"] for b in blocks if b["type"] == "photo"]
    photo_paths = _find_photos(files, record.get("photo_folder", ""))
    missing = [f for f in files if f not in photo_paths]
    print(f"\n다시 올릴 글: {record['title']}\n예전 주소: {record['url']}\n"
          f"카테고리: {saved['category'] or '기본'} / 태그 {len(saved['tags'])}개 / 사진 {len(files)}장 중 {len(photo_paths)}장 찾음"
          + (f" (못 찾은 사진: {', '.join(missing)})" if missing else ""))
    print("순서: 1) 고친 모양으로 새로 발행  2) 새 글이 제대로 올라가면 예전 글 삭제")
    if input("진행할까요? 네면 y 를 치고 엔터: ").strip().lower() not in ("y", "네", "ㅇ"):
        print("취소했어요.")
        return
    with publisher.open_browser() as page:
        try:
            result = publisher.post(page, record["title"], blocks, saved["tags"], photo_paths, saved["captions"],
                                    publish=True, category=saved["category"], quote=saved["quote"])
        except publisher.PublishError as e:
            stop(f"새 글을 올리지 못했어요. 예전 글은 그대로 있어요. {e}")
        if result["result"] != "published":
            stop("새 글 모양이 깨져서 임시저장만 했어요. 예전 글은 지우지 않았어요. 주의: " + " / ".join(result["warnings"]))
        new_url = result["url"]
        if not re.search(r"/\d{9,}|logNo=\d+", new_url):
            found = find_on_blog(record["title"])
            new_url = found["url"] if found else new_url
        deleted = publisher.delete_post(page, record["url"], record["title"])

    # 기록의 주소를 새 글로 바꾼다 (검색 성과 확인, 내부링크가 새 글을 보게)
    old_url = record["url"]
    record["url"], record["replaced_url"] = new_url, old_url
    history.save(records)
    message = f"[블로그 자동화] 글을 새로 발행했어요\n제목: {record['title']}\n새 주소: {new_url}"
    message += "\n예전 글 삭제: " + ("완료" if deleted else "실패. 예전 글을 직접 지워 주세요 (글 오른쪽 위 ... → 삭제)")
    if result["warnings"]:
        message += "\n주의: " + " / ".join(result["warnings"])
    log.info(message)
    notifier.notify(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="글만 만들고 네이버에는 올리지 않음")
    parser.add_argument("--schedule", action="store_true", help="발행 시간대 안 무작위 시각에 실행")
    parser.add_argument("--topic", help="특정 주제로 쓰기")
    parser.add_argument("--fix-last", action="store_true", help="가장 최근 발행 글의 본문을 다시 입력")
    args = parser.parse_args()
    setup_logging()
    keep_awake()
    if args.fix_last:
        if not check_login():
            stop("네이버 로그인이 안 되어 있어요. 1_네이버로그인.bat 을 먼저 실행해 주세요.")
        fix_last()
        return

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
        topic, photo_set, related, post, blocks, attempted = pending
        if attempted and AUTO_PUBLISH:
            # 지난번에 발행 버튼까지 눌렀을 수 있다. 블로그에 이미 있으면 다시 올리지 않는다.
            found = find_on_blog(post["title"])
            if found is None:
                stop("지난번 글이 발행됐는지 블로그에서 확인하지 못했어요. 같은 글이 두 번 올라가지 않게 "
                     "이번에는 쉽니다. 블로그를 한 번 확인해 주세요. 다음 실행 때 다시 확인합니다.")
            if found:
                log.info("지난번 글이 이미 블로그에 올라가 있어요. 다시 올리지 않습니다: %s", post["title"])
                finish(topic, photo_set, post, blocks,
                       {"result": "published", "url": found["url"], "warnings": []},
                       note="(지난번 실행 때 올라간 글을 이제 기록했어요. 다시 올리지 않았어요.)")
                pending = None
    if pending:
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

    if AUTO_PUBLISH:
        save_pending(topic, photo_set, related, post, blocks, attempted=True)
    log.info("크롬을 열어 네이버에 입력합니다. 끝날 때까지 크롬 창 안을 클릭하지 마세요.")
    photo_paths = {p.name: photos.prepare_upload(p) for p in photo_set["files"]} if photo_set else {}
    recorded = False
    try:
        with publisher.open_browser() as page:
            try:
                result = publisher.post(
                    page, post["title"], blocks, post["tags"],
                    photo_paths, post["photo_captions"], publish=AUTO_PUBLISH, category=topic["category"],
                    quote=post.get("quote", ""),
                )
            except publisher.PublishError as e:
                stop(f"{e}\n다시 실행하면 이 글이 블로그에 있는지 먼저 확인하고, 없을 때만 다시 올립니다.")
            except Exception as e:
                shot = publisher.screenshot(page, "error")
                log.error("예상하지 못한 오류: %r", e)
                where = f" 그때 화면: {shot}" if shot else ""
                stop(f"네이버에 입력하다 멈췄어요. 크롬 창이 닫혔거나 화면이 바뀌었을 수 있어요.{where}"
                     "\n다시 실행하면 이 글이 블로그에 있는지 먼저 확인하고, 없을 때만 다시 올립니다.")
            if result["result"] == "published" and not re.search(r"/\d+|logNo=\d+", result["url"]):
                found = find_on_blog(post["title"])  # 글 주소를 못 읽었으면 블로그 글 목록에서 찾는다
                if found:
                    result["url"] = found["url"]
            # 크롬을 닫기 전에 바로 기록한다. (닫다가 오류가 나도 같은 글을 다시 올리지 않게)
            finish(topic, photo_set, post, blocks, result)
            recorded = True
    except SystemExit:
        raise
    except Exception as e:
        log.error("예상하지 못한 오류: %r", e)
        if recorded:  # 글은 이미 올라가고 기록됐다. 크롬을 닫다가 난 오류라 무시한다
            return
        stop("크롬을 열거나 닫다가 문제가 생겼어요. 다시 실행하면 이 글이 블로그에 있는지 먼저 확인하고, "
             "없을 때만 다시 올립니다.")

    if args.schedule:
        # 자동 실행 끝에 지난 글들이 검색에 나오는지 확인한다. 월요일에는 순위, 플레이스, 검색량까지.
        try:
            import seo_check
            seo_check.run(full=datetime.now().weekday() == 0)
        except Exception as e:  # 확인이 안 돼도 글 발행에는 영향 없다
            log.warning("검색 성과 확인을 못 했어요: %s", e)


if __name__ == "__main__":
    main()
