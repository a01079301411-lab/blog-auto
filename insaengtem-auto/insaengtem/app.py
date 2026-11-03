"""관리 프로그램(바탕화면 아이콘으로 실행). 내 PC 안에서만 열리는 웹 화면: http://127.0.0.1:8765

실행: pythonw -m insaengtem.app   (이미 켜져 있으면 브라우저만 다시 연다)
"""
from __future__ import annotations

import json
import mimetypes
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, qa
from .config import OUT, ROOT, env, fmt_when, now, set_env_values, settings
from .winsetup import NO_WINDOW

PORT = 8765
STATIC = Path(__file__).parent / "static"
ALLOWED = {"scrape", "trends", "generate", "render", "plan", "approve", "run-due", "schedule-web", "sync", "insights",
           "inbox", "weekly", "dashboard", "auto", "login", "check", "links", "import-week1", "publish-now", "refresh-token"}
ENV_KEYS = ["ANTHROPIC_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN", "THREADS_USER_ID", "THREADS_ACCESS_TOKEN",
            "MEDIA_BASE_URL", "S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_PUBLIC_BASE_URL",
            "META_ASSET_ID", "META_BUSINESS_ID"]
SECRET_KEYS = {"ANTHROPIC_API_KEY", "IG_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN", "S3_SECRET_ACCESS_KEY", "S3_ACCESS_KEY_ID"}
JOBS: dict[str, dict] = {}


def start_job(args: list[str]) -> str:
    if not args or args[0] not in ALLOWED:
        raise ValueError("허용되지 않은 명령")
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "args": args, "lines": [], "done": False, "code": None, "started": fmt_when(now())}
    JOBS[jid] = job

    def run():
        envv = dict(__import__("os").environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PYTHONUTF8="1")
        exe = Path(sys.executable)
        py = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
        try:
            p = subprocess.Popen([str(py), "-m", "insaengtem", *args], cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                 errors="replace", env=envv, creationflags=NO_WINDOW)
            for line in p.stdout:
                job["lines"].append(line.rstrip("\n"))
            job["code"] = p.wait()
        except Exception as e:  # noqa: BLE001
            job["lines"].append(f"실행 실패: {e}")
            job["code"] = -1
        job["done"] = True
    threading.Thread(target=run, daemon=True).start()
    return jid


def current_week() -> str:
    from datetime import timedelta
    d = now().date() + timedelta(days=(7 - now().weekday()) % 7 or 7)
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def status() -> dict:
    from .winsetup import autopublish_status, checklist
    with db.connect() as con:
        cnt = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM posts GROUP BY status")}
        today = now().strftime("%Y-%m-%d")
        nxt = [dict(r) for r in con.execute(
            "SELECT id, when_kst, platform, product, variant, status FROM posts WHERE when_kst>=? AND status IN "
            "('approved','scheduled_web','external','draft') ORDER BY when_kst LIMIT 8", (fmt_when(now()),))]
        unanswered = con.execute("SELECT COUNT(*) FROM replies_seen WHERE answered=0").fetchone()[0]
        weeks = [r[0] for r in con.execute("SELECT DISTINCT week FROM posts WHERE week IS NOT NULL ORDER BY week DESC")]
        todays = con.execute("SELECT COUNT(*) FROM posts WHERE substr(when_kst,1,10)=?", (today,)).fetchone()[0]
    s = settings()
    return {"counts": cnt, "next": nxt, "unanswered": unanswered, "weeks": weeks, "today": todays,
            "checklist": checklist(), "autopublish": autopublish_status(), "next_week": current_week(),
            "publish_mode": s["publish_mode"], "instagram_slots": s["instagram"]["slots"], "now": fmt_when(now())}


def posts(week: str | None) -> list[dict]:
    with db.connect() as con:
        q = "SELECT * FROM posts" + (" WHERE week=?" if week else "") + " ORDER BY when_kst"
        rows = [dict(r) for r in con.execute(q, (week,) if week else ())]
    for r in rows:
        if r["product"] and r["variant"]:
            c = f"{r['product']}_{r['variant']}/cover_3x4.jpg"
            r["cover"] = f"/out/{c}" if (OUT / c).exists() else None
    return rows


def update_post(pid: int, body: dict) -> dict:
    with db.connect() as con:
        r = con.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
        if not r:
            return {"error": "없음"}
        if "action" in body:
            a = body["action"]
            new = {"skip": "skipped", "retry": "approved", "approve": "approved", "draft": "draft"}[a]
            db.set_status(con, pid, new, error=None)
            return {"ok": True, "status": new}
        if r["status"] in ("published", "publishing"):
            return {"error": "이미 게시된 건은 수정할 수 없습니다"}
        text, reply = body.get("text", r["text"]), body.get("reply", r["reply"])
        con.execute("UPDATE posts SET text=?, reply=?, status=CASE WHEN status='approved' THEN 'draft' ELSE status END WHERE id=?",
                    (text, reply, pid))
    plat = "instagram" if r["platform"] == "instagram" else "threads_root"
    iss = qa.check_text(text or "", where="본문", is_ad=bool(r["product"]), platform=plat)
    if reply:
        iss += qa.check_text(reply, where="2번째 칸", is_ad=True, platform="threads_reply")
    return {"ok": True, "issues": [str(i) for i in iss]}


def metrics() -> dict:
    with db.connect() as con:
        rows = [dict(r) for r in db.latest_metrics(con) if r["views"] is not None]
    weekly = sorted(OUT.glob("weekly_*.json"))
    w = json.loads(weekly[-1].read_text(encoding="utf-8")) if weekly else {}
    return {"rows": rows, "weekly": w}


def inbox_list() -> list[dict]:
    with db.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT s.*, p.permalink, p.product FROM replies_seen s LEFT JOIN posts p ON p.id=s.post_id "
            "WHERE s.answered=0 ORDER BY s.ts DESC LIMIT 200")]


def env_view() -> list[dict]:
    out = []
    for k in ENV_KEYS:
        v = env(k) or ""
        out.append({"key": k, "set": bool(v), "value": ("●●●●" + v[-4:]) if (v and k in SECRET_KEYS) else v,
                    "secret": k in SECRET_KEYS})
    return out


def save_settings(body: dict) -> None:
    p = ROOT / "config" / "settings.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    if "publish_mode" in body:
        for k, v in body["publish_mode"].items():
            if k in ("instagram", "threads") and v in ("api", "web"):
                s["publish_mode"][k] = v
    if "instagram_per_day" in body:
        n = int(body["instagram_per_day"])
        s["instagram"]["slots"] = {2: ["12:30", "21:30"], 3: ["12:30", "18:30", "21:30"]}.get(n, s["instagram"]["slots"])
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.cache_clear()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 조용히
        pass

    def _ok_host(self) -> bool:
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def do_GET(self):
        if not self._ok_host():
            return self.send_error(403)
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._file(STATIC / "app.html")
            if u.path.startswith("/out/"):
                f = (OUT / u.path[5:]).resolve()
                return self._file(f) if str(f).startswith(str(OUT.resolve())) else self.send_error(403)
            if u.path == "/api/status":
                return self._json(status())
            if u.path == "/api/posts":
                return self._json(posts(q.get("week")))
            if u.path == "/api/metrics":
                return self._json(metrics())
            if u.path == "/api/inbox":
                return self._json(inbox_list())
            if u.path == "/api/env":
                return self._json(env_view())
            if u.path == "/api/links":
                from .catalog import load_catalog, load_links
                links = load_links()
                return self._json([{"key": c["key"], "name": c.get("name"), "available": c.get("available"),
                                    "linked": c["key"] in links} for c in load_catalog()])
            if u.path.startswith("/api/jobs/"):
                j = JOBS.get(u.path.rsplit("/", 1)[1])
                return self._json(j or {"error": "없음"})
            if u.path == "/api/jobs":
                return self._json([{k: j[k] for k in ("id", "args", "done", "code", "started")} for j in JOBS.values()][-20:])
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)
        self.send_error(404)

    def do_POST(self):
        # 다른 사이트가 몰래 요청 못 하도록: 로컬 Host + 커스텀 헤더 필수
        if not self._ok_host() or self.headers.get("X-Insaengtem") != "1":
            return self.send_error(403)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        u = urlparse(self.path).path
        try:
            if u == "/api/run":
                return self._json({"job": start_job([str(x) for x in body["args"]])})
            if u.startswith("/api/posts/"):
                return self._json(update_post(int(u.rsplit("/", 1)[1]), body))
            if u == "/api/env":
                vals = {k: str(v).strip() for k, v in body.items() if k in ENV_KEYS and str(v).strip() and not str(v).startswith("●")}
                set_env_values(vals)
                return self._json({"ok": True, "saved": list(vals)})
            if u == "/api/settings":
                save_settings(body)
                return self._json({"ok": True})
            if u == "/api/links":
                from .catalog import set_link
                set_link(body["key"], body["url"])
                return self._json({"ok": True})
            if u == "/api/links/import":
                from .catalog import import_links
                tmp = ROOT / "secrets" / "_import_catalog.json"
                tmp.parent.mkdir(exist_ok=True)
                tmp.write_text(json.dumps(body["catalog"], ensure_ascii=False), encoding="utf-8")
                try:
                    n_ = import_links(tmp)
                finally:
                    tmp.unlink(missing_ok=True)
                return self._json({"ok": True, "count": n_})
            if u == "/api/autopublish":
                from .winsetup import autopublish
                return self._json({"log": autopublish(bool(body.get("on")))})
            if u.startswith("/api/inbox/"):
                with db.connect() as con:
                    con.execute("UPDATE replies_seen SET answered=1 WHERE reply_id=?", (u.rsplit("/", 1)[1],))
                return self._json({"ok": True})
            if u == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=lambda: (time.sleep(0.5), __import__("os")._exit(0)), daemon=True).start()
                return None
        except SystemExit as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        self.send_error(404)


def main(open_browser: bool = True):
    url = f"http://127.0.0.1:{PORT}/"
    with socket.socket() as s:
        busy = s.connect_ex(("127.0.0.1", PORT)) == 0
    if busy:  # 이미 실행 중 → 창만 열기
        webbrowser.open(url)
        return
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main(open_browser="--no-browser" not in sys.argv)
