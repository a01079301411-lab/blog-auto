"""코시(육성프로그램) 인스타 10개 계정별 제작 가이드.

'계정별 썸네일 영상 제작 가이드'의 예시 이미지를 1080x1920 기준으로 재서 옮긴 값과,
'인스타 계정 운영 가이드'의 계정 컨셉을 담는다.

- N-1 썸네일: 계정 피드 대표 이미지 (PNG 1080x1920)
- N-3 세로 촬영본: 세로 원본을 화면 전체에 꽉 채우고 글자를 위에 올림
- N-4 롱폼 잘라 쓴 숏폼: 가로 영상을 가운데 네모(y 432~1533)에만 넣고 위에 제목, 아래 하단자막

글자 크기는 글꼴 크기(px). 위치 y는 1080x1920 화면 기준.
"""
from __future__ import annotations

from dataclasses import dataclass

# 영상 상자 (N-4): 가이드의 회색 네모
BOX_TOP, BOX_BOTTOM = 432, 1534
# 설명자막(노란 [ ])과 말자막(하얀) 가운데 y, 하단자막(< >) 가운데 y
SPEAKER_Y, SUB_Y, BOTTOM_Y = 1066, 1152, 1604

F_ROKA = ["ROKABold", "강한육군 Bold", "강한육군", "ROKA"]
F_DOVE = ["Dovemayo_gothic", "둘기마요_고딕", "둘기마요 고딕", "Dovemayo"]
F_PAPER7 = ["Paperlogy-7Bold", "Paperlogy 7 Bold", "페이퍼로지 7 Bold", "Paperlogy"]
F_PAPER6 = ["Paperlogy-6SemiBold", "Paperlogy 6 SemiBold", "페이퍼로지 6 SemiBold", "Paperlogy"]


@dataclass
class Txt:
    """글자 한 종류의 모양."""
    fonts: list[str]
    size: int
    color: str = "#FFFFFF"
    hl: str | None = None          # {강조} 단어 색
    hl_box: bool = False           # 강조를 색 글자 대신 색 상자 위 흰 글자로
    stroke: int = 0                # 테두리 두께
    stroke_color: str = "#000000"
    shadow: bool = False           # 그림자
    italic: bool = False           # 기울이기
    box: str | None = None         # 줄 뒤 상자 색 (4번 주제목의 검은 상자)
    paper: bool = False            # 모눈종이 상자 (5번 제목)
    pill: str | None = None        # 알약 모양 배경색 (2·8번 썸네일 부제목)
    gap: int = 14                  # 줄 간격


@dataclass
class Layout:
    """화면 한 장(썸네일 또는 영상)의 글자 배치."""
    title: Txt
    title_y: int                   # 제목 묶음 기준 y
    anchor: str = "bottom"         # 기준 y가 묶음의 bottom / center
    align: str = "center"          # center / left
    x: int = 540                   # center면 가운데 x, left면 왼쪽 여백
    sub_title: Txt | None = None   # 제목 위 작은 부제목 줄
    pill: Txt | None = None        # 제목 위 알약 (부제목을 알약으로)
    layout: str = "full"           # 썸네일 바탕: full(화면 가득) / box(N-4처럼 가운데 상자)
    shade: str = "none"            # 썸네일 바탕 처리: none / bottom(아래 어둡게) / dim(전체 어둡게)


@dataclass
class Account:
    no: int
    handle: str
    name: str
    kind: str                      # B2B / B2C
    concept: str                   # 이런 걸 올려요
    audience: str
    title_hint: str                # Claude에게 줄 제목 작성 요령
    video: Layout                  # N-3 / N-4 공통 제목 배치
    thumb: Layout                  # N-1
    speaker: Txt                   # 설명자막 [ ]
    sub: Txt                       # 말자막
    sub_box: str | None = None     # 말자막 뒤 상자 색 (3번)
    bottom: Txt | None = None      # 하단자막 < > (1·5번)
    bio: str = ""
    caution: str = ""

    @property
    def folder(self) -> str:
        return f"{self.no:02}_{self.name}"


def _subs(fonts, speaker_color, speaker_size=64, sub_size=78, stroke=5):
    return (Txt(fonts, speaker_size, speaker_color, stroke=stroke - 1),
            Txt(fonts, sub_size, "#FFFFFF", stroke=stroke))


ACCOUNTS: dict[int, Account] = {}


def _add(a: Account) -> None:
    ACCOUNTS[a.no] = a


# ───────────── B2B (사장님 대상) ─────────────
_sp, _sb = _subs(F_DOVE, "#FFFD20", 64, 78)
_add(Account(
    1, "@heads_secret", "대표들의 말 못할 비밀", "B2B",
    "회사를 운영하며 직원들과, 또는 회사 일상 속에서 벌어지는 꼴통사장의 사이다 같은 일상",
    "30~40대 사장님. 예능 / 사업 인사이트",
    "부제목은 상황 설명(예: '사장님 속터지는'), 주제목은 펀치라인(예: '{진상 직원}의 한마디'). "
    "사이다·예능 톤, 사장님이 공감하는 상황.",
    video=Layout(Txt(F_ROKA, 113, hl="#00FF1E", stroke=4), title_y=408,
                 sub_title=Txt(["GangwonEduSaeeumMedium", "강원교육새음", "GangwonEduSaeeum"], 82,
                               stroke=4)),
    thumb=Layout(Txt(F_ROKA, 133, hl="#00FF1E", shadow=True), title_y=1314, anchor="center",
                 sub_title=Txt(["GangwonEduSaeeumMedium", "강원교육새음", "GangwonEduSaeeum"], 100,
                               shadow=True), shade="bottom"),
    speaker=_sp, sub=_sb,
    bottom=Txt(F_DOVE, 66, "#00FF1E", stroke=4),
    bio="직원 눈치 보느라 차마 못 하는 말, 아무한테도 말 못 하던 사장들의 속마음을 대신 시원하게"))

_sp, _sb = _subs(["GimpoBatang", "김포평화바탕", "Gimpo"], "#FFFD20", 61, 75)
_add(Account(
    2, "@business_.recipe", "사업 레시피", "B2B",
    "사업하는 사장님(초보~중급)이 알면 좋은 사업 정보",
    "30~50대 사장님. 브랜딩 / 사업 인사이트",
    "정보형 2줄 제목, 핵심 단어 1개를 강조(예: '매출 두 배 만든 / {가격 전략}'). "
    "부제목은 썸네일 위 알약에 들어갈 짧은 꼬리표(예: '사장님 필독').",
    video=Layout(Txt(["MuseumClassicBold", "박물관문화재단클래식", "MuseumClassic"], 114,
                     hl="#F332FF", stroke=5), title_y=388),
    thumb=Layout(Txt(["MuseumClassicBold", "박물관문화재단클래식", "MuseumClassic"], 136,
                     shadow=True), title_y=431, anchor="center",
                 pill=Txt(["MuseumClassicBold", "박물관문화재단클래식", "MuseumClassic"], 50,
                          pill="#99009F")),
    speaker=_sp, sub=_sb,
    bio="세상 모든 성공한 사업가들이 절대 말 안 해주는 진짜 꿀팁"))

_sp, _sb = _subs(["KOROADM", "KOROAD체", "KOROAD"], "#FFEB0C", 62, 62)
_add(Account(
    3, "@danaga_com", "사장은 처음이라", "B2B",
    "초보 사장이 알면 좋은 회사 성장 방법과 돈 버는 노하우",
    "30~40대 초보 사장님. 브랜딩 / 사업 인사이트",
    "최대 두 줄, 왼쪽 정렬로 들어가는 정보형 제목. 핵심 단어를 강조(예: '{직원 첫 채용} 전에 / 꼭 알아야 할 3가지').",
    video=Layout(Txt(F_PAPER7, 85, hl="#49FF09", italic=True, stroke=3), title_y=405,
                 align="left", x=60),
    thumb=Layout(Txt(F_PAPER7, 85, hl="#49FF09", italic=True, stroke=3), title_y=405,
                 align="left", x=60, layout="box"),
    speaker=_sp, sub=Txt(["KOROADM", "KOROAD체", "KOROAD"], 62, "#FFFFFF"), sub_box="#2B2B2B",
    bio="오늘도 혼자 버티는 초보 사장님들에게 회사 키우는 돈 냄새 나는 노하우"))

# ───────────── B2C (일반인 대상) ─────────────
_sp, _sb = _subs(F_DOVE, "#FFFD20", 63, 72)
_add(Account(
    4, "@goltong_tutor", "꼴통 강사 권기준", "B2C",
    "자물쇠 스터디·육성프로그램을 준비하면서 벌어지는 꼴통 강사의 일상. 강사와 제자들이 티격태격하며 같이 크는 이야기",
    "20~30대. 예능 / 육성프로그램 바이럴",
    "부제목은 짧은 주어(예: '꼴통 강사가'), 주제목은 궁금증을 부르는 펀치라인(예: '{물 빠따}를 든 이유'). "
    "웃기다가 가끔 찡한 예능 톤.",
    video=Layout(Txt(F_ROKA, 100, hl="#FFA800", box="#000000"), title_y=392,
                 sub_title=Txt(["GangwonEduHyeonokT_OTFMedium", "강원교육현옥샘", "GangwonEduHyeonok"],
                               80, stroke=3)),
    thumb=Layout(Txt(F_ROKA, 104, hl="#FFA800", box="#000000"), title_y=418, anchor="center",
                 sub_title=Txt(["GangwonEduHyeonokT_OTFMedium", "강원교육현옥샘", "GangwonEduHyeonok"],
                               90, shadow=True)),
    speaker=_sp, sub=_sb,
    bio="연매출 300억 회사 CEO이자 꼴통 강사. 저랑 제자들이 티격태격하면서 같이 크는 이야기"))

_KYOBO = ["KyoboHandwriting2019", "교보손글씨 2019", "교보 손글씨 2019", "Kyobo Handwriting 2019",
          "KyoboHandwriting"]
_NSN = ["NanumSquareNeoTTF-bRg", "NanumSquareNeo-bRg", "나눔스퀘어 네오", "NanumSquareNeo"]
_sp, _sb = _subs(_NSN, "#FFFD20", 64, 69)
_add(Account(
    5, "@creator_recipe", "크리에이터 비밀노트", "B2C",
    "10만~100만 크리에이터들의 수익화, 조회수 높이는 비법 등 SNS 관련 모든 정보",
    "20~30대 크리에이터 지망생. 인사이트 / 강의",
    "노트에 손글씨로 적은 듯한 2줄 정보형 제목, 강조 표시 없이(예: '조회수 0에서 / 10만 가는 법'). "
    "저장하고 싶어지는 꿀팁 톤.",
    video=Layout(Txt(_KYOBO, 82, "#000000", paper=True), title_y=423),
    thumb=Layout(Txt(_KYOBO, 92, "#000000", paper=True), title_y=416, anchor="center"),
    speaker=_sp, sub=_sb,
    bottom=Txt(_NSN, 56, "#FFFFFF", stroke=4),
    bio="남들 다 아는 뻔한 SNS 팁 말고, 10만부터 100만까지 크리에이터들의 정답 노트"))

_sp, _sb = _subs(F_DOVE, "#FFFD20", 62, 79)
_add(Account(
    6, "@youngkk_day", "1% 라이프", "B2C",
    "10만~100만, 억대를 버는 크리에이터들의 평범한 듯 결코 평범하지 않은 일상",
    "20~30대. 예능 / 거리 좁히기",
    "한 줄 또는 두 줄의 짧고 친근한 예능 제목, 강조 표시 없이(예: '맨날 삥 뜯는 / 슈퍼스타 형').",
    video=Layout(Txt(["EF_jejudoldam", "제주돌담", "EF_제주돌담", "jejudoldam"], 102, stroke=7),
                 title_y=410),
    thumb=Layout(Txt(["EF_jejudoldam", "제주돌담", "EF_제주돌담", "jejudoldam"], 150, stroke=8),
                 title_y=1231, anchor="center"),
    speaker=_sp, sub=_sb,
    bio="월 수억 버는 사람들은 대체 어떤 하루를 보낼까? 상위 1% 크리에이터들의 일상"))

_NBG = ["NanumBarunGothicBold", "나눔바른고딕 Bold", "NanumBarunGothic", "나눔바른고딕"]
_sp, _sb = _subs(F_PAPER6, "#FFEB0C", 53, 63)
_add(Account(
    7, "@grow_up_rizz", "성공 취조실", "B2C",
    "탑 크리에이터들의 밑바닥부터 성장해온 과정과 지금의 성공 사례, 그들의 민낯까지 파헤친다",
    "20~30대. 실제 수강생 성과·후기 공유",
    "출연자의 한마디를 큰따옴표로 인용한 제목, 최대 두 줄, 핵심 단어 강조"
    "(예: '“조회수 0에서 {월 천}까지 / 6개월 걸렸어요”').",
    video=Layout(Txt(_NBG, 92, hl="#FFFD20", stroke=3), title_y=385),
    thumb=Layout(Txt(_NBG, 130, hl="#FFFD20", shadow=True), title_y=1202, anchor="center",
                 align="left", x=96, shade="bottom"),
    speaker=_sp, sub=_sb,
    caution="수강생 개인 정보 주의: 얼굴, 이름, 채널명 등 모자이크 필수",
    bio="지금은 월 수억 버는 탑 크리에이터들도 조회수 0에서 시작했습니다"))

_sp, _sb = _subs(F_PAPER6, "#FFEB0C", 53, 63)
_add(Account(
    8, "@young_.n_rich", "수억 버는 쉬었음 청년", "B2C",
    "일하기는 싫고 쉽게 돈 버는 팁만 모았다. 2030 쉬었음 청년들을 위한 SNS 부업 정보",
    "20~30대 쉬었음 청년. SNS 부업 정보 / 수익화 강의 숏폼",
    "2줄 제목, 핵심 단어 강조(예: '침대에서 {월 300} / 버는 방법'). 부제목은 썸네일 위 알약에 들어갈 "
    "짧은 꼬리표(예: '퇴사 각').",
    video=Layout(Txt(["62570", "62570체"], 100, hl="#FF67F6", italic=True, stroke=5), title_y=406),
    thumb=Layout(Txt(["62570", "62570체"], 135, italic=True, shadow=True), title_y=1278,
                 anchor="center", pill=Txt(["62570", "62570체"], 46, pill="#FF67F6")),
    speaker=_sp, sub=_sb,
    bio="남들 출근할 때, 침대에서 돈 쓸어 담는 쉬었음 청년들의 SNS 부업 꿀팁"))

_sp, _sb = _subs(F_PAPER6, "#FFEB0C", 67, 81)
_add(Account(
    9, "@old_.but_rich", "퇴사한 김부장", "B2C",
    "SNS 모르는 엄마 아빠도 배울 수 있는 초보자 강의와 수익 노하우, 부업으로 돈 버는 모든 방법",
    "40~50대 SNS 왕초보. sns 부업 정보 초보자 버전",
    "4050이 바로 알아듣는 쉬운 말로 2줄, 핵심 단어 강조(예: '자식한테 손 안 벌리는 / {노후 부업}').",
    video=Layout(Txt(["RiaSans-Bold", "리아체", "RiaSans"], 105, hl="#FFD820", stroke=8),
                 title_y=424),
    thumb=Layout(Txt(["RiaSans-Bold", "리아체", "RiaSans"], 112, hl="#FFD820", stroke=8),
                 title_y=945, anchor="center"),
    speaker=_sp, sub=_sb,
    bio="요즘 4050이 은퇴 나이를 당긴 이유? SNS 왕초보도 차근차근 따라만 오세요"))

_sp, _sb = _subs(F_PAPER6, "#FFEB0C", 53, 63)
_add(Account(
    10, "@the._last_.chance", "인생 역전 story", "B2C",
    "수익화로 돈을 버는 수강생들의 성공사례로 동기부여, 그들을 여기까지 만든 각자의 팁 전수",
    "20~40대. 수익화(부업) 인사이트 / 강의 바이럴 / 성공 사례",
    "최대 두 줄, 핵심 단어 1~2개를 강조(색 상자로 표시됨)(예: '{월급 200}에서 / {월 2천} 된 비결').",
    video=Layout(Txt(F_PAPER6, 84, hl="#FF4A25", hl_box=True, stroke=3), title_y=392),
    thumb=Layout(Txt(F_PAPER6, 105, hl="#FF4A25", hl_box=True), title_y=955, anchor="center",
                 align="left", x=75, shade="dim"),
    speaker=_sp, sub=_sb,
    bio="SNS로 인생 역전한 사람들의 기록. 바닥에서 인생 뒤집은 사람들의 진짜 성공 이야기"))


def parse(text: str) -> list[int]:
    """'1,4, 7' → [1, 4, 7]. 잘못된 번호는 뺀다."""
    out = []
    for part in str(text).replace(" ", "").split(","):
        if part.isdigit() and int(part) in ACCOUNTS and int(part) not in out:
            out.append(int(part))
    return out


def all_fonts(acct: Account) -> dict[str, list[str]]:
    """이 계정에 필요한 글꼴 (역할 → 후보 이름)."""
    out = {"제목": acct.video.title.fonts, "말자막": acct.sub.fonts}
    if acct.video.sub_title:
        out["부제목"] = acct.video.sub_title.fonts
    return out
