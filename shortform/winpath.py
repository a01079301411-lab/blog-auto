"""윈도우에서 한글이 들어간 경로를 FFmpeg에 넘길 때의 안전장치.

어떤 컴퓨터의 FFmpeg는 사용자 이름(C:\\Users\\이원주pc)이나 폴더 이름(바탕 화면, 영상편집기)에
한글이 있으면 파일을 열지 못하고 'Illegal byte sequence'로 멈춘다. 그래서 FFmpeg·FFprobe를
부를 때만 경로를 한글 없는 경로로 바꿔 준다.

- 읽는 파일(-i 뒤): 윈도우 짧은 이름(8.3, 예: C:\\Users\\C8E9~1\\...)으로. 짧은 이름이 없으면
  한글 없는 작업 폴더(C:\\ProgramData\\shortform_cache)에 하드링크(안 되면 복사)를 만들어 그걸 넘긴다.
- 쓰는 파일(명령의 마지막 인자): 폴더에 짧은 이름이 있고 파일 이름에 한글이 없으면 짧은 경로로,
  아니면 작업 폴더에 먼저 쓰고 끝난 뒤 원래 자리로 옮긴다.

subprocess.Popen을 감싸서 숏폼·롱폼의 모든 FFmpeg 호출에 한 번에 적용된다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time

_installed = False


def _ascii(s: str) -> bool:
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _cache_dir() -> str:
    for base in (os.environ.get("ProgramData", ""), "C:\\"):
        if base and _ascii(base):
            d = os.path.join(base, "shortform_cache")
            try:
                os.makedirs(d, exist_ok=True)
                return d
            except OSError:
                continue
    return ""


def _short(path: str) -> str:
    """윈도우 짧은 경로 (없으면 원래 경로)."""
    try:
        import ctypes
        from ctypes import wintypes

        f = ctypes.windll.kernel32.GetShortPathNameW
        f.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        n = f(path, None, 0)
        if n:
            buf = ctypes.create_unicode_buffer(n)
            if f(path, buf, n):
                return buf.value
    except Exception:
        pass
    return path


def _key(path: str) -> str:
    st = os.stat(path)
    return hashlib.md5(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]


# 원드라이브 '온라인 전용' 파일 (아직 컴퓨터에 안 내려받은 파일) 표시
_CLOUD = 0x400000 | 0x40000 | 0x1000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def _in_cloud(path: str) -> bool:
    try:
        return bool(getattr(os.stat(path), "st_file_attributes", 0) & _CLOUD)
    except OSError:
        return False


def input_path(path: str) -> str:
    if not os.path.isfile(path):
        return path
    cloud = _in_cloud(path)
    if _ascii(path) and not cloud:
        return path
    if not cloud:
        s = _short(os.path.abspath(path))
        if _ascii(s):
            return s
    cache = _cache_dir()
    if not cache:
        return path
    dst = os.path.join(cache, _key(path) + os.path.splitext(path)[1].encode("ascii", "ignore").decode())
    if not os.path.exists(dst):
        try:
            if cloud:  # 원드라이브에서 내려받으며 복사 (FFmpeg가 직접 열면 실패하는 경우가 있다)
                raise OSError
            os.link(path, dst)  # 같은 드라이브면 복사 없이 바로
        except OSError:
            shutil.copyfile(path, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
    return dst


def output_path(path: str) -> tuple[str, str | None]:
    """(FFmpeg에 줄 경로, 끝나고 옮길 원래 경로 또는 None)."""
    if _ascii(path):
        return path, None
    folder, name = os.path.split(os.path.abspath(path))
    if os.path.isdir(folder) and _ascii(name):
        s = _short(folder)
        if _ascii(s):
            return os.path.join(s, name), None
    cache = _cache_dir()
    if not cache:
        return path, None
    ext = os.path.splitext(name)[1].encode("ascii", "ignore").decode()
    tmp = os.path.join(cache, f"out_{os.getpid()}_{time.time_ns()}{ext}")
    return tmp, path


def _is_path(a: str) -> bool:
    return len(a) > 2 and (a[1:3] == ":\\" or a[1:3] == ":/" or a.startswith("\\\\"))


def fix(cmd: list) -> tuple[list, list[tuple[str, str]]]:
    """FFmpeg·FFprobe 명령의 한글 경로를 바꾼다. (새 명령, [(임시 출력, 원래 출력)])"""
    out = list(cmd)
    moves = []
    prog = os.path.basename(str(out[0])).lower()
    for i, a in enumerate(out):
        if i == 0 or not isinstance(a, str) or not _is_path(a):
            continue
        if _ascii(a) and not (str(out[i - 1]) == "-i" or prog.startswith("ffprobe")):
            continue
        last = i == len(out) - 1 and prog.startswith("ffmpeg")
        if last and str(out[i - 1]) != "-i":
            tmp, final = output_path(a)
            out[i] = tmp
            if final:
                moves.append((tmp, final))
        else:
            out[i] = input_path(a)
    return out, moves


def _finish(moves: list[tuple[str, str]], ok: bool) -> None:
    for tmp, final in moves:
        if os.path.exists(tmp):
            if ok:
                shutil.move(tmp, final)
            else:
                os.remove(tmp)


class _Popen(subprocess.Popen):
    def __init__(self, args, *a, **k):
        self._sf_moves = []
        if isinstance(args, (list, tuple)) and args:
            prog = os.path.basename(str(args[0])).lower()
            if prog.startswith(("ffmpeg", "ffprobe")):
                args, self._sf_moves = fix(list(args))
        super().__init__(args, *a, **k)

    def wait(self, *a, **k):
        code = super().wait(*a, **k)
        if self._sf_moves:
            moves, self._sf_moves = self._sf_moves, []
            _finish(moves, code == 0)
        return code


def _cleanup() -> None:
    """작업 폴더에서 사흘 넘은 파일을 지운다."""
    cache = _cache_dir()
    if not cache:
        return
    now = time.time()
    for n in os.listdir(cache):
        p = os.path.join(cache, n)
        try:
            if now - os.path.getmtime(p) > 3 * 86400:
                os.remove(p)
        except OSError:
            pass


def install() -> None:
    """윈도우에서만: subprocess가 FFmpeg를 부를 때 한글 경로를 바꾸게 한다."""
    global _installed
    if _installed or sys.platform != "win32":
        return
    _installed = True
    subprocess.Popen = _Popen
    try:
        _cleanup()
    except Exception:
        pass
