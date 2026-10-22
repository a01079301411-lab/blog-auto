"""숏폼 '영상 종류' 가이드.

두 층으로 되어 있다.
1. 공통 이론(COMMON): 장르와 상관없이 잘되는 숏폼들이 공통으로 쓰는 원칙.
   훅 유형 11가지, 이야기 구조 5가지, 끝맺음 규칙. 모든 영상 종류에 들어간다.
2. 장르별 가이드(BUILTIN): 그 장르에서 특히 잘 먹히는 장면·훅·제목 예시와 피할 것.
   context/speaker는 이 프로그램을 쓰는 사람의 채널 기본값이라 [고급 설정]에서 바꿔도 된다.

guides.json 파일을 프로그램 폴더에 두면 같은 모양으로 가이드를 더 넣거나 고칠 수 있다.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_FILE = os.path.join(ROOT, "guides.json")
# 실제로 터진 숏폼 제목 (한 줄에 하나). 프로그램이 처음 켜질 때 만들고, 사용자가 계속 적어 넣는다.
HITS_FILE = os.path.join(ROOT, "잘된제목.txt")
HITS_SEED = ["연봉 1억 아내 남편 직업은?"]

# 제목 규칙: 조회수를 가르는 건 제목이라 장르와 상관없이 지킨다
TITLE_RULES = """\
Title rules (the title decides whether people stop scrolling):
- Short: at most 16 characters in total including spaces, 1-2 lines (split with \\n).
  If a shorter title works, use it.
- Plain words only: no "/", "|", "·", ":", brackets or other symbols ("?" at the end is
  fine). Never write "/" to separate lines.
- Build a curiosity gap the clip answers: a concrete, surprising fact (a number, money,
  a job, a relationship, a place) + an open question or unexpected outcome.
  e.g. "연봉 1억 아내\\n남편 직업은?" (number + people + question; the answer is in the clip).
- Concrete beats abstract. Avoid report words such as 해명, 정리, 이야기, 공개, 소개, 방법
  unless nothing else fits, and never stack two ideas in one title.
- Use the number viewers measure themselves against (연봉 1억, 월 300, 30평) even when the
  real figure is bigger: understating is fine (someone earning 월 1억 also earns 연봉 1억),
  overstating never. A reachable, familiar number feels real; a huge one feels fake.
- Never reveal the answer or punchline in the title.
- Write it the way the viewer would say it, not like a news headline."""

# 장르와 상관없이 조회수·시청 지속이 높은 숏폼에서 반복해서 보이는 패턴
COMMON = """\
Short-form principles seen across many successful Shorts/Reels/TikToks of every genre.
Use them for every clip; the genre notes below say which ones fit this video best.
Hook types for the first 1-2 seconds (pick the one the footage really supports):
1. Result first: show the end state or the punchline moment, then how it got there.
2. Question: a question the viewer silently asks themselves ("왜 다들 이걸 모를까?").
3. Turn teaser: promise a twist without revealing it ("근데 마지막에…").
4. Specific number: money, time, count, years ("10년 해보니", "3초 만에").
5. Relatable pain: "나만 그래?" moments everyone has lived.
6. Warning / don't: "이거 하지 마세요", a common mistake.
7. Before vs after: a visible contrast.
8. Conflict: two sides, an argument, a challenge, a bet.
9. Secret / insider: what only insiders know.
10. Reaction first: open on the strongest laugh, shock or tear, then show why.
11. Unfinished line: start mid-sentence on the most charged words (open loop).
Story shapes that hold attention: problem -> solution, expectation -> twist,
before -> after, situation -> conflict -> resolution, claim -> proof.
Q&A chain (works very well for interviews and talks): start at the question the title
asks, give the unexpected answer within 3 seconds, then a follow-up question and a bigger
punchline, and stop there. e.g. "남편 직업은?" -> "제 매니저예요, 제가 고용했어요" ->
"월급 얼마 받아?" -> "매번 달라요" -> the negotiation punchline (about 20 seconds in all).
Pacing: something new every 3-5 seconds (a new point, emotion, face or image).
One idea per short; drop side stories.
Ending: stop right after the payoff, no outro, so the loop restarts and viewers rewatch."""

BUILTIN: dict[str, dict] = {
    "lecture": {
        "length": "20-45",
        "name": "강의·인터뷰·팟캐스트",
        "context": "꼴통사장 권기준 대표의 사업 강의. 창업, 매출, 사장 마인드, 크리에이터로 돈 버는 법",
        "speaker": "권기준 / 꼴통사장 대표",
        "focus": (
            "A talk, lecture, interview or podcast. Pick moments with a provocative claim, a "
            "blunt opinion, a specific number, a common mistake, or a short story with a turn "
            "that ends in a clear lesson or punchline. Best hooks: 2, 4, 6, 9, 11."),
        "title": ("도발적인 주장·숫자·실수로 시작. 예: 사장님 속터지는\\n{진상 직원}의 한마디; "
                  "월매출 1억 찍고\\n{망한 이유}; 직원 뽑을 때\\n{이 질문} 하세요"),
        "avoid": "Long theory without an example; greetings; references to slides the viewer can't see.",
    },
    "vlog": {
        "length": "15-35",
        "name": "브이로그·가족 일상",
        "context": ("'여친 있는 유부남' 채널. 여친은 딸 셋, 본처는 아내. 5인 가족 아빠의 딸 데이트, "
                    "아내와 데이트, 크로스핏 등 취미, 이사업체 사장 일상 브이로그"),
        "speaker": "",
        "focus": (
            "A family or daily-life vlog, not a lecture: do NOT look for business lessons. Pick "
            "moments viewers would rewatch and share: a kid's unexpected line, a joke landing or "
            "failing, a hug or a sincere sentence, a relatable parenting or marriage moment, a "
            "small win in a hobby or at work. The first 2 seconds must already show the situation "
            "or the reaction. Best hooks: 1, 3, 5, 10. If the context describes a channel concept "
            "or nicknames (e.g. daughters called 'girlfriends'), keep it."),
        "title": ("위트 있는 반말 제목, 세계관 살리기. 예: 여친이 셋인 유부남의\\n{현실 데이트}; "
                  "첫째 여친의\\n{팩트 폭행}; 아빠가 {울컥}한\\n딸의 한마디"),
        "avoid": "Anything exposing a child's school, address or something embarrassing for the child.",
    },
    "moving": {
        "length": "15-40",
        "name": "현장·작업 과정 (이사·시공 등)",
        "context": "대구 이사업체 사장님의 현장 영상. 포장이사, 보관이사, 정리 과정과 현장 꿀팁",
        "speaker": "이사업체 사장님",
        "focus": (
            "Work footage (moving, construction, cleaning, repair...). Pick satisfying process "
            "moments (perfect packing, a tight staircase, a full truck), practical tips a "
            "customer can use, before/after contrasts, and lines only a professional would say. "
            "Best hooks: 1, 6, 7, 9."),
        "title": ("꿀팁·반전·전후. 예: 이사할 때 {이것} 모르면\\n돈 두 번 냅니다; "
                  "냉장고 옮기기 전\\n{꼭 할 일}; 3시간 걸린 짐이\\n{1톤 트럭} 하나에"),
        "avoid": "A customer's face, address or private belongings in detail.",
    },
    "commerce": {
        "length": "15-35",
        "name": "제품 소개·리뷰·광고",
        "context": "코시(COSY) 제품을 실제로 써 보는 영상. 유료광고 포함",
        "speaker": "",
        "focus": (
            "A product video (review or paid ad). Pick moments that follow problem -> using the "
            "product -> visible change, real usage, honest reactions and clear before/after. Do "
            "not exaggerate beyond what is shown. If it is a paid ad, the caption must start "
            "with '#광고'. Best hooks: 5, 7, 1."),
        "title": ("문제 → 해결이 보이게. 예: 매일 아프던 손목\\n{이걸로} 끝냈습니다; "
                  "써보고 놀란\\n{진짜 차이}"),
        "avoid": "Claims not shown in the footage (medical effects, 'best', 'No.1').",
    },
    "funny": {
        "length": "10-30",
        "name": "웃긴 장면·예능·리액션",
        "context": "",
        "speaker": "",
        "focus": (
            "Comedy, variety or reaction footage. Pick the setups that pay off with a laugh, "
            "awkward silences, unexpected answers, fails and strong reactions. Keep the setup "
            "short (under 5 s) and end right on the laugh. Best hooks: 10, 3, 8."),
        "title": ("상황을 짧게 비틀기. 예: 이걸 이렇게\\n{받아친다고?}; 아무도 예상 못한\\n{마지막 대답}"),
        "avoid": "Mocking someone who is not in on the joke.",
    },
    "story": {
        "length": "25-55",
        "name": "인생 이야기·감동",
        "context": "",
        "speaker": "",
        "focus": (
            "Personal stories, confessions, turning points and emotional moments. Pick a story "
            "with a clear before, a low point and a turn, told in one breath; or a single line "
            "that hits hard. Best hooks: 11, 4, 3."),
        "title": ("한 문장 고백형. 예: 빚 3억에서\\n{다시 시작한} 날; 그때 아버지가\\n{하신 말}"),
        "avoid": "Cutting before the turn of the story.",
    },
    "howto": {
        "length": "15-40",
        "name": "꿀팁·하우투·정보",
        "context": "",
        "speaker": "",
        "focus": (
            "Tips, how-tos and explainers. Pick one tip per short that is useful on its own and "
            "can be shown or said in under a minute, ideally with a visible result. Best hooks: "
            "6, 2, 1, 7."),
        "title": ("결과·실수 중심. 예: 이거 하나로\\n{30분} 아낍니다; 다들 {거꾸로}\\n하고 있어요"),
        "avoid": "Lists of many tips in one clip; vague tips without a concrete step.",
    },
    "custom": {
        "length": "",
        "name": "직접 입력 (영상 설명대로)",
        "context": "",
        "speaker": "",
        "focus": "",
        "title": "",
        "avoid": "",
    },
}


def load() -> dict[str, dict]:
    """기본 가이드 + guides.json에 사용자가 넣은 가이드."""
    guides = {k: dict(v) for k, v in BUILTIN.items()}
    try:
        with open(USER_FILE, encoding="utf-8-sig") as f:
            for key, g in json.load(f).items():
                guides[key] = {**guides.get(key, BUILTIN["custom"]), **g}
    except (OSError, ValueError):
        pass
    return guides


def get(key: str | None) -> dict:
    guides = load()
    return guides.get(key or "lecture", guides["lecture"])


def hit_titles() -> list[str]:
    """잘된제목.txt의 제목들. 파일이 없으면 기본 제목으로 만든다."""
    try:
        if not os.path.exists(HITS_FILE):
            with open(HITS_FILE, "w", encoding="utf-8-sig") as f:
                f.write("# 조회수가 잘 나온 숏폼 제목을 한 줄에 하나씩 적어 주세요. AI가 이 모양을 따라 해요.\n")
                f.write("\n".join(HITS_SEED) + "\n")
        with open(HITS_FILE, encoding="utf-8-sig") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        return list(HITS_SEED)


def brief(key: str | None) -> str:
    """Claude에게 줄 가이드 글 (하이라이트 고르기·검증·제목 쓰기에 쓴다)."""
    g = get(key)
    lines = [COMMON, "", TITLE_RULES]
    hits = hit_titles()[-15:]
    if hits:
        lines.append("Titles of this creator's shorts that went viral (copy their shape and length, "
                     "not their words):")
        lines += [f"- {t}" for t in hits]
    lines += ["", f"Video type: {g['name']}"]
    if g.get("focus"):
        lines.append(g["focus"])
    if g.get("title"):
        lines.append(f"Title style for this video type (Korean): {g['title']}")
    if g.get("avoid"):
        lines.append(f"Avoid: {g['avoid']}")
    if g.get("length"):
        lines.append(f"Best length for this type: about {g['length']} seconds (stay inside the "
                     "allowed range). Prefer the shortest clip that still holds the whole hook -> "
                     "payoff chain; cut setup that the viewer does not need.")
    return "\n".join(lines)
