"""숏폼 자동 편집기 프로그램 창.

실제 작업은 `python -m shortform auto 영상` 을 별도 프로세스로 돌리고, 이 창은
설정 입력, 진행 상황 표시, 숏폼 고르기 화면, 중지·결과 폴더 열기를 맡는다.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import review, settings
from .highlights import Highlight
from .styles import PRESETS

ROOT = settings.ROOT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIDEO_TYPES = [("영상 파일", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("모든 파일", "*.*")]

MODELS = [("small", "빠름 (small)"), ("medium", "보통 (medium)"), ("large-v3", "정확함 (large-v3)")]
UPLOADS = [("no", "안 함"), ("private", "비공개"), ("unlisted", "일부 공개"), ("public", "공개")]
STYLE_NAMES = {"green": "green (초록 강조 + 하단 문구)", "magenta": "magenta (분홍 강조)",
               "overlay": "overlay (영상 꽉 채우기)", "basic": "basic (16:9 그대로)"}


def _python() -> str:
    """작업용 파이썬. 창은 pythonw로 떠도 작업은 python.exe로 돌려야 출력을 받을 수 있다."""
    if os.environ.get("SHORTFORM_PYTHON"):
        return os.environ["SHORTFORM_PYTHON"]
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            return cand
    return exe


def _open_folder(path: str) -> None:
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass  # 폴더를 못 열어도 작업 결과에는 영향 없음


class App:
    def __init__(self, root: tk.Tk, videos: list[str]):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.queue: queue.Queue = queue.Queue()
        self.last_output: str | None = None
        self.stopping = False

        root.title("숏폼 자동 편집기")
        try:
            root.iconbitmap(os.path.join(ROOT, "shortform", "assets", "app.ico"))
        except tk.TclError:
            pass  # 아이콘을 못 읽어도 창은 그대로
        root.geometry("980x760")
        root.minsize(860, 640)
        self._fonts()
        try:
            self.cfg = settings.load()
        except RuntimeError:
            self.cfg = dict(settings.DEFAULTS)

        self._build()
        for v in videos:
            self._add_video(v)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)
        self._check_update()

    # ---------- 화면 ----------

    def _fonts(self) -> None:
        family = "Malgun Gothic" if sys.platform == "win32" else None
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            f.configure(size=10, **({"family": family} if family else {}))
        self.big = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.big.configure(size=12, weight="bold")
        self.mono = tkfont.Font(family="Consolas" if sys.platform == "win32" else "TkFixedFont",
                                size=9)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", font=self.big, padding=(18, 8))

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # 영상 목록
        vf = ttk.LabelFrame(main, text=" 1. 영상 선택 ", padding=8)
        vf.pack(fill="x")
        self.videos = tk.Listbox(vf, height=3, activestyle="none")
        self.videos.pack(side="left", fill="x", expand=True)
        vb = ttk.Frame(vf)
        vb.pack(side="left", padx=(8, 0))
        ttk.Button(vb, text="영상 추가...", command=self._pick_videos).pack(fill="x")
        ttk.Button(vb, text="목록에서 빼기", command=self._remove_video).pack(fill="x", pady=(4, 0))

        # 설정 (왼쪽: 기본 / 오른쪽: 자동 편집)
        sf = ttk.LabelFrame(main, text=" 2. 설정 ", padding=8)
        sf.pack(fill="x", pady=(8, 0))
        left = ttk.Frame(sf)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(sf)
        right.pack(side="left", fill="y", padx=(16, 0))

        c = self.cfg
        r = 0
        ttk.Label(left, text="디자인").grid(row=r, column=0, sticky="w", **pad)
        names = [STYLE_NAMES.get(k, k) for k in PRESETS]
        self.style_var = tk.StringVar(value=STYLE_NAMES.get(c["style"], c["style"]))
        ttk.Combobox(left, textvariable=self.style_var, values=names, width=34).grid(
            row=r, column=1, columnspan=3, sticky="w", **pad)

        r += 1
        ttk.Label(left, text="숏폼 개수").grid(row=r, column=0, sticky="w", **pad)
        self.count_var = tk.StringVar(value=c["count"])
        ttk.Spinbox(left, from_=1, to=30, textvariable=self.count_var, width=6).grid(
            row=r, column=1, sticky="w", **pad)
        ttk.Label(left, text="길이(초)").grid(row=r, column=2, sticky="e", **pad)
        lf = ttk.Frame(left)
        lf.grid(row=r, column=3, sticky="w", **pad)
        self.min_var = tk.StringVar(value=c["min_len"])
        self.max_var = tk.StringVar(value=c["max_len"])
        ttk.Spinbox(lf, from_=5, to=180, textvariable=self.min_var, width=5).pack(side="left")
        ttk.Label(lf, text=" ~ ").pack(side="left")
        ttk.Spinbox(lf, from_=10, to=180, textvariable=self.max_var, width=5).pack(side="left")

        r += 1
        ttk.Label(left, text="영상 설명").grid(row=r, column=0, sticky="nw", **pad)
        self.context = tk.Text(left, height=3, width=50, wrap="word")
        self.context.insert("1.0", c["context"])
        self.context.grid(row=r, column=1, columnspan=3, sticky="we", **pad)

        r += 1
        ttk.Label(left, text="인물 소개").grid(row=r, column=0, sticky="w", **pad)
        self.speaker_var = tk.StringVar(value=c["speaker"])
        ttk.Entry(left, textvariable=self.speaker_var, width=30).grid(
            row=r, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(left, text="(비우면 AI가 정해요)", foreground="gray").grid(
            row=r, column=3, sticky="w")

        r += 1
        ttk.Label(left, text="음성 인식").grid(row=r, column=0, sticky="w", **pad)
        self.model_var = tk.StringVar(value=dict(MODELS).get(c["model"], c["model"]))
        ttk.Combobox(left, textvariable=self.model_var, values=[v for _, v in MODELS],
                     state="readonly", width=18).grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        left.columnconfigure(3, weight=1)

        self.flags = {}
        for key, text in [("focus", "얼굴 따라가기"), ("fix_subtitles", "자막 오타 교정 (Claude)"),
                          ("review", "만들기 전에 고르기"), ("zoom", "핵심 단어 확대"),
                          ("sfx", "확대할 때 효과음"), ("thumbnail", "썸네일 만들기")]:
            on = c[key] == "auto" if key == "focus" else c[key].lower() == "yes"
            var = tk.BooleanVar(value=on)
            ttk.Checkbutton(right, text=text, variable=var).pack(anchor="w", pady=1)
            self.flags[key] = var

        bg = ttk.Frame(right)
        bg.pack(anchor="w", pady=(6, 0))
        ttk.Label(bg, text="배경음악 볼륨").pack(side="left")
        try:
            vol = float(c["bgm_volume"])
        except ValueError:
            vol = 0.15
        self.bgm_var = tk.DoubleVar(value=vol)
        ttk.Scale(bg, from_=0, to=0.5, variable=self.bgm_var, length=110).pack(side="left", padx=4)
        ttk.Button(right, text="배경음악 폴더 열기",
                   command=lambda: _open_folder(os.path.join(ROOT, "bgm"))).pack(anchor="w", pady=2)

        up = ttk.Frame(right)
        up.pack(anchor="w", pady=(4, 0))
        ttk.Label(up, text="유튜브 업로드").pack(side="left")
        self.upload_var = tk.StringVar(value=dict(UPLOADS).get(c["upload"], "안 함"))
        ttk.Combobox(up, textvariable=self.upload_var, values=[v for _, v in UPLOADS],
                     state="readonly", width=9).pack(side="left", padx=4)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            kf = ttk.Frame(main)
            kf.pack(fill="x", pady=(6, 0))
            ttk.Label(kf, text="Claude API 키", foreground="#b00").pack(side="left")
            self.key_var = tk.StringVar()
            ttk.Entry(kf, textvariable=self.key_var, show="•", width=50).pack(side="left", padx=6)
            ttk.Button(kf, text="저장", command=self._save_key).pack(side="left")
        else:
            self.key_var = None

        # 실행
        rf = ttk.Frame(main)
        rf.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(rf, text="숏폼 만들기", style="Big.TButton",
                                    command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(rf, text="중지", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.open_btn = ttk.Button(rf, text="결과 폴더 열기", command=self._open_output,
                                   state="disabled")
        self.open_btn.pack(side="left")
        self.status = ttk.Label(rf, text="", font=self.big)
        self.status.pack(side="left", padx=16)

        self.bar = ttk.Progressbar(main, mode="indeterminate")
        self.bar.pack(fill="x", pady=(8, 4))

        lf = ttk.Frame(main)
        lf.pack(fill="both", expand=True)
        self.log = tk.Text(lf, height=12, font=self.mono, wrap="word", state="disabled",
                           background="#1e1e1e", foreground="#dddddd", insertbackground="white")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    # ---------- 영상 목록 ----------

    def _add_video(self, path: str) -> None:
        path = os.path.abspath(path)
        if path not in self.videos.get(0, "end"):
            self.videos.insert("end", path)

    def _pick_videos(self) -> None:
        for p in filedialog.askopenfilenames(title="영상 고르기", filetypes=VIDEO_TYPES):
            self._add_video(p)

    def _remove_video(self) -> None:
        for i in reversed(self.videos.curselection()):
            self.videos.delete(i)

    # ---------- 설정 ----------

    def _values(self) -> dict[str, str]:
        rev = {v: k for k, v in STYLE_NAMES.items()}
        style = rev.get(self.style_var.get(), self.style_var.get().split(" ")[0])
        focus = "auto" if self.flags["focus"].get() else (
            self.cfg["focus"] if self.cfg["focus"] != "auto" else "0.5")
        yes = lambda k: "yes" if self.flags[k].get() else "no"
        return {
            "style": style, "count": self.count_var.get().strip(),
            "min_len": self.min_var.get().strip(), "max_len": self.max_var.get().strip(),
            "context": " ".join(self.context.get("1.0", "end").split()),
            "speaker": self.speaker_var.get().strip(),
            "model": {v: k for k, v in MODELS}.get(self.model_var.get(), "small"),
            "focus": focus, "fix_subtitles": yes("fix_subtitles"), "review": yes("review"),
            "zoom": yes("zoom"), "sfx": yes("sfx"), "thumbnail": yes("thumbnail"),
            "bgm_volume": f"{self.bgm_var.get():.2f}",
            "upload": {v: k for k, v in UPLOADS}.get(self.upload_var.get(), "no"),
        }

    def _save_key(self) -> None:
        key = (self.key_var.get() if self.key_var else "").strip()
        if not key.startswith("sk-"):
            messagebox.showwarning("API 키", "sk-ant- 로 시작하는 키를 넣어 주세요.")
            return
        os.environ["ANTHROPIC_API_KEY"] = key
        if sys.platform == "win32":
            subprocess.run(["setx", "ANTHROPIC_API_KEY", key], capture_output=True,
                           creationflags=NO_WINDOW)
        messagebox.showinfo("API 키", "저장했어요.")

    # ---------- 실행 ----------

    def _start(self) -> None:
        videos = list(self.videos.get(0, "end"))
        if not videos:
            messagebox.showinfo("숏폼 자동 편집기", "먼저 [영상 추가...]로 영상을 골라 주세요.")
            return
        values = self._values()
        try:
            int(values["count"]), float(values["min_len"]), float(values["max_len"])
        except ValueError:
            messagebox.showwarning("설정", "개수와 길이는 숫자로 적어 주세요.")
            return
        if self.key_var is not None and self.key_var.get().strip() and \
                not os.environ.get("ANTHROPIC_API_KEY"):
            self._save_key()
        try:
            settings.save(values)
        except Exception as e:
            self._append(f"(설정 저장 실패: {e})\n")
        self.stopping = False
        self._set_running(True)
        threading.Thread(target=self._run_all, args=(videos,), daemon=True).start()

    def _run_all(self, videos: list[str]) -> None:
        env = {**os.environ, "SHORTFORM_GUI": "1", "PYTHONUNBUFFERED": "1",
               "PYTHONIOENCODING": "utf-8"}
        code = 0
        for n, video in enumerate(videos, 1):
            if self.stopping:
                break
            self.queue.put(("status", f"[{n}/{len(videos)}] {os.path.basename(video)}"))
            self.queue.put(("log", f"\n===== {video} =====\n", False))
            self.last_output = settings.output_dir(video)
            kwargs = {"creationflags": NO_WINDOW} if sys.platform == "win32" else \
                {"start_new_session": True}
            self.proc = subprocess.Popen(
                [_python(), "-m", "shortform", "auto", video], cwd=ROOT, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                **kwargs)
            self._pump(self.proc)
            code = self.proc.wait()
            if code and not self.stopping:
                break
        self.queue.put(("done", code))

    def _pump(self, proc: subprocess.Popen) -> None:
        """출력을 읽어 창으로 보낸다. '\\r'로 끝나는 진행률 줄은 마지막 줄을 덮어쓴다."""
        import codecs

        dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buf = ""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not chunk:
                break
            buf += dec.decode(chunk)
            while True:
                i = min((k for k in (buf.find("\n"), buf.find("\r")) if k >= 0), default=-1)
                if i < 0:
                    break
                line, sep, buf = buf[:i], buf[i], buf[i + 1:]
                if line.startswith("@@REVIEW@@ "):
                    self.queue.put(("review", line[len("@@REVIEW@@ "):].strip()))
                    continue
                if line.startswith("[") and "]" in line[:20]:
                    self.queue.put(("stage", line.strip()))
                self.queue.put(("log", line + ("\n" if sep == "\n" else ""), sep == "\r"))
        if buf:
            self.queue.put(("log", buf + "\n", False))

    def _stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        if not messagebox.askyesno("중지", "지금 작업을 멈출까요?\n다시 [숏폼 만들기]를 누르면 "
                                         "끝난 부분부터 이어서 해요."):
            return
        self.stopping = True
        self._kill()

    def _kill(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        if sys.platform == "win32":  # 자식 프로세스(FFmpeg)까지 같이 끈다
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=NO_WINDOW)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self.bar.start(12)
            self.open_btn.configure(state="disabled")
        else:
            self.bar.stop()
            if self.last_output and os.path.isdir(self.last_output):
                self.open_btn.configure(state="normal")

    def _open_output(self) -> None:
        if self.last_output and os.path.isdir(self.last_output):
            _open_folder(self.last_output)

    # ---------- 창 갱신 ----------

    def _append(self, text: str, replace_last: bool = False) -> None:
        self.log.configure(state="normal")
        if self._replacing:
            self.log.delete("end-1c linestart", "end-1c")
        self.log.insert("end", text)
        self._replacing = replace_last
        self.log.see("end")
        self.log.configure(state="disabled")

    _replacing = False

    def _poll(self) -> None:
        try:
            while True:
                kind, *rest = self.queue.get_nowait()
                if kind == "log":
                    self._append(*rest)
                elif kind == "stage":
                    self.status.configure(text=rest[0][:40])
                elif kind == "status":
                    self.root.title(f"숏폼 자동 편집기 - {rest[0]}")
                elif kind == "review":
                    self.dialog = ReviewDialog(self.root, rest[0])
                elif kind == "done":
                    self._finish(rest[0])
                elif kind == "updated":
                    self._restart()
                    return
                elif kind == "ready":
                    self.start_btn.configure(state="normal")
                    self.status.configure(text=rest[0])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, code: int) -> None:
        self._set_running(False)
        self.root.title("숏폼 자동 편집기")
        if self.stopping:
            self.status.configure(text="중지했어요")
        elif code == 0:
            self.status.configure(text="완료!")
            self._open_output()
        else:
            self.status.configure(text="오류가 났어요 (아래 메시지를 캡처해 주세요)")

    # ---------- 업데이트 ----------

    def _check_update(self) -> None:
        self.start_btn.configure(state="disabled")
        self.status.configure(text="업데이트 확인 중...")

        def work():
            from . import update
            try:
                changed = update.update()
            except Exception as e:  # 인터넷 문제 등: 지금 버전으로
                self.queue.put(("log", f"[업데이트 확인] 건너뜀 ({e})\n", False))
                self.queue.put(("ready", ""))
                return
            if "requirements.txt" in changed:
                self.queue.put(("log", "[업데이트] 필요한 패키지 설치 중...\n", False))
                subprocess.run([_python(), "-m", "pip", "install", "-q",
                                "--no-warn-script-location", "-r",
                                os.path.join(ROOT, "requirements.txt")], creationflags=NO_WINDOW)
            if any(c.startswith("shortform/") and c.endswith(".py") for c in changed):
                self.queue.put(("updated",))
                return
            msg = f"새 버전으로 업데이트했어요 ({len(changed)}개)" if changed else ""
            self.queue.put(("log", f"[업데이트 확인] {msg or '최신 버전이에요.'}\n", False))
            self.queue.put(("ready", msg))

        threading.Thread(target=work, daemon=True).start()

    def _restart(self) -> None:
        """프로그램 코드가 바뀌었으면 새 코드로 창을 다시 연다."""
        videos = list(self.videos.get(0, "end"))
        subprocess.Popen([sys.executable, "-m", "shortform.gui", *videos], cwd=ROOT,
                         creationflags=NO_WINDOW)
        self.root.destroy()

    def _on_close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("닫기", "작업 중이에요. 멈추고 닫을까요?\n"
                                             "다음에 같은 영상으로 다시 하면 이어서 해요."):
                return
            self.stopping = True
            self._kill()
        self.root.destroy()


class ReviewDialog:
    """하이라이트 목록에서 만들 숏폼을 고르고 제목·문구·구간을 고치는 창."""

    def __init__(self, parent: tk.Tk, path: str):
        self.path = path
        with open(os.path.join(os.path.dirname(path), "highlights.json"), encoding="utf-8") as f:
            self.highlights = [Highlight(**h) for h in json.load(f)["highlights"]]

        self.win = win = tk.Toplevel(parent)
        win.title("만들 숏폼 고르기")
        win.geometry("1000x620")
        win.transient(parent)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", self._done)

        ttk.Label(win, text="만들 숏폼에 체크하고, 필요하면 제목·문구·구간을 고친 뒤 "
                            "[선택한 숏폼 만들기]를 눌러 주세요.  (제목 줄바꿈은 /, 강조는 {중괄호})",
                  padding=(10, 8)).pack(anchor="w")

        outer = ttk.Frame(win)
        outer.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        win.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        win.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        win.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        for col, text in enumerate(["", "번호", "점수", "구간", "제목", "하단 문구", "선정 이유"]):
            ttk.Label(body, text=text, font=("", 9, "bold")).grid(row=0, column=col, sticky="w",
                                                                 padx=4, pady=(0, 4))
        self.rows = []
        for i, h in enumerate(self.highlights, 1):
            on = tk.BooleanVar(value=True)
            rng = tk.StringVar(value=f"{review._hms(h.start)} ~ {review._hms(h.end)}")
            title = tk.StringVar(value=h.title.replace("\n", " / "))
            bottom = tk.StringVar(value=h.bottom)
            ttk.Checkbutton(body, variable=on).grid(row=i, column=0, padx=4, pady=3)
            ttk.Label(body, text=f"{i:02}").grid(row=i, column=1, padx=4)
            ttk.Label(body, text=f"{h.score}/10").grid(row=i, column=2, padx=4)
            ttk.Entry(body, textvariable=rng, width=14).grid(row=i, column=3, padx=4)
            ttk.Entry(body, textvariable=title, width=34).grid(row=i, column=4, padx=4)
            ttk.Entry(body, textvariable=bottom, width=18).grid(row=i, column=5, padx=4)
            ttk.Label(body, text=h.reason, wraplength=260, foreground="#555").grid(
                row=i, column=6, padx=4, sticky="w")
            self.rows.append((on, rng, title, bottom))

        bf = ttk.Frame(win, padding=10)
        bf.pack(fill="x")
        ttk.Button(bf, text="모두 선택", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(bf, text="모두 해제", command=lambda: self._all(False)).pack(side="left", padx=6)
        ttk.Button(bf, text="선택한 숏폼 만들기", style="Big.TButton",
                   command=self._done).pack(side="right")

    def _all(self, value: bool) -> None:
        for on, *_ in self.rows:
            on.set(value)

    def _done(self) -> None:
        for h, (on, rng, title, bottom) in zip(self.highlights, self.rows):
            h.title = "\n".join(p.strip() for p in title.get().split("/") if p.strip())
            h.bottom = bottom.get().strip()
            try:
                a, b = (review._sec(x) for x in rng.get().split("~"))
                if b > a:
                    h.start, h.end = a, b
            except ValueError:
                pass
        review.write(self.path, self.highlights)
        with open(self.path, encoding="utf-8-sig") as f:
            text = f.read()
        for i, (on, *_) in enumerate(self.rows, 1):
            if not on.get():
                text = text.replace(f"[O] {i:02} ", f"[X] {i:02} ", 1)
        with open(self.path, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(text.replace("\r\n", "\n"))
        open(self.path + ".done", "w").close()
        self.win.unbind_all("<MouseWheel>")
        self.win.destroy()


def main() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"프로그램 창을 열 수 없어요: {e}\nrun.bat에 영상을 끌어다 놓는 방식으로 써 주세요.")
        sys.exit(1)
    App(root, [a for a in sys.argv[1:] if os.path.isfile(a)])
    root.mainloop()


if __name__ == "__main__":
    main()
