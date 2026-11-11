"""휴대폰 → 드라이브 폴더 → 자동 편집.

휴대폰에서 영상을 드라이브(구글 드라이브·원드라이브)의 '숏폼_편집할영상' 폴더에 공유해 넣으면,
PC가 그 폴더를 지켜보다가 숏폼을 만들어 '숏폼_완성' 폴더에 넣는다. 휴대폰 드라이브 앱에서
완성본을 갤러리에 저장해 바로 올리면 된다.

- 하위 폴더 이름 = 템플릿 이름: '숏폼_편집할영상/크로스핏'에 넣으면 '크로스핏' 템플릿 설정으로
  (템플릿은 프로그램 창의 [템플릿 저장]으로 만든다). 폴더 바로 아래에 넣으면 지금 설정 그대로.
- 몇 분 안에 같은 폴더에 함께 들어온 영상들은 하나로 이어서 한 번에 만든다.
- 같은 폴더에 '지시.txt'(아무 이름의 .txt)를 함께 넣으면 그 내용을 편집 지시로 먼저 따른다.
- 다 올라가기 전에 시작하지 않도록, 파일 크기가 멈추고 마지막 영상이 들어온 지 2분이 지나면 시작한다.
- 처리한 원본은 '_완료', 실패하면 '_실패' 폴더로 옮겨서 다시 처리하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from . import settings

ROOT = settings.ROOT
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
INBOX_NAME, OUTBOX_NAME = "숏폼_편집할영상", "숏폼_완성"
SKIP = ("_처리중", "_완료", "_실패")
SETTLE = 120      # 마지막 영상이 들어오고 이만큼(초) 지나야 시작 (여러 개를 올리는 중일 수 있어서)
SCAN = 15         # 폴더를 살펴보는 간격(초)


def default_base() -> str:
    """드라이브 폴더: 구글 드라이브(G:\\내 드라이브 등) → 원드라이브 → 사용자 폴더."""
    cands = []
    for letter in "GHIJKLMNOPQRSTUVWXYZ":
        cands += [f"{letter}:\\내 드라이브", f"{letter}:\\My Drive"]
    home = os.path.expanduser("~")
    cands += [os.path.join(home, "Google Drive"), os.path.join(home, "내 드라이브"),
              os.environ.get("OneDrive", ""), os.path.join(home, "OneDrive")]
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return home


def folders(base: str | None = None) -> tuple[str, str]:
    base = base or settings.load().get("watch_base", "") or default_base()
    inbox, outbox = os.path.join(base, INBOX_NAME), os.path.join(base, OUTBOX_NAME)
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(outbox, exist_ok=True)
    guide = os.path.join(inbox, "읽어주세요.txt")
    if not os.path.exists(guide):
        with open(guide, "w", encoding="utf-8-sig") as f:
            f.write("휴대폰에서 영상을 이 폴더에 공유해 넣으면 PC가 숏폼을 만들어 '숏폼_완성' 폴더에 넣어요.\n\n"
                    "- 하위 폴더 이름이 템플릿 이름이면 그 템플릿 설정으로 만들어요 (예: 크로스핏, 브이로그).\n"
                    "- 몇 분 안에 함께 넣은 영상들은 하나로 이어서 만들어요.\n"
                    "- '지시.txt'를 같이 넣으면 그 내용을 편집 지시로 먼저 따라요 (예: 20초, 웃는 장면에서 끝).\n"
                    "- PC에서 프로그램이 켜져 있고 '폴더 지켜보기'가 켜져 있어야 해요.\n")
    for name in _templates():  # 템플릿마다 하위 폴더를 만들어 둔다 (휴대폰에서 고르기 쉽게)
        safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip()
        if safe:
            os.makedirs(os.path.join(inbox, safe), exist_ok=True)
    return inbox, outbox


def _templates() -> dict:
    path = os.path.join(ROOT, "템플릿.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class Watcher:
    def __init__(self, inbox: str, outbox: str):
        self.inbox, self.outbox = inbox, outbox
        self.sizes: dict[str, tuple[int, float]] = {}
        self.seen: dict[str, float] = {}   # 폴더에서 처음 본 시각

    def _stable(self, path: str, now: float) -> bool:
        """다 올라온 파일인지: 크기가 바뀌지 않은 채 한 번 더 확인됐는지."""
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        self.seen.setdefault(path, now)
        prev = self.sizes.get(path)
        self.sizes[path] = (size, prev[1] if prev and prev[0] == size else now)
        return size > 0 and prev is not None and prev[0] == size and now - self.sizes[path][1] >= SCAN

    def ready_groups(self) -> list[tuple[str, list[str], list[str]]]:
        """(폴더, 영상들, 지시 파일들) 중 시작해도 되는 묶음."""
        now = time.time()
        out = []
        for dirpath, dirs, files in os.walk(self.inbox):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            vids = [os.path.join(dirpath, f) for f in sorted(files)
                    if f.lower().endswith(VIDEO_EXT) and not f.startswith((".", "~"))]
            if not vids:
                continue
            if not all(self._stable(v, now) for v in vids):
                continue
            # 마지막 영상이 들어온 지 SETTLE초가 지나면, 그 폴더에 함께 있는 영상을 한 묶음으로
            # (휴대폰에서 여러 개를 고르면 몇 초~몇 분에 걸쳐 차례로 올라온다)
            if now - max(self.seen[v] for v in vids) < SETTLE:
                continue
            group = vids
            notes = [os.path.join(dirpath, f) for f in files if f.lower().endswith(".txt")
                     and f != "읽어주세요.txt"]
            out.append((dirpath, group, notes))
        return out

    def run_group(self, folder: str, vids: list[str], notes: list[str]) -> bool:
        stamp = datetime.now().strftime("%m%d_%H%M%S")
        work = os.path.join(self.inbox, "_처리중", stamp)
        os.makedirs(work, exist_ok=True)
        moved = []
        for v in vids:
            dst = os.path.join(work, os.path.basename(v))
            shutil.move(v, dst)
            moved.append(dst)
            self.sizes.pop(v, None)
            self.seen.pop(v, None)
        direction = ""
        for n in notes:
            try:
                with open(n, encoding="utf-8-sig", errors="replace") as f:
                    direction += " ".join(f.read().split()) + " "
                shutil.move(n, os.path.join(work, os.path.basename(n)))
            except OSError:
                pass
        # 설정: 지금 설정 + 폴더 이름의 템플릿 + 지시 (확인 창 없이 끝까지)
        rel = os.path.relpath(folder, self.inbox)
        template = "" if rel == "." else rel.split(os.sep)[0]
        values = {}
        if template:
            values.update(_templates().get(template, {}))
        values.update({"review": "no", "upload": "no",
                       "merge": "yes" if len(moved) > 1 else values.get("merge", "no")})
        if direction.strip():
            values["direction"] = direction.strip()
        ini = os.path.join(work, "settings.ini")
        shutil.copyfile(settings.PATH, ini)
        settings.save(values, path=ini)
        print(f"\n[폰 영상] {len(moved)}개 편집 시작"
              + (f" (템플릿: {template})" if template else "")
              + (f" / 지시: {direction.strip()}" if direction.strip() else ""), flush=True)
        for m in moved:
            print(f"  - {os.path.basename(m)}", flush=True)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        env.pop("SHORTFORM_GUI", None)
        code = subprocess.run([sys.executable, "-m", "shortform", "auto", *moved, "--settings", ini],
                              cwd=ROOT, env=env).returncode
        made = self._collect(work, stamp) if code == 0 else []
        dest = "_완료" if made else "_실패"
        final = os.path.join(self.inbox, dest, stamp)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        shutil.move(work, final)
        if made:
            print(f"[폰 영상] 완성 {len(made)}개 → {os.path.join(self.outbox, made[0])}", flush=True)
        else:
            print(f"[폰 영상] 실패했어요. 원본은 '{INBOX_NAME}\\_실패\\{stamp}'에 있어요.", flush=True)
        return bool(made)

    def _collect(self, work: str, stamp: str) -> list[str]:
        """완성본(영상·썸네일·설명글)을 '숏폼_완성/날짜_제목' 폴더로 옮긴다."""
        made = []
        for dirpath, dirs, files in os.walk(work):
            dirs[:] = [d for d in dirs if d != "캡컷_소스"]
            picks = os.path.join(dirpath, "highlights.json")
            if not os.path.exists(picks):
                continue
            try:
                with open(picks, encoding="utf-8") as f:
                    hs = json.load(f).get("highlights", [])
            except (OSError, ValueError):
                hs = []
            for k, h in enumerate(hs, 1):
                title = " ".join((h.get("title") or f"숏폼{k}").replace("{", "").replace("}", "").split())
                prefix = f"{k:02d}_"
                mp4 = next((f for f in files if f.startswith(prefix) and f.endswith(".mp4")), None)
                if not mp4:
                    continue
                safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|')[:40]
                out = os.path.join(self.outbox, f"{stamp}_{k:02d}_{safe}")
                os.makedirs(out, exist_ok=True)
                for f in files:
                    if f.startswith(prefix) and (f.endswith(".mp4") or "_썸네일" in f):
                        shutil.copyfile(os.path.join(dirpath, f), os.path.join(out, f))
                with open(os.path.join(out, "설명글.txt"), "w", encoding="utf-8-sig") as fh:
                    fh.write(f"{title}\n\n{h.get('caption', '')}\n")
                made.append(os.path.basename(out))
        return made

    def loop(self) -> None:
        print(f"[폴더 지켜보기] '{self.inbox}'에 영상이 들어오면 숏폼을 만들어 "
              f"'{self.outbox}'에 넣어요.", flush=True)
        while True:
            try:
                for folder, vids, notes in self.ready_groups():
                    self.run_group(folder, vids, notes)
            except Exception as e:  # 한 번 실패해도 계속 지켜본다
                print(f"[폴더 지켜보기] 문제가 생겼지만 계속 지켜봐요: {type(e).__name__}: {e}", flush=True)
            time.sleep(SCAN)


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="python -m shortform.watch")
    p.add_argument("--base", help="드라이브 폴더 (기본: 구글 드라이브 → 원드라이브)")
    a = p.parse_args(argv)
    inbox, outbox = folders(a.base)
    Watcher(inbox, outbox).loop()


if __name__ == "__main__":
    main()
