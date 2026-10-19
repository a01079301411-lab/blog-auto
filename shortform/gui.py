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

from . import __version__, accounts, guides, review, settings
from .highlights import Highlight
from .styles import PRESETS

ROOT = settings.ROOT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
APP_TITLE = f"숏폼·롱폼 자동 편집기  v{__version__}"
REF_TYPES = [("사진·영상", "*.png *.jpg *.jpeg *.webp *.mp4 *.mov *.m4v *.webm"),
             ("모든 파일", "*.*")]
PLAN_TYPES = [("기획안", "*.hwp *.docx *.txt *.md"), ("모든 파일", "*.*")]
VIDEO_TYPES = [("영상 파일", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("모든 파일", "*.*")]

MODELS = [("small", "빠름 (small)"), ("medium", "보통 (medium)"), ("large-v3", "정확함 (large-v3)")]
UPLOADS = [("no", "안 함"), ("private", "비공개"), ("unlisted", "일부 공개"), ("public", "공개")]
STYLE_NAMES = {"green": "green (초록 강조 + 하단 문구)", "magenta": "magenta (분홍 강조)",
               "overlay": "overlay (영상 꽉 채우기)", "basic": "basic (16:9 그대로)"}


# ---------- 색 (캡컷처럼 어두운 화면 + 청록색 강조) ----------
BG = "#101014"        # 창 배경
PANEL = "#16161b"     # 탭 안쪽
CARD = "#1e1e24"      # 상자
FIELD = "#2a2a32"     # 입력 칸
LINE = "#34343d"
FG = "#f2f2f5"
SUB = "#9a9aa6"
ACCENT = "#20d5ec"
ACCENT_HOVER = "#62e6f6"
ACCENT_TEXT = "#04161a"
DANGER = "#ff6b78"
OK = "#5ee39b"
LOG_BG = "#0b0b0e"
LOG_FG = "#dcdce4"


def apply_theme(root: tk.Misc, family: str) -> None:
    """ttk 기본 테마를 어두운 캡컷 느낌으로 바꾼다."""
    style = ttk.Style(root)
    style.theme_use("clam")
    f = lambda size, bold=False: (family, size, "bold") if bold else (family, size)
    root.configure(background=BG)
    style.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=LINE,
                    lightcolor=CARD, darkcolor=CARD, troughcolor=FIELD, focuscolor=CARD,
                    selectbackground=ACCENT, selectforeground=ACCENT_TEXT, insertcolor=FG,
                    arrowcolor=FG, font=f(10))
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Sub.TLabel", background=BG, foreground=SUB)
    style.configure("Logo.TLabel", background=BG, foreground=FG, font=f(17, True))
    style.configure("Status.TLabel", background=BG, foreground=ACCENT, font=f(12, True))
    style.configure("Warn.TLabel", background=BG, foreground=DANGER, font=f(10, True))
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("Sub.Card.TLabel", background=CARD, foreground=SUB, font=f(9))
    style.configure("Title.Card.TLabel", background=CARD, foreground=FG, font=f(12, True))

    style.configure("TButton", background=FIELD, foreground=FG, borderwidth=0, padding=(14, 6),
                    focusthickness=0, relief="flat")
    style.map("TButton", background=[("disabled", CARD), ("pressed", LINE), ("active", LINE)],
              foreground=[("disabled", "#5c5c66")])
    style.configure("Soft.TButton", background="#173d44", foreground=ACCENT, font=f(10, True))
    style.map("Soft.TButton", background=[("pressed", "#1d4c55"), ("active", "#1d4c55")])
    style.configure("Link.TButton", background=CARD, foreground=ACCENT, padding=(0, 4),
                    font=f(10, True))
    style.map("Link.TButton", background=[("active", CARD), ("pressed", CARD)],
              foreground=[("active", ACCENT_HOVER)])
    for name in ("Accent.TButton", "Big.TButton"):
        style.configure(name, background=ACCENT, foreground=ACCENT_TEXT, font=f(13, True),
                        padding=(30, 12), borderwidth=0)
        style.map(name, background=[("disabled", "#1f4a51"), ("pressed", ACCENT_HOVER),
                                    ("active", ACCENT_HOVER)],
                  foreground=[("disabled", "#6f9aa0")])

    for name, bg in (("TCheckbutton", BG), ("Card.TCheckbutton", CARD)):
        style.configure(name, background=bg, foreground=FG, indicatorbackground=FIELD,
                        indicatorforeground=ACCENT_TEXT, indicatormargin=(0, 0, 8, 0),
                        padding=(0, 2))
        style.map(name, background=[("active", bg)],
                  indicatorbackground=[("selected", ACCENT), ("active", LINE)],
                  indicatorforeground=[("selected", ACCENT_TEXT)])

    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=FIELD, foreground=FG, background=FIELD,
                        bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD, padding=(6, 4),
                        arrowcolor=FG)
        style.map(name, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0),
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure("TNotebook.Tab", background=BG, foreground=SUB, padding=(28, 10),
                    font=f(12, True), borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.map("TNotebook.Tab", background=[("selected", PANEL), ("active", CARD)],
              foreground=[("selected", ACCENT), ("active", FG)],
              lightcolor=[("selected", PANEL)], bordercolor=[("selected", PANEL)],
              padding=[("selected", (28, 10))], expand=[("selected", (0, 0, 0, 0))])

    style.configure("Accent.Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD,
                    bordercolor=CARD, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=LOG_BG,
                    bordercolor=LOG_BG, arrowcolor=SUB, lightcolor=FIELD, darkcolor=FIELD)
    style.configure("Horizontal.TScale", background=ACCENT, troughcolor=FIELD)
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG,
                    rowheight=28, borderwidth=0)
    style.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", ACCENT_TEXT)])
    style.configure("Treeview.Heading", background=CARD, foreground=SUB, font=f(10, True),
                    borderwidth=0, padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", LINE)])
    style.configure("TLabelframe", background=CARD, bordercolor=LINE)
    style.configure("TLabelframe.Label", background=CARD, foreground=FG, font=f(10, True))


def style_field(widget: tk.Widget) -> None:
    """tk 목록·글 칸을 어두운 테마에 맞춘다."""
    widget.configure(background=FIELD, foreground=FG, relief="flat", borderwidth=0,
                     highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
                     selectbackground=ACCENT, selectforeground=ACCENT_TEXT)
    if isinstance(widget, tk.Text):
        widget.configure(insertbackground=FG, padx=8, pady=6)


LOG_DIR = os.path.join(ROOT, "logs")
LAST_LOG = os.path.join(LOG_DIR, "마지막_실행기록.txt")
BGM_SOURCES = {"auto": "자동 (직접 만든 곡, 저작권 안전)", "folder": "bgm 폴더의 음악",
               "none": "안 깔기"}


def _bgm_key(text: str) -> str:
    return next((k for k, v in BGM_SOURCES.items() if v == text), "auto")


LENGTHS = ["AI가 정해요", "3분", "5분", "8분", "10분", "15분", "20분", "30분"]


def _num(text: str) -> float:
    """'10분', '8.5' → 숫자. 숫자가 없으면 0 (AI가 정함)."""
    import re
    m = re.search(r"\d+(?:\.\d+)?", str(text))
    return float(m.group()) if m else 0.0


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
        root.geometry("1500x900")
        root.minsize(1200, 720)
        if sys.platform == "win32":
            try:
                root.state("zoomed")  # 화면 가득 (진행 기록이 크게 보이게)
            except tk.TclError:
                pass
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
        base = tkfont.nametofont("TkDefaultFont").actual()["family"]
        self.big = tkfont.Font(family=base, size=12, weight="bold")
        self.title_font = tkfont.Font(family=base, size=11, weight="bold")
        self.mono = tkfont.Font(family="Consolas" if sys.platform == "win32" else "TkFixedFont",
                                size=11)
        apply_theme(self.root, base)

    def _card(self, parent, title: str, hint: str = "") -> ttk.Frame:
        """제목이 있는 둥근 느낌의 어두운 상자. 안쪽 프레임을 돌려준다."""
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(16, 12))
        head = ttk.Frame(outer, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text=title, style="Title.Card.TLabel").pack(side="left")
        if hint:
            ttk.Label(head, text=hint, style="Sub.Card.TLabel").pack(side="left", padx=(10, 0))
        body = ttk.Frame(outer, style="Card.TFrame")
        body.pack(fill="both", expand=True)
        body.outer = outer
        return body

    def _advanced(self, card: ttk.Frame, title: str) -> ttk.Frame:
        """'고급 설정' 버튼을 누르면 뜨는 작은 창 (메인 화면과 진행 기록 크기는 그대로)."""
        win = tk.Toplevel(self.root, background=BG)
        win.withdraw()
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        box = ttk.Frame(win, style="Card.TFrame", padding=(20, 16))
        box.pack(fill="both", expand=True)
        foot = ttk.Frame(win, padding=(20, 0, 20, 16))
        foot.pack(fill="x")
        ttk.Button(foot, text="확인", style="Soft.TButton", command=win.withdraw).pack(side="right")

        def show():
            win.deiconify()
            win.lift()
            x = self.root.winfo_rootx() + self.root.winfo_width() - win.winfo_reqwidth() - 60
            win.geometry(f"+{max(x, 0)}+{self.root.winfo_rooty() + 120}")
        ttk.Button(card, text="고급 설정  ›", style="Link.TButton", command=show).pack(
            anchor="w", pady=(10, 0))
        return box

    def _ref_card(self, parent) -> tk.Listbox:
        """레퍼런스 칸: 링크 붙여넣기, 스크린샷·짧은 영상 추가."""
        rf = self._card(parent, "레퍼런스", "이런 느낌으로! (선택)")
        row = ttk.Frame(rf, style="Card.TFrame")
        row.pack(fill="x")
        link = tk.StringVar()
        entry = ttk.Entry(row, textvariable=link)
        entry.pack(side="left", fill="x", expand=True)
        box = tk.Listbox(rf, height=3, activestyle="none", selectmode="extended")
        style_field(box)

        def add_link(_e=None):
            text = link.get().strip()
            if text and text not in box.get(0, "end"):
                box.insert("end", text)
            link.set("")
        entry.bind("<Return>", add_link)
        ttk.Button(row, text="링크 추가", style="Soft.TButton", command=add_link).pack(
            side="left", padx=(6, 0))
        box.pack(fill="x", pady=(6, 0))
        foot = ttk.Frame(rf, style="Card.TFrame")
        foot.pack(fill="x", pady=(6, 0))

        def add_files():
            for p in filedialog.askopenfilenames(title="레퍼런스 사진·영상 고르기",
                                                 filetypes=REF_TYPES):
                p = os.path.abspath(p)
                if p not in box.get(0, "end"):
                    box.insert("end", p)
        ttk.Button(foot, text="+  스크린샷·영상", command=add_files).pack(side="left")
        ttk.Button(foot, text="빼기", command=lambda: [box.delete(i) for i in
                                                     reversed(box.curselection())]).pack(
            side="left", padx=6)
        ttk.Label(foot, text="링크·캡처·짧은 영상", style="Sub.Card.TLabel").pack(
            side="right")
        return box

    def _guide_key(self) -> str:
        name = self.guide_var.get()
        return next((k for k, g in self.guide_list.items() if g["name"] == name), "lecture")

    def _on_guide(self, _event=None) -> None:
        """영상 종류를 바꾸면 영상 설명·인물 소개를 그 종류의 기본값으로 채운다."""
        g = self.guide_list[self._guide_key()]
        if g.get("context") or self._guide_key() == "custom":
            self.context.delete("1.0", "end")
            self.context.insert("1.0", g.get("context", ""))
        self.speaker_var.set(g.get("speaker", ""))
        if self._guide_key() != "lecture" and any(v.get() for v in self.acct_vars.values()):
            for v in self.acct_vars.values():  # 코시 계정 디자인은 강의 영상용
                v.set(False)
            self._append("영상 종류를 바꿔서 코시 인스타 계정 선택을 풀었어요 "
                         "(계정 가이드는 강의 영상용이에요).\n")
        self._append(f"영상 종류: {g['name']} (영상 설명·인물 소개는 [고급 설정]에서 고칠 수 있어요)\n")

    def _row(self, parent, label: str) -> ttk.Frame:
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, style="Card.TLabel", width=12).pack(side="left")
        return row

    def _check(self, parent, text: str, value: bool) -> tk.BooleanVar:
        var = tk.BooleanVar(value=value)
        ttk.Checkbutton(parent, text=text, variable=var, style="Card.TCheckbutton").pack(
            anchor="w", pady=2)
        return var

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=(16, 12, 16, 14))
        outer.pack(fill="both", expand=True)
        # 왼쪽: 탭·설정·실행 버튼 / 오른쪽: 위에서 아래까지 진행 기록
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2, minsize=400)
        outer.rowconfigure(0, weight=1)
        main = ttk.Frame(outer)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        # 위: 이름 + 숏폼/롱폼 탭
        top = ttk.Frame(main)
        top.pack(fill="x")
        ttk.Label(top, text="✂  자동 편집기", style="Logo.TLabel").pack(side="left")
        ttk.Label(top, text=f"v{__version__}", style="Sub.TLabel").pack(side="left", padx=(8, 0),
                                                                        pady=(6, 0))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="x", pady=(10, 0))
        short = ttk.Frame(self.tabs, style="Panel.TFrame", padding=12)
        self.long_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=12)
        self.tabs.add(short, text="숏폼 만들기")
        self.tabs.add(self.long_tab, text="롱폼 만들기")
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab)
        self._build_short(short)
        self._build_long(self.long_tab)

        if not os.environ.get("ANTHROPIC_API_KEY"):
            kf = ttk.Frame(main)
            kf.pack(fill="x", pady=(8, 0))
            ttk.Label(kf, text="Claude API 키", style="Warn.TLabel").pack(side="left")
            self.key_var = tk.StringVar()
            ttk.Entry(kf, textvariable=self.key_var, show="•", width=50).pack(side="left", padx=8)
            ttk.Button(kf, text="저장", command=self._save_key).pack(side="left")
        else:
            self.key_var = None

        # 실행 줄
        rf = ttk.Frame(main)
        rf.pack(fill="x", pady=(12, 0))
        self.start_btn = ttk.Button(rf, text="▶  숏폼 만들기", style="Accent.TButton",
                                    command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(rf, text="■  중지", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0), ipady=4)
        self.open_btn = ttk.Button(rf, text="결과 폴더 열기", command=self._open_output,
                                   state="disabled")
        self.open_btn.pack(side="left", padx=(8, 0), ipady=4)
        self.preview_btn = ttk.Button(rf, text="결과 미리보기", command=self._show_results,
                                      state="disabled")
        self.preview_btn.pack(side="left", padx=(8, 0), ipady=4)
        self.status = ttk.Label(rf, text="", style="Status.TLabel")
        self.status.pack(side="left", padx=(18, 0))
        self.progress_text = ttk.Label(rf, text="", style="Sub.TLabel")
        self.progress_text.pack(side="left", padx=(12, 0))

        self.bar = ttk.Progressbar(main, mode="determinate", maximum=100,
                                   style="Accent.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(12, 8))

        # 오른쪽: 진행 기록 (위에서 아래까지 길게)
        lf = ttk.Frame(outer, style="Card.TFrame", padding=(14, 12))
        lf.grid(row=0, column=1, sticky="nsew")
        ttk.Label(lf, text="진행 기록", style="Title.Card.TLabel").pack(anchor="w", pady=(0, 6))
        inner = ttk.Frame(lf, style="Card.TFrame")
        inner.pack(fill="both", expand=True)
        self.log = tk.Text(inner, height=10, width=40, font=self.mono, wrap="word", state="disabled",
                           background=LOG_BG, foreground=LOG_FG, insertbackground=FG,
                           relief="flat", borderwidth=0, padx=12, pady=10,
                           highlightthickness=0, spacing1=2, spacing3=2)
        self.log.tag_configure("stage", foreground=ACCENT, font=self.title_font)
        self.log.tag_configure("error", foreground=DANGER)
        self.log.tag_configure("done", foreground=OK)
        sb = ttk.Scrollbar(inner, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    def _build_short(self, tab: ttk.Frame) -> None:
        c = self.cfg
        tab.columnconfigure(0, weight=3, uniform="col")
        tab.columnconfigure(1, weight=2, uniform="col")

        # 왼쪽: 영상 + 계정
        left = ttk.Frame(tab, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        vf = self._card(left, "① 영상", "여러 개 넣으면 차례로 만들어요")
        vf.outer.pack(fill="x")
        self.videos = tk.Listbox(vf, height=4, activestyle="none")
        style_field(self.videos)
        self.videos.pack(fill="x")
        vb = ttk.Frame(vf, style="Card.TFrame")
        vb.pack(fill="x", pady=(8, 0))
        ttk.Button(vb, text="+  영상 추가", style="Soft.TButton",
                   command=self._pick_videos).pack(side="left")
        ttk.Button(vb, text="빼기", command=self._remove_video).pack(side="left", padx=6)

        af = self._card(left, "② 인스타 계정", "고르면 코시 가이드대로 만들어요")
        af.outer.pack(fill="x", pady=(10, 0))
        chosen = set(accounts.parse(c.get("accounts", "")))
        self.acct_vars: dict[int, tk.BooleanVar] = {}
        grid = ttk.Frame(af, style="Card.TFrame")
        grid.pack(fill="x")
        for k, (no, a) in enumerate(accounts.ACCOUNTS.items()):
            var = tk.BooleanVar(value=no in chosen)
            ttk.Checkbutton(grid, text=f"{no}. {a.name}", variable=var,
                            style="Card.TCheckbutton").grid(row=k // 2, column=k % 2, sticky="w",
                                                            padx=(0, 16), pady=1)
            self.acct_vars[no] = var
        pf = ttk.Frame(af, style="Card.TFrame")
        pf.pack(fill="x", pady=(8, 0))
        ttk.Label(pf, text="계정당", style="Card.TLabel").pack(side="left")
        self.per_var = tk.StringVar(value=c.get("per_account", "3"))
        ttk.Spinbox(pf, from_=1, to=10, textvariable=self.per_var, width=4).pack(side="left", padx=6)
        ttk.Label(pf, text="개", style="Card.TLabel").pack(side="left")
        ttk.Button(pf, text="글꼴 확인", command=self._check_fonts).pack(side="right")

        # 오른쪽: 설정
        right = ttk.Frame(tab, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        sf = self._card(right, "③ 설정")
        sf.outer.pack(fill="x")
        self.short_refs = self._ref_card(right)
        self.short_refs.master.outer.pack(fill="x", pady=(10, 0))
        row = self._row(sf, "영상 종류")
        self.guide_list = guides.load()
        names = {k: g["name"] for k, g in self.guide_list.items()}
        self.guide_var = tk.StringVar(value=names.get(c.get("guide", "lecture"), names["lecture"]))
        box = ttk.Combobox(row, textvariable=self.guide_var, values=list(names.values()),
                           state="readonly", width=26)
        box.pack(side="left", fill="x", expand=True)
        box.bind("<<ComboboxSelected>>", self._on_guide)
        row = self._row(sf, "숏폼 개수")
        self.count_var = tk.StringVar(value=c["count"])
        ttk.Spinbox(row, from_=1, to=30, textvariable=self.count_var, width=5).pack(side="left")
        ttk.Label(row, text="계정 안 고를 때", style="Sub.Card.TLabel").pack(side="left", padx=8)
        row = self._row(sf, "길이(초)")
        self.min_var = tk.StringVar(value=c["min_len"])
        self.max_var = tk.StringVar(value=c["max_len"])
        ttk.Spinbox(row, from_=5, to=180, textvariable=self.min_var, width=5).pack(side="left")
        ttk.Label(row, text="~", style="Card.TLabel").pack(side="left", padx=6)
        ttk.Spinbox(row, from_=10, to=180, textvariable=self.max_var, width=5).pack(side="left")
        row = self._row(sf, "디자인")
        names = [STYLE_NAMES.get(k, k) for k in PRESETS]
        self.style_var = tk.StringVar(value=STYLE_NAMES.get(c["style"], c["style"]))
        ttk.Combobox(row, textvariable=self.style_var, values=names, width=26).pack(
            side="left", fill="x", expand=True)

        self.flags = {}
        ttk.Frame(sf, style="Card.TFrame", height=6).pack()
        self.flags["focus"] = self._check(sf, "얼굴 따라가기", c["focus"] == "auto")
        self.flags["burned_subs"] = self._check(sf, "원본에 자막 있으면 그대로 쓰기",
                                                c["burned_subs"] in ("auto", "yes"))
        self.flags["subtitles"] = self._check(sf, "자막 넣기", c["subtitles"].lower() != "no")
        self.flags["thumbnail"] = self._check(sf, "썸네일 만들기", c["thumbnail"].lower() == "yes")
        self.flags["retention"] = self._check(sf, "훅 자막·중간 한마디·진행 막대 (시청 지속)",
                                              c.get("retention", "yes").lower() != "no")
        row = self._row(sf, "배경음악")
        self.bgm_src = tk.StringVar(value=BGM_SOURCES.get(c.get("bgm_source", "auto"),
                                                          BGM_SOURCES["auto"]))
        ttk.Combobox(row, textvariable=self.bgm_src, values=list(BGM_SOURCES.values()),
                     state="readonly", width=24).pack(side="left")
        ttk.Button(sf, text="📈 성과 기록 열기 (조회수 적기)", style="Link.TButton",
                   command=self._open_performance).pack(anchor="w", pady=(6, 0))

        adv = self._advanced(sf, "숏폼 고급 설정")
        ttk.Label(adv, text="영상 설명 (누가, 무슨 내용인지)", style="Card.TLabel").pack(anchor="w")
        self.context = tk.Text(adv, height=3, width=40, wrap="word")
        style_field(self.context)
        self.context.insert("1.0", c["context"])
        self.context.pack(fill="x", pady=(2, 6))
        row = self._row(adv, "인물 소개")
        self.speaker_var = tk.StringVar(value=c["speaker"])
        ttk.Entry(row, textvariable=self.speaker_var).pack(side="left", fill="x", expand=True)
        row = self._row(adv, "음성 인식")
        self.model_var = tk.StringVar(value=dict(MODELS).get(c["model"], c["model"]))
        ttk.Combobox(row, textvariable=self.model_var, values=[v for _, v in MODELS],
                     state="readonly", width=18).pack(side="left")
        row = self._row(adv, "유튜브 업로드")
        self.upload_var = tk.StringVar(value=dict(UPLOADS).get(c["upload"], "안 함"))
        ttk.Combobox(row, textvariable=self.upload_var, values=[v for _, v in UPLOADS],
                     state="readonly", width=10).pack(side="left")
        row = self._row(adv, "음악 볼륨")
        try:
            vol = float(c["bgm_volume"])
        except ValueError:
            vol = 0.15
        self.bgm_var = tk.DoubleVar(value=vol)
        ttk.Scale(row, from_=0, to=0.5, variable=self.bgm_var, length=120).pack(side="left")
        ttk.Button(row, text="폴더", command=lambda: _open_folder(os.path.join(ROOT, "bgm"))).pack(
            side="left", padx=8)
        self.flags["fix_subtitles"] = self._check(adv, "자막 오타 교정 (Claude)",
                                                  c["fix_subtitles"].lower() == "yes")
        self.flags["review"] = self._check(adv, "만들기 전에 목록 보고 고르기",
                                           c["review"].lower() == "yes")

    # ---------- 롱폼 탭 ----------

    def _build_long(self, tab: ttk.Frame) -> None:
        c = settings.LONG_DEFAULTS
        try:
            c = settings.load_long()
        except Exception:
            pass
        tab.columnconfigure(0, weight=3, uniform="col")
        tab.columnconfigure(1, weight=2, uniform="col")

        left = ttk.Frame(tab, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cf = self._card(left, "① 촬영본", "찍은 순서대로 놓으면 AI가 더 정확해요")
        cf.outer.pack(fill="x")
        self.clips = tk.Listbox(cf, height=5, activestyle="none", selectmode="extended")
        style_field(self.clips)
        self.clips.pack(fill="x")
        cb = ttk.Frame(cf, style="Card.TFrame")
        cb.pack(fill="x", pady=(8, 0))
        ttk.Button(cb, text="+  영상 추가", style="Soft.TButton",
                   command=self._pick_clips).pack(side="left")
        ttk.Button(cb, text="+  폴더 추가", style="Soft.TButton",
                   command=self._pick_clip_folder).pack(side="left", padx=6)
        for text, cmd in [("빼기", self._remove_clip), ("▼", lambda: self._move_clip(1)),
                          ("▲", lambda: self._move_clip(-1))]:
            ttk.Button(cb, text=text, command=cmd, width=4 if len(text) == 1 else None).pack(
                side="right", padx=(6, 0))

        pf = self._card(left, "② 기획안", "hwp · docx · txt 파일, 또는 아래에 붙여 넣기")
        pf.outer.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(pf, style="Card.TFrame")
        row.pack(fill="x")
        self.plan_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.plan_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="파일 고르기", style="Soft.TButton",
                   command=self._pick_plan).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="지우기", command=lambda: self.plan_var.set("")).pack(side="left", padx=6)
        self.plan_text = tk.Text(pf, height=3, wrap="word")
        style_field(self.plan_text)
        self.plan_text.pack(fill="x", pady=(8, 0))

        right = ttk.Frame(tab, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        sf = self._card(right, "③ 설정")
        sf.outer.pack(fill="x")
        self.long_refs = self._ref_card(right)
        self.long_refs.master.outer.pack(fill="x", pady=(10, 0))
        row = self._row(sf, "영상 이름")
        self.long_title = tk.StringVar()
        ttk.Entry(row, textvariable=self.long_title).pack(side="left", fill="x", expand=True)
        row = self._row(sf, "영상 길이")
        mins = c["long_minutes"].strip()
        self.long_minutes = tk.StringVar(
            value=f"{float(mins):g}분" if mins and _num(mins) else LENGTHS[0])
        ttk.Combobox(row, textvariable=self.long_minutes, values=LENGTHS, width=12).pack(
            side="left")
        ttk.Label(row, text="직접 적어도 돼요 (예: 12분)", style="Sub.Card.TLabel").pack(
            side="left", padx=8)
        ttk.Frame(sf, style="Card.TFrame", height=6).pack()
        self.long_flags = {}
        yes = lambda k: c[k].lower() == "yes"
        self.long_flags["long_commerce"] = self._check(sf, "유료광고 포함 (코시 커머스 편)",
                                                       yes("long_commerce"))
        self.long_flags["long_subtitles"] = self._check(sf, "자막 넣기", yes("long_subtitles"))
        self.long_flags["long_thumbnail"] = self._check(sf, "썸네일 만들기", yes("long_thumbnail"))

        adv = self._advanced(sf, "롱폼 고급 설정")
        ttk.Label(adv, text="채널 설명 (세계관, 출연자)", style="Card.TLabel").pack(anchor="w")
        self.long_context = tk.Text(adv, height=3, width=40, wrap="word")
        style_field(self.long_context)
        self.long_context.insert("1.0", c["long_context"])
        self.long_context.pack(fill="x", pady=(2, 6))
        row = self._row(adv, "음성 인식")
        self.long_model = tk.StringVar(value=dict(MODELS).get(c["long_model"], c["long_model"]))
        ttk.Combobox(row, textvariable=self.long_model, values=[v for _, v in MODELS],
                     state="readonly", width=18).pack(side="left")
        row = self._row(adv, "출력 화질")
        self.long_res = tk.StringVar(value={"2160": "4K (오래 걸림)"}.get(c["long_resolution"],
                                                                       "1080p (기본)"))
        ttk.Combobox(row, textvariable=self.long_res, values=["1080p (기본)", "4K (오래 걸림)"],
                     state="readonly", width=16).pack(side="left")
        row = self._row(adv, "배경음악")
        self.long_bgm_src = tk.StringVar(value=BGM_SOURCES.get(c.get("long_bgm_source", "auto"),
                                                               BGM_SOURCES["auto"]))
        ttk.Combobox(row, textvariable=self.long_bgm_src, values=list(BGM_SOURCES.values()),
                     state="readonly", width=24).pack(side="left")
        row = self._row(adv, "음악 볼륨")
        try:
            vol = float(c["long_bgm_volume"])
        except ValueError:
            vol = 0.10
        self.long_bgm = tk.DoubleVar(value=vol)
        ttk.Scale(row, from_=0, to=0.4, variable=self.long_bgm, length=120).pack(side="left")
        for key, text in [("long_jumpcut", "말 사이 긴 무음 자르기"),
                          ("long_fix_subtitles", "자막 오타 교정"),
                          ("long_chapter_titles", "챕터 제목 띄우기"),
                          ("long_frames", "장면 사진도 AI에게 보여주기"),
                          ("long_review", "만들기 전에 순서표 고치기")]:
            self.long_flags[key] = self._check(adv, text, yes(key))
        self.replan = self._check(adv, "편집 순서 새로 짜기 (이번 한 번)", False)

    def _on_tab(self, _event=None) -> None:
        if not hasattr(self, "start_btn"):
            return
        long = self.tabs.index(self.tabs.select()) == 1
        self.start_btn.configure(text="▶  롱폼 만들기" if long else "▶  숏폼 만들기")

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
            "long_minutes": f"{_num(self.long_minutes.get()):g}",
            "long_model": {v: k for k, v in MODELS}.get(self.long_model.get(), "small"),
            "long_bgm_volume": f"{self.long_bgm.get():.2f}",
            "long_resolution": "2160" if self.long_res.get().startswith("4K") else "auto",
            "long_bgm_source": _bgm_key(self.long_bgm_src.get()),
        })
        return vals

    def _start_long(self) -> None:
        clips = list(self.clips.get(0, "end"))
        if not clips:
            messagebox.showinfo(APP_TITLE, "먼저 [영상 추가...]나 [폴더 추가...]로 촬영본을 넣어 주세요.")
            return
        # '영상 이름'에 "13분"처럼 길이를 적었으면 영상 길이로 쓴다
        import re
        if _num(self.long_minutes.get()) == 0 and \
                re.fullmatch(r"\s*\d+(\.\d+)?\s*분\s*", self.long_title.get()):
            self.long_minutes.set(self.long_title.get().strip())
            self._append(f"영상 길이를 {self.long_title.get().strip()}으로 맞춰요.\n")
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
        for r in self.long_refs.get(0, "end"):
            argv += ["--ref", r]
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
            "guide": self._guide_key(),
            "accounts": ",".join(str(n) for n, v in self.acct_vars.items() if v.get()),
            "per_account": self.per_var.get().strip(),
            "style": style, "count": self.count_var.get().strip(),
            "min_len": self.min_var.get().strip(), "max_len": self.max_var.get().strip(),
            "context": " ".join(self.context.get("1.0", "end").split()),
            "speaker": self.speaker_var.get().strip(),
            "model": {v: k for k, v in MODELS}.get(self.model_var.get(), "small"),
            "focus": focus, "fix_subtitles": yes("fix_subtitles"), "review": yes("review"),
            "burned_subs": "auto" if self.flags["burned_subs"].get() else "no",
            "thumbnail": yes("thumbnail"), "subtitles": yes("subtitles"),
            "retention": yes("retention"), "bgm_source": _bgm_key(self.bgm_src.get()),
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
            self.queue.put(("batch", n - 1, len(videos)))
            self.queue.put(("log", f"\n===== {video} =====\n", False))
            self.last_output = settings.output_dir(video)
            kwargs = {"creationflags": NO_WINDOW} if sys.platform == "win32" else \
                {"start_new_session": True}
            self.proc = subprocess.Popen(
                [_python(), "-m", "shortform", "auto", video,
                 *[a for r in self.short_refs.get(0, "end") for a in ("--ref", r)]],
                cwd=ROOT, env=env,
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
        # 받은 출력은 파일로도 남긴다 (창에서 놓친 오류도 확인할 수 있게)
        os.makedirs(LOG_DIR, exist_ok=True)
        try:
            record = open(LAST_LOG, "w", encoding="utf-8")
        except OSError:
            record = None
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not chunk:
                break
            text = dec.decode(chunk)
            if record:
                record.write(text.replace("\r\n", "\n"))
                record.flush()
            buf += text
            while True:
                i = min((k for k in (buf.find("\n"), buf.find("\r")) if k >= 0), default=-1)
                if i < 0:
                    break
                if buf[i] == "\r" and i + 1 == len(buf):
                    break  # 다음 글자가 \n인지 보고 판단 (Windows 줄바꿈은 \r\n)
                if buf[i] == "\r" and buf[i + 1] == "\n":
                    line, sep, buf = buf[:i], "\n", buf[i + 2:]  # Windows 줄바꿈: 덮어쓰기 아님
                else:
                    line, sep, buf = buf[:i], buf[i], buf[i + 1:]
                if line.startswith("@@REVIEW@@ "):
                    self.queue.put(("review", line[len("@@REVIEW@@ "):].strip()))
                    continue
                if line.startswith("@@PROGRESS@@ "):
                    parts = line.split(" ", 2)
                    try:
                        self.queue.put(("progress", float(parts[1]),
                                        parts[2] if len(parts) > 2 else ""))
                    except ValueError:
                        pass
                    continue
                if line.startswith("@@LONGREVIEW@@ "):
                    self.queue.put(("longreview", line[len("@@LONGREVIEW@@ "):].strip()))
                    continue
                if line.startswith("[") and "]" in line[:20]:
                    self.queue.put(("stage", line.strip()))
                self.queue.put(("log", line + ("\n" if sep == "\n" else ""), sep == "\r"))
        if buf.strip("\r"):
            self.queue.put(("log", buf.strip("\r") + "\n", False))
        if record:
            record.close()

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

    batch = (0, 1)

    def _set_running(self, running: bool) -> None:
        import time
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self.batch = (0, 1)
            self.started = time.time()
            self.bar.configure(value=0)
            self.progress_text.configure(text="준비 중...")
            self.open_btn.configure(state="disabled")
            self.preview_btn.configure(state="disabled")
        else:
            if self.last_output and os.path.isdir(self.last_output):
                self.open_btn.configure(state="normal")
                self.preview_btn.configure(state="normal")

    def _show_progress(self, value: float, label: str = "") -> None:
        """막대, %, 남은 시간 (여러 영상이면 전체 기준)."""
        import time
        k, n = self.batch
        total = (k + value) / max(n, 1)
        self.bar.configure(value=total * 100)
        elapsed = time.time() - getattr(self, "started", time.time())
        text = f"{total * 100:.0f}%"
        if label:
            text += f" · {label}"
        if total > 0.03 and elapsed > 20:
            left = elapsed * (1 - total) / total
            text += f" · 남은 시간 약 {_fmt_left(left)}"
        self.progress_text.configure(text=text)

    def _open_performance(self) -> None:
        from . import performance
        path = performance.ensure_file()
        messagebox.showinfo("성과 기록", "만든 숏폼이 한 줄씩 적혀 있어요.\n\n올린 뒤 '조회수', '평균 시청률(%)', "
                            "'좋아요', '링크' 칸을 채우고 저장하면, 다음 숏폼부터 잘된 숏폼의 공통점을 "
                            "따라 해요. (3개 이상 쌓이면 반영)\n\n유튜브 쇼츠 링크를 적어 두면 조회수는 "
                            "프로그램이 알아서 가져와요 (유튜브 연결이 되어 있을 때).")
        _open_folder(path)

    def _show_results(self) -> None:
        if self.last_output and os.path.isdir(self.last_output):
            self.results = ResultsDialog(self.root, self.last_output)  # 그림이 사라지지 않게 잡아 둔다

    def _open_output(self) -> None:
        if self.last_output and os.path.isdir(self.last_output):
            _open_folder(self.last_output)

    # ---------- 창 갱신 ----------

    def _append(self, text: str, replace_last: bool = False) -> None:
        self.log.configure(state="normal")
        if self._replacing:
            self.log.delete("end-1c linestart", "end-1c")
        line = text.strip()
        tag = ()
        if line.startswith("[") and not text.startswith(" "):
            tag = ("stage",)
        if "오류" in line or "실패" in line or "Error" in line:
            tag = ("error",)
        if line.startswith("완료") or line.startswith("완성"):
            tag = ("done",)
        self.log.insert("end", text, tag)
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
                elif kind == "batch":
                    self.batch = (rest[0], rest[1])
                elif kind == "progress":
                    self._show_progress(*rest)
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
            self.bar.configure(value=100)
            self.progress_text.configure(text="100% · 다 만들었어요")
            self._show_results()
        else:
            self.status.configure(text="오류가 났어요 (오른쪽 기록을 캡처해 주세요)")
            self._append(f"\n작업이 멈췄어요 (종료 코드 {code}).\n"
                         f"전체 기록 파일: {LAST_LOG}\n")

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
            self.queue.put(("log", f"[업데이트 확인] {msg or '최신 버전이에요.'} (v{__version__})\n",
                            False))
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


def _fmt_left(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}시간 {seconds % 3600 // 60}분"
    if seconds >= 60:
        return f"{seconds // 60}분"
    return f"{seconds}초"


class ResultsDialog:
    """다 만든 영상을 썸네일로 보여 주고 바로 재생하는 창."""

    def __init__(self, parent: tk.Tk, folder: str):
        videos = []
        for root_dir, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ("작업파일", "_배경음악", ".미리보기")]
            videos += [os.path.join(root_dir, f) for f in files
                       if f.lower().endswith(".mp4") and ".tmp" not in f]
        videos.sort()
        self.win = win = tk.Toplevel(parent, background=BG)
        win.title(f"결과 미리보기 ({len(videos)}개)")
        win.geometry("1180x760")
        win.transient(parent)
        head = ttk.Frame(win, padding=(16, 12))
        head.pack(fill="x")
        ttk.Label(head, text=f"만든 영상 {len(videos)}개", style="Logo.TLabel").pack(side="left")
        ttk.Label(head, text="  누르면 재생돼요", style="Sub.TLabel").pack(side="left", pady=(6, 0))
        ttk.Button(head, text="폴더 열기", command=lambda: _open_folder(folder)).pack(side="right")
        outer = ttk.Frame(win)
        outer.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        canvas = tk.Canvas(outer, background=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        win.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.images = []  # 화면에서 사라지지 않게 잡아 둔다
        cache = os.path.join(folder, ".미리보기")
        cols = 5
        for i, video in enumerate(videos):
            card = ttk.Frame(body, style="Card.TFrame", padding=8)
            card.grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky="n")
            img = self._thumb(video, cache)
            if img is not None:
                btn = tk.Label(card, image=img, background=CARD, cursor="hand2")
                btn.pack()
                btn.bind("<Button-1>", lambda e, v=video: _open_folder(v))
            name = os.path.splitext(os.path.basename(video))[0]
            ttk.Label(card, text=name, style="Card.TLabel", wraplength=190).pack(pady=(6, 2))
            sub = os.path.basename(os.path.dirname(video))
            if os.path.abspath(os.path.dirname(video)) != os.path.abspath(folder):
                ttk.Label(card, text=sub, style="Sub.Card.TLabel").pack()
            ttk.Button(card, text="▶ 재생", style="Soft.TButton",
                       command=lambda v=video: _open_folder(v)).pack(fill="x", pady=(4, 0))

    def _thumb(self, video: str, cache: str):
        """썸네일 그림: 함께 만든 썸네일이 있으면 그것, 없으면 영상 1초 장면."""
        base = os.path.splitext(video)[0]
        src = next((p for p in (base + "_썸네일.png", base + ".jpg") if os.path.exists(p)), None)
        os.makedirs(cache, exist_ok=True)
        small = os.path.join(cache, hashlib_name(video) + ".png")
        try:
            if not os.path.exists(small):  # FFmpeg로 작게 줄인 그림을 만든다
                seek = [] if src else ["-ss", "1"]
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *seek, "-i", src or video,
                                "-frames:v", "1", "-vf",
                                "scale='min(190,iw)':'min(300,ih)':force_original_aspect_ratio=decrease",
                                small], creationflags=NO_WINDOW, check=True)
            return self._keep(tk.PhotoImage(file=small))
        except Exception:
            return None

    def _keep(self, img):
        self.images.append(img)
        return img


def hashlib_name(path: str) -> str:
    import hashlib
    return hashlib.md5(f"{path}|{os.path.getmtime(path)}".encode()).hexdigest()[:12]


class AutoStart:
    """고르기 창에서 정해진 시간 동안 아무것도 안 누르면 그대로 진행한다 (밤새 돌려도 안 멈추게).

    창 안에서 마우스나 키보드를 쓰면 기다리기를 멈추고 사람이 직접 누를 때까지 둔다.
    """

    def __init__(self, win: tk.Toplevel, parent: ttk.Frame, done, what: str):
        self.win, self.done, self.what = win, done, what
        self.left = int(review.wait_minutes() * 60)
        self.job = None
        self.label = ttk.Label(parent, foreground=ACCENT)
        self.label.pack(side="right", padx=12)
        if not self.left:
            return
        win.bind("<ButtonPress>", self.stop, add="+")
        win.bind("<KeyPress>", self.stop, add="+")
        self.tick()

    def tick(self) -> None:
        try:
            if self.left <= 0:
                self.done()
                return
            m, s = divmod(self.left, 60)
            self.label.configure(text=f"{m}:{s:02} 뒤 자동으로 {self.what}  (아무거나 누르면 멈춰요)")
            self.left -= 1
            self.job = self.win.after(1000, self.tick)
        except tk.TclError:
            pass  # 창이 이미 닫혔다

    def stop(self, _event=None) -> None:
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
                self.label.configure(text="직접 고르는 중 (다 고르면 오른쪽 버튼을 눌러 주세요)")
            except tk.TclError:
                pass
            self.job = None


class ReviewDialog:
    """하이라이트 목록에서 만들 숏폼을 고르고 제목·문구·구간을 고치는 창."""

    def __init__(self, parent: tk.Tk, path: str):
        self.path = path
        with open(os.path.join(os.path.dirname(path), "highlights.json"), encoding="utf-8") as f:
            self.highlights = [Highlight(**h) for h in json.load(f)["highlights"]]

        self.win = win = tk.Toplevel(parent, background=BG)
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
        canvas = tk.Canvas(outer, highlightthickness=0, background=BG)
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
            ttk.Label(body, text=h.reason, wraplength=200, foreground=SUB).grid(
                row=i, column=8, padx=4, sticky="w")
            self.rows.append((on, rng, title, bottom, subt))

        bf = ttk.Frame(win, padding=10)
        bf.pack(fill="x")
        ttk.Button(bf, text="모두 선택", command=lambda: self._all(True)).pack(side="left")
        ttk.Button(bf, text="모두 해제", command=lambda: self._all(False)).pack(side="left", padx=6)
        ttk.Button(bf, text="선택한 숏폼 만들기", style="Big.TButton",
                   command=self._done).pack(side="right")
        self.auto = AutoStart(win, bf, self._done, "선택한 숏폼을 만들어요")

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
        self.win = win = tk.Toplevel(parent, background=BG)
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
        self.tree.tag_configure("off", foreground="#6a6a74")
        self.tree.bind("<<TreeviewSelect>>", self._load_row)
        self.tree.bind("<Double-1>", lambda e: self._toggle())

        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=(8, 0))
        for text, cmd in [("위로", lambda: self._move(-1)), ("아래로", lambda: self._move(1)),
                          ("넣기 / 빼기", self._toggle), ("촬영본 열어 보기", self._open_clip)]:
            ttk.Button(side, text=text, command=cmd, width=20).pack(fill="x", pady=2)

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
            box = tk.Text(df, height=4, wrap="word")
            style_field(box)
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
        self.auto = AutoStart(win, bf, self._done, "이 순서대로 만들어요")

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
