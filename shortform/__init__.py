"""롱폼 영상 → 숏폼 하이라이트 자동 생성 도구."""

# 업데이트할 때마다 올린다. 프로그램 창 제목과 실행 기록에 보여서 새 버전인지 확인할 수 있다
__version__ = "10.28-4"

# 윈도우에서 한글 경로(사용자 이름, 바탕 화면 등)를 FFmpeg가 못 여는 컴퓨터가 있어서 미리 바꿔 준다
from . import winpath as _winpath  # noqa: E402

_winpath.install()

