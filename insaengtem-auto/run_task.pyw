"""작업 스케줄러가 창 없이 실행하는 진입점.  pythonw run_task.pyw run-due|inbox|weekly"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs"
LOG.mkdir(exist_ok=True)
sys.stdout = sys.stderr = open(LOG / f"task_{datetime.now():%Y%m}.log", "a", encoding="utf-8", buffering=1)
print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {sys.argv[1:]} ===")

from insaengtem import db  # noqa: E402
from insaengtem.winsetup import notify  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "run-due"
try:
    if mode == "run-due":
        from insaengtem.ops import run_due
        with db.connect() as con:
            before = {r["id"]: r["status"] for r in con.execute("SELECT id, status FROM posts")}
        run_due()
        with db.connect() as con:
            after = {r["id"]: r["status"] for r in con.execute("SELECT id, status FROM posts")}
        changed = [(i, s) for i, s in after.items() if before.get(i) != s]
        ok = sum(s == "published" for _, s in changed)
        bad = sum(s in ("failed", "missed", "skipped") for _, s in changed)
        if ok or bad:
            notify("인생템연구소 게시", f"게시 완료 {ok}건" + (f" · 실패/건너뜀 {bad}건 → 프로그램에서 확인" if bad else ""))
    elif mode == "inbox":
        from insaengtem.ops import inbox
        new = inbox(hours=48)
        if new:
            notify("새 답글·댓글", f"{len(new)}건 — 1시간 안에 답하면 노출에 유리해요. {new[0]['text'][:40]}")
    elif mode == "weekly":
        try:
            from insaengtem.publish.meta_api import Threads
            Threads().refresh_token()
            print("스레드 토큰 갱신")
        except BaseException as e:  # noqa: BLE001
            print(f"토큰 갱신 건너뜀: {e}")
        from insaengtem.cli import main
        main(["auto"])
        notify("다음 주 준비 완료", "바탕화면 아이콘 → [이번 주 승인] 에서 검토 후 승인하세요.")
except BaseException:  # noqa: BLE001
    traceback.print_exc()
    notify("인생템연구소 오류", f"{mode} 실행 중 오류 — logs 폴더 확인")
