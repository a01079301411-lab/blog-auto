"""run.bat이 부르는 실행기: 자동 업데이트 → 숏폼 만들기.

run.bat은 바뀔 일이 없도록 이 파일만 부르고, 나머지는 여기서 처리한다.
업데이트로 바뀐 코드가 바로 쓰이도록 실제 작업은 새 파이썬 프로세스로 실행한다.
"""
from __future__ import annotations

import subprocess
import sys

from . import update


def main() -> int:
    update.main()
    print()
    if len(sys.argv) < 2:
        print("영상 파일을 run.bat 위로 끌어다 놓으세요.")
        print("설정은 settings.ini를 메모장으로 열어서 바꿀 수 있어요.")
        return 0

    code = 0
    for video in sys.argv[1:]:  # 여러 개를 한꺼번에 끌어다 놓아도 차례로 처리
        code = subprocess.run([sys.executable, "-m", "shortform", "auto", video],
                              cwd=update.ROOT).returncode or code
    if code:
        print("\n[실패] 위 오류 메시지를 캡처해서 보내 주세요.")
    return code


if __name__ == "__main__":
    sys.exit(main())
