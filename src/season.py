"""계절에 맞는 말인지 확인한다.

10월에 '장마철이라…'처럼 지금 계절과 안 맞는 말이 들어가면 글이 오래된 글처럼 보인다.
아래 표의 말은 적힌 달에만 쓴다. (한 달 전부터 준비 글은 쓸 수 있게 앞 달을 넣어 두었다)
"""
import re
from datetime import date

# 말: 써도 되는 달
SEASON_WORDS = {
    "장마": (5, 6, 7, 8),
    "폭염": (6, 7, 8, 9),
    "무더위": (6, 7, 8, 9),
    "열대야": (6, 7, 8, 9),
    "한여름": (6, 7, 8),
    "한파": (11, 12, 1, 2),
    "한겨울": (12, 1, 2),
    "폭설": (12, 1, 2),
    "혹한": (12, 1, 2),
    "동파": (11, 12, 1, 2),
    "벚꽃": (3, 4),
    "황사": (3, 4, 5),
}

SEASONS = {
    "봄": ((3, 4, 5), "봄 이사철, 일교차, 황사"),
    "여름": ((6, 7, 8), "장마, 폭염, 높은 습도"),
    "가을": ((9, 10, 11), "가을 이사철, 환절기 일교차, 곧 다가올 겨울 결로"),
    "겨울": ((12, 1, 2), "겨울 결로, 한파, 동파, 짧은 해"),
}


def season_of(month):
    return next(name for name, (months, _) in SEASONS.items() if month in months)


def out_of_season(text, today=None):
    """지금 달에 맞지 않는 계절 말 목록."""
    month = (today or date.today()).month
    return [w for w, months in SEASON_WORDS.items() if month not in months and re.search(w, text)]


def topic_in_season(topic, today=None):
    """주제 이름·키워드에 지금 계절과 안 맞는 말이 있으면 False (예: 10월의 '장마철 보관이사')."""
    return not out_of_season(topic["topic"] + " " + topic["keyword"], today)


def describe(today=None):
    """AI에게 알려 줄 오늘 날짜와 계절."""
    today = today or date.today()
    name = season_of(today.month)
    hint = SEASONS[name][1]
    avoid = ", ".join(w for w, months in SEASON_WORDS.items() if today.month not in months)
    return (f"{today.year}년 {today.month}월 {today.day}일, {name}. 지금 계절에 맞는 말({hint})만 쓴다. "
            f"다른 계절 이야기({avoid})는 제목, 본문, 태그, 댓글 보기 어디에도 쓰지 않는다.")
