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

from . import accounts, review, settings
from .highlights import Highlight
from .styles import PRESETS

ROOT = settings.ROOT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
APP_TITLE = "숏폼·롱폼 자동 편집기"
PLAN_TYPES = [("기획안", "*.hwp *.docx *.txt *.md"), ("모든 파일", "*.*")]
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

        root.title(APP_TITLE)
        try:
            root.iconbitmap(os.path.join(ROOT, "shortform", "assets", "app.ico"))
        except tk.TclError:
            pass  # 아이콘을 못 읽어도 창은 그대로
        root.geometry("1000x900")
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

        # 숏폼 / 롱폼 탭
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="x")
        short = ttk.Frame(self.tabs, padding=(0, 6, 0, 0))
        self.long_tab = ttk.Frame(self.tabs, padding=(0, 6, 0, 0))
        self.tabs.add(short, text="  숏폼 만들기  ")
        self.tabs.add(self.long_tab, text="  롱폼 만들기  ")
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab)
        self._build_long(self.long_tab)

        # 영상 목록
        vf = ttk.LabelFrame(short, text=" 1. 영상 선택 ", padding=8)
        vf.pack(fill="x")
        self.videos = tk.Listbox(vf, height=3, activestyle="none")
        self.videos.pack(side="left", fill="x", expand=True)
        vb = ttk.Frame(vf)
        vb.pack(side="left", padx=(8, 0))
        ttk.Button(vb, text="영상 추가...", command=self._pick_videos).pack(fill="x")
        ttk.Button(vb, text="목록에서 빼기", command=self._remove_video).pack(fill="x", pady=(4, 0))

        # 코시 인스타 계정
        af = ttk.LabelFrame(short, text=" 2. 인스타 계정 (코시 제작 가이드대로 만들어요) ", padding=8)
        af.pack(fill="x", pady=(8, 0))
        chosen = set(accounts.parse(self.cfg.get("accounts", "")))
        self.acct_vars: dict[int, tk.BooleanVar] = {}
        grid = ttk.Frame(af)
        grid.pack(side="left", fill="x", expand=True)
        for k, (no, a) in enumerate(accounts.ACCOUNTS.items()):
            var = tk.BooleanVar(value=no in chosen)
            ttk.Checkbutton(grid, text=f"{no}. {a.name}", variable=var).grid(
                row=k // 5, column=k % 5, sticky="w", padx=(0, 14), pady=1)
            self.acct_vars[no] = var
        ab = ttk.Frame(af)
        ab.pack(side="left", padx=(8, 0))
        pf = ttk.Frame(ab)
        pf.pack(anchor="w")
        ttk.Label(pf, text="계정당").pack(side="left")
        self.per_var = tk.StringVar(value=self.cfg.get("per_account", "3"))
        ttk.Spinbox(pf, from_=1, to=10, textvariable=self.per_var, width=4).pack(side="left", padx=4)
        ttk.Label(pf, text="개").pack(side="left")
        ttk.Button(ab, text="글꼴 확인", command=self._check_fonts).pack(fill="x", pady=(4, 0))
        ttk.Label(af, text="안 고르면 아래 '디자인'으로 만들어요", foreground="gray").pack(
            side="bottom", anchor="w")

        # 설정 (왼쪽: 기본 / 오른쪽: 자동 편집)
        sf = ttk.LabelFrame(short, text=" 3. 설정 ", padding=8)
        sf.pack(fill="x", pady=(8, 0))
        left = ttk.Frame(sf)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(sf)
        right.pack(side="left", fill="y", padx=(16, 0))

        c = self.cfg
        r = 0
        ttk.Label(left, text="디자인").grid(row=r, column=0, sticky="w", **pad)  # 계정 안 고를 때
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
        for key, text in [("focus", "얼굴 따라가기"),
                          ("burned_subs", "원본에 자막 있으면 그대로 쓰기"),
                          ("fix_subtitles", "자막 오타 교정 (Claude)"),
                          ("review", "만들기 전에 고르기"), ("thumbnail", "썸네일 만들기")]:
            on = c[key] in ("auto", "yes") if key in ("focus", "burned_subs") else \
                c[key].lower() == "yes"
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

    # ---------- 롱폼 탭 ----------

    def _build_long(self, tab: ttk.Frame) -> None:
        pad = {"padx": 8, "pady": 3}
        c = settings.LONG_DEFAULTS
        try:
            c = settings.load_long()
        except Exception:
            pass

        cf = ttk.LabelFrame(tab, text=" 1. 촬영본 (찍은 순서대로 놓으면 AI가 더 정확해요) ", padding=8)
        cf.pack(fill="x")
        self.clips = tk.Listbox(cf, height=6, activestyle="none", selectmode="extended")
        self.clips.pack(side="left", fill="x", expand=True)
        cb = ttk.Frame(cf)
        cb.pack(side="left", padx=(8, 0))
        for text, cmd in [("영상 추가...", self._pick_clips), ("폴더 추가...", self._pick_clip_folder),
                          ("위로", lambda: self._move_clip(-1)), ("아래로", lambda: self._move_clip(1)),
                          ("목록에서 빼기", self._remove_clip)]:
            ttk.Button(cb, text=text, command=cmd).pack(fill="x", pady=1)

        pf = ttk.LabelFrame(tab, text=" 2. 기획안 (파일을 고르거나 아래에 붙여 넣기) ", padding=8)
        pf.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(pf)
        row.pack(fill="x")
        self.plan_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.plan_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="기획안 파일...", command=self._pick_plan).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="지우기", command=lambda: self.plan_var.set("")).pack(side="left", padx=4)
        self.plan_text = tk.Text(pf, height=4, wrap="word")
        self.plan_text.pack(fill="x", pady=(6, 0))

        sf = ttk.LabelFrame(tab, text=" 3. 설정 ", padding=8)
        sf.pack(fill="x", pady=(8, 0))
        left = ttk.Frame(sf)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(sf)
        right.pack(side="left", fill="y", padx=(16, 0))

        ttk.Label(left, text="영상 이름").grid(row=0, column=0, sticky="w", **pad)
        self.long_title = tk.StringVar()
        ttk.Entry(left, textvariable=self.long_title, width=28).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(left, text="목표 길이(분)").grid(row=0, column=2, sticky="e", **pad)
        self.long_minutes = tk.StringVar(value=c["long_minutes"])
        ttk.Spinbox(left, from_=0, to=120, textvariable=self.long_minutes, width=5).grid(
            row=0, column=3, sticky="w", **pad)
        ttk.Label(left, text="(결과 폴더 이름, 비워도 돼요)   0분이면 AI가 정해요",
                  foreground="gray").grid(row=1, column=1, columnspan=3, sticky="w", padx=8)
        ttk.Label(left, text="채널 설명").grid(row=2, column=0, sticky="nw", **pad)
        self.long_context = tk.Text(left, height=3, width=50, wrap="word")
        self.long_context.insert("1.0", c["long_context"])
        self.long_context.grid(row=2, column=1, columnspan=3, sticky="we", **pad)
        ttk.Label(left, text="음성 인식").grid(row=3, column=0, sticky="w", **pad)
        self.long_model = tk.StringVar(value=dict(MODELS).get(c["long_model"], c["long_model"]))
        ttk.Combobox(left, textvariable=self.long_model, values=[v for _, v in MODELS],
                     state="readonly", width=18).grid(row=3, column=1, sticky="w", **pad)
        left.columnconfigure(3, weight=1)

        self.long_flags = {}
        for key, text in [("long_commerce", "유료광고 포함 (코시 커머스 편)"),
                          ("long_review", "만들기 전에 순서표 고치기"),
                          ("long_frames", "장면 사진도 AI에게 보여주기"),
                          ("long_jumpcut", "말 사이 긴 무음 자르기"),
                          ("long_subtitles", "자막 넣기"), ("long_fix_subtitles", "자막 오타 교정"),
                          ("long_chapter_titles", "챕터 제목 띄우기"),
                          ("long_thumbnail", "썸네일 만들기")]:
            var = tk.BooleanVar(value=c[key].lower() == "yes")
            ttk.Checkbutton(right, text=text, variable=var).pack(anchor="w")
            self.long_flags[key] = var
        self.replan = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="편집 순서 새로 짜기", variable=self.replan).pack(anchor="w")
        bg = ttk.Frame(right)
        bg.pack(anchor="w", pady=(4, 0))
        ttk.Label(bg, text="배경음악 볼륨").pack(side="left")
        try:
            vol = float(c["long_bgm_volume"])
        except ValueError:
            vol = 0.10
        self.long_bgm = tk.DoubleVar(value=vol)
        ttk.Scale(bg, from_=0, to=0.4, variable=self.long_bgm, length=110).pack(side="left", padx=4)

    def _on_tab(self, _event=None) -> None:
        if not hasattr(self, "start_btn"):
            return
        long = self.tabs.index(self.tabs.select()) == 1
        self.start_btn.configure(text="롱폼 만들기" if long else "숏폼 만들기")

    def _pick_clips(self) -> None:
        for p in filedialog.askopenfilenames(title="촬영본 고르기", filetypes=VIDEO_TYPES):
            p = os.path.abspath(p)
            if p not in self.clips.get(0, "end"):
                self.clips.insert("end", p)

    def _pick_clip_folder(self) -> None:
        from .longform import collect_clips

        folder = filedialog.askdirectory(title="촬영본 폴더 고르기")
        for p in collect_clips([folder]) if folder else []:
            if p not in self.clips.get(0, "end"):
                self.clips.insert("end", p)

    def _move_clip(self, step: int) -> None:
        sel = list(self.clips.curselection())
        if not sel:
            return
        items = list(self.clips.get(0, "end"))
        order = sel if step < 0 else list(reversed(sel))
        for i in order:
            j = i + step
            if 0 <= j < len(items) and j not in sel:
                items[i], items[j] = items[j], items[i]
                sel[sel.index(i)] = j
        self.clips.delete(0, "end")
        for p in items:
            self.clips.insert("end", p)
        for i in sel:
            self.clips.selection_set(i)

    def _remove_clip(self) -> None:
        for i in reversed(self.clips.curselection()):
            self.clips.delete(i)

    def _pick_plan(self) -> None:
        p = filedialog.askopenfilename(title="기획안 고르기", filetypes=PLAN_TYPES)
        if p:
            self.plan_var.set(os.path.abspath(p))

    def _long_values(self) -> dict[str, str]:
        vals = {k: "yes" if v.get() else "no" for k, v in self.long_flags.items()}
        vals.update({
            "long_context": " ".join(self.long_context.get("1.0", "end").split()),
            "long_minutes": self.long_minutes.get().strip() or "0",
            "long_model": {v: k for k, v in MODELS}.get(self.long_model.get(), "small"),
            "long_bgm_volume": f"{self.long_bgm.get():.2f}",
        })
        return vals

    def _start_long(self) -> None:
        clips = list(self.clips.get(0, "end"))
        if not clips:
            messagebox.showinfo(APP_TITLE, "먼저 [영상 추가...]나 [폴더 추가...]로 촬영본을 넣어 주세요.")
            return
        values = self._long_values()
        try:
            float(values["long_minutes"])
        except ValueError:
            messagebox.showwarning("설정", "목표 길이는 숫자(분)로 적어 주세요.")
            return
        if self.key_var is not None and self.key_var.get().strip() and \
                not os.environ.get("ANTHROPIC_API_KEY"):
            self._save_key()
        try:
            settings.save(values)
        except Exception as e:
            self._append(f"(설정 저장 실패: {e})\n")
        title = self.long_title.get().strip()
        out = settings.long_output_dir(clips, title)
        plan = self.plan_var.get().strip()
        pasted = self.plan_text.get("1.0", "end").strip()
        if plan and not os.path.isfile(plan):
            messagebox.showwarning("기획안", f"기획안 파일을 찾을 수 없어요:\n{plan}")
            return
        if not plan and pasted:  # 붙여 넣은 기획은 결과 폴더에 파일로 저장해서 넘긴다
            os.makedirs(out, exist_ok=True)
            plan = os.path.join(out, "기획안.txt")
            with open(plan, "w", encoding="utf-8") as f:
                f.write(pasted)
        argv = ["longauto", *clips, "-o", out]
        if plan:
            argv += ["--plan", plan]
        if self.replan.get():
            argv.append("--replan")
            self.replan.set(False)
        self.last_output = out
        self.stopping = False
        self._set_running(True)
        threading.Thread(target=self._run_long, args=(argv, title or "롱폼"), daemon=True).start()

    def _run_long(self, argv: list[str], name: str) -> None:
        env = {**os.environ, "SHORTFORM_GUI": "1", "PYTHONUNBUFFERED": "1",
               "PYTHONIOENCODING": "utf-8"}
        self.queue.put(("status", name))
        self.queue.put(("log", f"\n===== 롱폼: {name} =====\n", False))
        kwargs = {"creationflags": NO_WINDOW} if sys.platform == "win32" else \
            {"start_new_session": True}
        self.proc = subprocess.Popen(
            [_python(), "-m", "shortform", *argv], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
        self._pump(self.proc)
        self.queue.put(("done", self.proc.wait()))

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
            "accounts": ",".join(str(n) for n, v in self.acct_vars.items() if v.get()),
            "per_account": self.per_var.get().strip(),
            "style": style, "count": self.count_var.get().strip(),
            "min_len": self.min_var.get().strip(), "max_len": self.max_var.get().strip(),
            "context": " ".join(self.context.get("1.0", "end").split()),
            "speaker": self.speaker_var.get().strip(),
            "model": {v: k for k, v in MODELS}.get(self.model_var.get(), "small"),
            "focus": focus, "fix_subtitles": yes("fix_subtitles"), "review": yes("review"),
            "burned_subs": "auto" if self.flags["burned_subs"].get() else "no",
            "thumbnail": yes("thumbnail"),
            "bgm_volume": f"{self.bgm_var.get():.2f}",
            "upload": {v: k for k, v in UPLOADS}.get(self.upload_var.get(), "no"),
        }

    def _check_fonts(self) -> None:
        """고른 계정에 필요한 글꼴이 이 컴퓨터에 있는지 보여준다."""
        from . import fonts

        picked = [n for n, v in self.acct_vars.items() if v.get()] or list(accounts.ACCOUNTS)
        rows, missing = [], 0
        for n in picked:
            a = accounts.ACCOUNTS[n]
            for role, cands in accounts.all_fonts(a).items():
                path = fonts.find(cands)
                name = cands[1] if len(cands) > 1 else cands[0]
                if path:
                    rows.append(f"✔ {n}. {a.name} - {role}: {name}")
                else:
                    missing += 1
                    rows.append(f"✘ {n}. {a.name} - {role}: {name}  (없음)")
        os.makedirs(fonts.LOCAL_DIR, exist_ok=True)
        tip = ("\n\n없는 글꼴은 코시 가이드의 [3.폰트] 폴더에서 설치하거나, 글꼴 파일을 "
               "프로그램의 fonts 폴더에 넣어 주세요. 없으면 맑은 고딕으로 대신 만들어요."
               if missing else "\n\n모든 글꼴이 준비됐어요!")
        if messagebox.askyesno("글꼴 확인", "\n".join(rows) + tip + "\n\nfonts 폴더를 열까요?"):
            _open_folder(fonts.LOCAL_DIR)

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
        if self.tabs.index(self.tabs.select()) == 1:
            self._start_long()
        else:
            self._start_short()

    def _start_short(self) -> None:
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
                if line.startswith("@@LONGREVIEW@@ "):
                    self.queue.put(("longreview", line[len("@@LONGREVIEW@@ "):].strip()))
                    continue
                if line.startswith("[") and "]" in line[:20]:
                    self.queue.put(("stage", line.strip()))
                self.queue.put(("log", line + ("\n" if sep == "\n" else ""), sep == "\r"))
        if buf:
            self.queue.put(("log", buf + "\n", False))

    def _stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        if not messagebox.askyesno("중지", "지금 작업을 멈출까요?\n다시 [만들기]를 누르면 "
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
                    self.root.title(f"{APP_TITLE} - {rest[0]}")
                elif kind == "review":
                    self.dialog = ReviewDialog(self.root, rest[0])
                elif kind == "longreview":
                    self.dialog = LongReviewDialog(self.root, rest[0])
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
        self.root.title(APP_TITLE)
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
        win.geometry("1240x640")
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

        for col, text in enumerate(["", "번호", "점수", "계정", "구간", "부제목", "제목", "하단 문구", "선정 이유"]):
            ttk.Label(body, text=text, font=("", 9, "bold")).grid(row=0, column=col, sticky="w",
                                                                 padx=4, pady=(0, 4))
        self.rows = []
        for i, h in enumerate(self.highlights, 1):
            on = tk.BooleanVar(value=True)
            rng = tk.StringVar(value=f"{review._hms(h.start)} ~ {review._hms(h.end)}")
            title = tk.StringVar(value=h.title.replace("\n", " / "))
            subt = tk.StringVar(value=h.sub_title)
            bottom = tk.StringVar(value=h.bottom)
            ttk.Checkbutton(body, variable=on).grid(row=i, column=0, padx=4, pady=3)
            ttk.Label(body, text=f"{i:02}").grid(row=i, column=1, padx=4)
            ttk.Label(body, text=f"{h.score}/10").grid(row=i, column=2, padx=4)
            acct = accounts.ACCOUNTS.get(h.account)
            ttk.Label(body, text=f"{acct.no}. {acct.name}" if acct else "-").grid(
                row=i, column=3, padx=4, sticky="w")
            ttk.Entry(body, textvariable=rng, width=14).grid(row=i, column=4, padx=4)
            ttk.Entry(body, textvariable=subt, width=12).grid(row=i, column=5, padx=4)
            ttk.Entry(body, textvariable=title, width=28).grid(row=i, column=6, padx=4)
            ttk.Entry(body, textvariable=bottom, width=14).grid(row=i, column=7, padx=4)
            ttk.Label(body, text=h.reason, wraplength=200, foreground="#555").grid(
                row=i, column=8, padx=4, sticky="w")
            self.rows.append((on, rng, title, bottom, subt))

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
        for h, (on, rng, title, bottom, subt) in zip(self.highlights, self.rows):
            h.title = "\n".join(p.strip() for p in title.get().split("/") if p.strip())
            h.bottom = bottom.get().strip()
            h.sub_title = subt.get().strip()
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


class LongReviewDialog:
    """롱폼 편집 순서표를 보고 순서·구간·챕터를 고치는 창."""

    COLS = ("on", "chapter", "clip", "range", "len", "note")

    def __init__(self, parent: tk.Tk, path: str):
        from .longform import Edl

        self.path = path
        self.edl = Edl.load(path)
        self.win = win = tk.Toplevel(parent)
        win.title("롱폼 편집 순서표")
        win.geometry("1180x720")
        win.transient(parent)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", self._done)

        top = ttk.Frame(win, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="영상 제목").grid(row=0, column=0, sticky="w")
        self.title = tk.StringVar(value=self.edl.title)
        ttk.Entry(top, textvariable=self.title, width=60).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(top, text="썸네일 문구 (줄바꿈은 /)").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.thumb = tk.StringVar(value=self.edl.thumbnail_text.replace("\n", " / "))
        ttk.Entry(top, textvariable=self.thumb, width=60).grid(row=1, column=1, sticky="w", padx=6,
                                                               pady=(4, 0))
        ttk.Label(win, text="위에서부터 영상에 나오는 순서예요. 줄을 고르고 [위로]/[아래로]로 순서를, "
                            "아래 칸에서 챕터·구간·메모를 고칠 수 있어요. 더블클릭하면 넣기/빼기.",
                  padding=(10, 0)).pack(anchor="w")

        mid = ttk.Frame(win, padding=(10, 4))
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=self.COLS, show="headings", selectmode="browse")
        for col, text, width in [("on", "사용", 50), ("chapter", "챕터", 170), ("clip", "촬영본", 220),
                                 ("range", "구간", 150), ("len", "길이", 60), ("note", "메모", 420)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w", stretch=col == "note")
        sb = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("off", foreground="#999")
        self.tree.bind("<<TreeviewSelect>>", self._load_row)
        self.tree.bind("<Double-1>", lambda e: self._toggle())

        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=(8, 0))
        for text, cmd in [("위로", lambda: self._move(-1)), ("아래로", lambda: self._move(1)),
                          ("넣기 / 빼기", self._toggle), ("촬영본 열어 보기", self._open_clip)]:
            ttk.Button(side, text=text, command=cmd, width=16).pack(fill="x", pady=2)

        ed = ttk.Frame(win, padding=(10, 4))
        ed.pack(fill="x")
        self.f_chapter, self.f_start, self.f_end, self.f_note = (tk.StringVar() for _ in range(4))
        for k, (label, var, width) in enumerate([("챕터", self.f_chapter, 18), ("시작", self.f_start, 9),
                                                 ("끝", self.f_end, 9), ("메모", self.f_note, 50)]):
            ttk.Label(ed, text=label).grid(row=0, column=k * 2, padx=(0 if k == 0 else 8, 4))
            ttk.Entry(ed, textvariable=var, width=width).grid(row=0, column=k * 2 + 1)
        ttk.Button(ed, text="고친 내용 적용", command=self._apply).grid(row=0, column=8, padx=8)

        if self.edl.dropped:
            df = ttk.LabelFrame(win, text=" AI가 뺀 구간 (참고) ", padding=6)
            df.pack(fill="x", padx=10)
            box = tk.Text(df, height=4, wrap="word", foreground="#555")
            for d in self.edl.dropped:
                c = d.get("clip", 0)
                name = os.path.basename(self.edl.clips[c]) if 0 <= c < len(self.edl.clips) else "?"
                box.insert("end", f"{name}  {self._tc(d['start'])} ~ {self._tc(d['end'])}  "
                                  f"{d.get('reason', '')}\n")
            box.configure(state="disabled")
            box.pack(fill="x")

        bf = ttk.Frame(win, padding=10)
        bf.pack(fill="x")
        self.total = ttk.Label(bf, text="")
        self.total.pack(side="left")
        ttk.Button(bf, text="이대로 롱폼 만들기", style="Big.TButton",
                   command=self._done).pack(side="right")

        self.rows: dict[str, list] = {}
        for ch in self.edl.chapters:
            for seg in ch.segments:
                self._insert("end", [ch.title, seg])
        self._refresh_total()

    @staticmethod
    def _tc(t: float) -> str:
        from .longform import _tc
        return _tc(t)

    def _values(self, row) -> tuple:
        title, seg = row
        return ("✔" if seg.on else "✘", title, os.path.basename(self.edl.clips[seg.clip]),
                f"{self._tc(seg.start)} ~ {self._tc(seg.end)}", f"{seg.end - seg.start:.0f}초", seg.note)

    def _insert(self, index, row) -> None:
        iid = self.tree.insert("", index, values=self._values(row),
                               tags=() if row[1].on else ("off",))
        self.rows[iid] = row

    def _redraw(self, iid: str) -> None:
        row = self.rows[iid]
        self.tree.item(iid, values=self._values(row), tags=() if row[1].on else ("off",))
        self._refresh_total()

    def _refresh_total(self) -> None:
        from .longform import _hms
        segs = [r[1] for r in self.rows.values() if r[1].on]
        total = sum(s.end - s.start for s in segs)
        self.total.configure(text=f"넣는 장면 {len(segs)}개 · 약 {_hms(total)} (무음을 자르면 더 짧아져요)")

    def _selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _load_row(self, _event=None) -> None:
        iid = self._selected()
        if not iid:
            return
        title, seg = self.rows[iid]
        self.f_chapter.set(title)
        self.f_start.set(self._tc(seg.start))
        self.f_end.set(self._tc(seg.end))
        self.f_note.set(seg.note)

    def _apply(self) -> None:
        from .longform import _sec
        iid = self._selected()
        if not iid:
            return
        row = self.rows[iid]
        seg = row[1]
        try:
            a, b = _sec(self.f_start.get()), _sec(self.f_end.get())
        except ValueError:
            messagebox.showwarning("구간", "시간은 1:05.3 처럼 적어 주세요.", parent=self.win)
            return
        if b <= a:
            messagebox.showwarning("구간", "끝이 시작보다 뒤여야 해요.", parent=self.win)
            return
        seg.start, seg.end, seg.note = a, b, self.f_note.get().strip()
        row[0] = self.f_chapter.get().strip() or row[0]
        self._redraw(iid)

    def _move(self, step: int) -> None:
        iid = self._selected()
        if iid:
            self.tree.move(iid, "", max(self.tree.index(iid) + step, 0))
            self.tree.see(iid)

    def _toggle(self) -> None:
        iid = self._selected()
        if iid:
            self.rows[iid][1].on = not self.rows[iid][1].on
            self._redraw(iid)

    def _open_clip(self) -> None:
        iid = self._selected()
        if iid:
            _open_folder(self.edl.clips[self.rows[iid][1].clip])  # 기본 플레이어로 열기

    def _done(self) -> None:
        from .longform import Chapter

        chapters: list = []
        for iid in self.tree.get_children(""):
            title, seg = self.rows[iid]
            if not chapters or chapters[-1].title != title:
                chapters.append(Chapter(title))
            chapters[-1].segments.append(seg)
        self.edl.chapters = chapters
        self.edl.title = self.title.get().strip()
        self.edl.thumbnail_text = "\n".join(p.strip() for p in self.thumb.get().split("/")
                                            if p.strip())
        self.edl.save(self.path)
        open(self.path + ".done", "w").close()
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
