"""바탕화면 아이콘이 여는 입구. 프로그램 창을 열다가 무엇이든 실패하면(설치가 덜 됐거나 부품이
없을 때) 조용히 꺼지지 않고 이유를 알림 창과 logs/시작_오류.txt로 알려 준다."""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tell(text: str) -> None:
    try:
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        with open(os.path.join(ROOT, "logs", "시작_오류.txt"), "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    hint = "프로그램 폴더의 install.bat을 한 번 실행한 뒤 다시 열어 보세요."
    if "No module named" in text:
        hint = ("필요한 부품이 이 컴퓨터에 설치되지 않았어요. " + hint)
    msg = f"프로그램을 여는 중에 문제가 생겼어요.\n\n{text[-900:]}\n\n{hint}\n그래도 안 되면 이 창을 캡처해서 보내 주세요."
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "숏폼·롱폼 자동 편집기", 0x10)
    except Exception:
        print(msg)


def main() -> None:
    os.chdir(ROOT)
    try:
        from . import gui
    except Exception:
        _tell(traceback.format_exc())
        sys.exit(1)
    gui.main()


if __name__ == "__main__":
    main()
