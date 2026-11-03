"""콘텐츠 생성: 제품 영상 JSON(v1/v2/v3) + 인스타 캡션 3개 + 스레드 본문/링크칸 3세트 + 무광고 공감글.

원칙
- 숫자(가격·단가·배송비·절감액)는 usp.py 결정값만 사용. LLM 은 숫자를 만들지 않는다.
- LLM(Claude) 은 문구만 쓴다. ANTHROPIC_API_KEY 없거나 실패/검수 불합격이면 규칙 기반 템플릿으로 대체.
- 레퍼런스는 패턴만 빌리고 문구는 새로 (qa COPY 체크).
"""
from __future__ import annotations

import json
import re

from . import qa
from .catalog import load_facts, usp_of
from .config import PRODUCTS, ROOT, TRENDS, env, settings
from .usp import UspResult, allowed_amounts, won

THEMES = json.loads((ROOT / "config" / "themes.json").read_text(encoding="utf-8"))
CATEGORY_TAGS = {
    "food": ["#장보기", "#집밥", "#살림팁"],
    "health": ["#건강간식", "#한끼대용", "#살림팁"],
    "beauty": ["#욕실템", "#살림템", "#데일리케어"],
    "living": ["#살림템", "#살림팁", "#생활꿀템"],
    "baby": ["#육아템", "#육아꿀팁", "#살림팁"],
}


def short_name(facts: dict) -> str:
    n = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", facts["name"]).strip()
    n = re.sub(r"\d+\s*(g|ml|kg|L|구|포|팩|개)\b.*$", "", n).strip()
    return n.split()[-1] if len(n) > 8 else n


def josa(word: str, a: str, b: str) -> str:
    """받침 있으면 a(이/은/을), 없으면 b(가/는/를). 숫자·영문 끝은 읽는 소리 기준 근사."""
    ch = word.strip()[-1:] or "가"
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
    else:
        has = ch in "0136781LMNlmn"
    return word + (a if has else b)


def clean_bullet(b: str, maxlen: int = 14) -> str:
    b = re.sub(r"\([^)]*\)", "", b).strip()
    if len(b) <= maxlen:
        return b
    words = b.split()
    out = ""
    for w in words:
        if len((out + " " + w).strip()) > maxlen:
            break
        out = (out + " " + w).strip()
    return out or b[:maxlen]


def pick_theme(facts: dict, key: str) -> dict:
    names = THEMES["_category_default"].get(facts.get("category", "living"), ["warm_light"])
    return dict(THEMES[names[sum(map(ord, key)) % len(names)]])


def _numeric_bullet(facts: dict):
    for b in facts.get("bullets", []):
        m = re.search(r"([가-힣A-Za-z]+)\s*(\d+)\s*(g|ml|mg|kg|L)", b)
        if m:
            return m.group(1), int(m.group(2)), m.group(3), b
    return None


# ---------------------------------------------------------------- 템플릿 ---
def template_cfg(key: str, facts: dict, u: UspResult) -> dict:
    L = u.lines
    b = u.best
    sn = short_name(facts)
    bullets = list(dict.fromkeys(clean_bullet(x, 20) for x in facts.get("bullets", [])))[:3] or [facts["name"]]
    price_short = won(b.per_unit)
    cfg = {
        "theme": pick_theme(facts, key),
        "image": facts.get("image", f"assets/products/{key}.png"),
        "tag": f"사기 전 체크 · {sn}",
        "hook": [
            {"t": f"{sn} 1{b.option.unit}", "s": 100},
            {"t": price_short, "s": 180, "style": "accent"},
            {"t": f"{clean_bullet(bullets[0])}인데?", "s": 70, "style": "mark"},
        ],
        "math": {"label": "계산해보면", "formula": L["formula"], "value": L["value"], "fmt": L["fmt"], "sub": L["ship_line"]},
        "usp": {"title": "사기 전 이것만 체크", "rows": [[x, ""] for x in bullets]},
        "variants": {},
    }
    if len(u.rows) > 1:
        best_label = b.option.label
        rows = [r for r in L["table"] if r[0] != best_label] + [r for r in L["table"] if r[0] == best_label]
        cfg["offer"] = {"type": "table", "rows": rows[-3:], "cta": "구매 링크는 프로필에"}
    else:
        cfg["offer"] = {"type": "price", "orig": f"정가 {won(facts['list_price'])}" if facts.get("list_price") else facts["name"][:16],
                        "strike_from": 0.32 if facts.get("list_price") else 1.0,
                        "price": f"{b.option.label} {won(b.option.price)}",
                        "note": L.get("discount_line") or L["ship_line"], "cta": "구매 링크는 프로필에"}
    sticker = "무료\n배송" if not b.shipping and not u.shipping_fee else f"1{b.option.unit}\n가격"
    cfg["variants"]["v1"] = {"cover": {"top": f"{sn} 사기 전"[:15], "big": price_short, "sticker": sticker}}
    # v2 퀴즈
    if len(u.rows) > 1:
        opts = [[f"{r.option.label} {'구매' if r.option.qty == 1 else won(r.option.price)}", r.text] for r in u.rows][:3]
        ans = [r.option.label for r in u.rows][:3].index(b.option.label) if b in u.rows[:3] else len(opts) - 1
        quiz = {"question": f"1{b.option.unit}당 제일 싼 건?", "options": opts, "answer": ans,
                "note": L.get("saving_line", L["ship_line"])}
        cover2 = {"top": f"{sn} {'·'.join(r.option.label for r in u.rows[:3])}"[:15], "big": "제일 싼 건?", "sticker": "3초\n퀴즈"}
    elif (nb := _numeric_bullet(facts)):
        word, n, unit, src = nb
        cand = sorted({max(1, round(n * 0.5)), max(1, round(n * 0.75)), n})
        quiz = {"question": f"이 {sn} {word}은?", "options": [[f"{c}{unit}", ""] for c in cand],
                "answer": cand.index(n), "note": src}
        cover2 = {"top": f"{sn} 한 개", "big": f"{word} 몇 {unit}?"[:7], "sticker": "3초\n퀴즈"}
    elif facts.get("list_price"):
        quiz = {"question": "오픈딜 가격은?", "options": [["정가", won(facts["list_price"])], ["오픈딜", won(b.option.price)]],
                "answer": 1, "note": L.get("discount_line", "")}
        cover2 = {"top": f"{sn} 정가 vs", "big": "얼마?", "sticker": "3초\n퀴즈"}
    else:
        quiz = {"question": f"1{b.option.unit}에 얼마일까?", "options": [[b.option.label, b.text]], "answer": 0, "note": L["ship_line"]}
        cover2 = {"top": sn, "big": "얼마?", "sticker": "3초\n퀴즈"}
    cfg["variants"]["v2"] = {"cover": cover2, "quiz": quiz}
    rb = bullets + [""] * 3
    reasons = [[rb[0], ""], [rb[1] or rb[0], rb[2]], [b.text, L["ship_line"]]]
    cfg["variants"]["v3"] = {"cover": {"top": "장바구니 넣기 전", "big": "이 3개만", "sticker": "사기 전\n체크"},
                             "reasons": reasons}
    # ---- v4~v6: 같은 레이아웃, 다른 훅 (14일 재사용 금지 규칙 대응) ----
    if len(u.rows) > 1 and u.saving_per_unit > 0:
        big4 = f"{u.saving_per_unit:,}원↓"
        top4 = f"{u.worst.option.label} 말고 {b.option.label}"
    elif L.get("discount_line"):
        big4, top4 = f"{u.discount_rate}% 할인", f"{sn} 정가 말고"
    else:
        big4, top4 = price_short, f"{sn} 한 개 값"
    cfg["variants"]["v4"] = {"layout": "v1", "cover": {"top": top4[:15], "big": big4[:7], "sticker": "아끼는\n법"}}
    free = (b.shipping == 0)
    cfg["variants"]["v5"] = {"layout": "v2", "cover": {"top": f"{sn} {b.option.label}"[:15], "big": "배송비는?", "sticker": "3초\n퀴즈"},
                             "quiz": {"question": f"{b.option.label} 사면 배송비는?",
                                      "options": [["무료배송", ""], ["배송비 있음", won(b.shipping) if b.shipping else ""]],
                                      "answer": 0 if free else 1, "note": L["ship_line"]}}
    cfg["variants"]["v6"] = {"layout": "v3", "cover": {"top": f"{sn} 결론부터", "big": price_short, "sticker": "딱\n3개"},
                             "reasons": [[b.text, L["ship_line"]], [rb[0], rb[1]], [rb[2] or rb[1] or rb[0], ""]]}
    return cfg


def hashtags(facts: dict, extra: list[str] | None = None) -> str:
    s = settings()["instagram"]
    sn = re.sub(r"[^0-9A-Za-z가-힣]", "", short_name(facts))
    tags = [f"#{sn}"] + list(extra or []) + CATEGORY_TAGS.get(facts.get("category", "living"), [])
    out: list[str] = []
    for t in tags:
        t = "#" + re.sub(r"[^0-9A-Za-z가-힣_]", "", t.lstrip("#"))
        if t not in out and t != s["hashtag_last"]:
            out.append(t)
    return " ".join(out[: s["hashtag_max"] - 1] + [s["hashtag_last"]])


def link_line(key: str, facts: dict) -> str:
    """캡션의 구매 안내. 링크샵이 있으면 번호로, 없으면 프로필 링크 이름으로."""
    from .catalog import load_catalog
    no = next((c.get("no") for c in load_catalog() if c["key"] == key), None)
    if env("SHOP_PUBLIC_URL") and no:
        return f"🔗 구매: 프로필 링크샵 → {no}번 (검색창에 {no})"
    return f"🔗 구매 링크: 프로필 링크 '{short_name(facts)}'"


def template_posts(key: str, facts: dict, u: UspResult, cfg: dict) -> dict:
    L = u.lines
    sn = short_name(facts)
    bl = facts.get("bullets", [])[:3]
    tail = "\n\n🔖 저장해두고 장 볼 때 꺼내보세요\n📩 이번 주 장 보는 사람한테 보내두기\n" + link_line(key, facts) + "\n\n" + hashtags(facts)
    table = "\n".join(f"{a} {p} ({t})" for a, p, t in L["table"]) if len(u.rows) > 1 else ""
    checks = " ".join(f"✔ {x}" for x in bl)
    q = cfg["variants"]["v2"]["quiz"]
    ig = {
        "v1": f"[광고] {facts['name']}, {L['best_text']}\n\n{L['formula']} = {L['best_text']}\n{L['ship_line']}"
              + (f"\n\n{table}" if table else "") + f"\n\n{checks}" + tail,
        "v2": f"[광고] {q['question']}\n\n" + " / ".join(o[0] for o in q["options"]) + "\n정답은 영상에서 👀\n\n"
              + f"{checks}\n\n맞히셨으면 댓글로 '정답' 🙋" + tail,
        "v3": f"[광고] {sn} 사기 전, 이 3개만 보세요\n\n"
              + "\n".join(f"0{i + 1} {r[0]}" + (f" – {r[1]}" if r[1] else "") for i, r in enumerate(cfg["variants"]["v3"]["reasons"]))
              + tail,
    }
    for v, base_v in (("v4", "v1"), ("v5", "v2"), ("v6", "v3")):
        cv = cfg["variants"][v]["cover"]
        head = f"[광고] {cv['top']} — {cv['big']}"
        if v == "v5":
            q5 = cfg["variants"]["v5"]["quiz"]
            ig[v] = (f"[광고] {q5['question']}\n\n" + " / ".join(o[0] for o in q5["options"]) + "\n정답은 영상에서 👀\n\n"
                     + f"{checks}\n\n맞히셨으면 댓글로 '정답' 🙋" + tail)
        else:
            ig[v] = head + "\n\n" + ig[base_v].split("\n", 1)[1].lstrip("\n")
    reply = f"[광고] {facts['name']} 링크예요. {L['formula']} = {L['best_text']}\n{{link}}"
    th = {
        "v1": {"text": f"[광고] {sn} 살 때 한 {u.best.option.unit}에 얼마인지 나눠보세요?\n"
                       f"큰 거 사면 당연히 싼 줄 알았는데 막상 나눠보면 아닐 때도 있더라고요.\n"
                       f"여러분은 {sn} 고를 때 뭐부터 보세요?", "reply": reply},
        "v2": {"text": f"[광고] 퀴즈 하나만 풀고 가세요\n{q['question']}\n"
                       + " / ".join(f"{i + 1}) {o[0]}" for i, o in enumerate(q["options"]))
                       + "\n번호만 댓글로 남겨주세요. 정답은 영상에 🙋", "reply": reply},
        "v3": {"text": f"[광고] 장바구니에 {sn} 넣기 전에 딱 3초만.\n"
                       + ", ".join(r[0] for r in cfg["variants"]["v3"]["reasons"][:2])
                       + ", 그리고 한 개당 가격.\n이 세 개만 봐도 실패가 확 줄어요. 여러분 기준은 뭐예요?", "reply": reply},
    }
    q5 = cfg["variants"]["v5"]["quiz"]
    th["v4"] = {"text": f"[광고] 장 볼 때 '조금 더 큰 걸로' 고민되는 순간 있잖아요.\n"
                        f"{sn}도 나눠보면 차이가 꽤 나더라고요.\n여러분은 큰 거 쟁이는 편이에요, 그때그때 사는 편이에요?", "reply": reply}
    th["v5"] = {"text": f"[광고] 온라인 장보기 할 때 배송비 보고 장바구니 닫은 적 있는 사람 🙋\n"
                        f"{q5['question']}\n1) 무료배송  2) 배송비 있음\n번호만 남겨주세요.", "reply": reply}
    th["v6"] = {"text": f"[광고] 결론부터 말하는 거 좋아하는 분들 계시죠.\n"
                        f"{sn} 사기 전에 볼 건 딱 세 개예요. 가격, {', '.join(r[0] for r in cfg['variants']['v6']['reasons'][1:])}.\n"
                        f"여러분은 뭐부터 보세요?", "reply": reply}
    return {"instagram": ig, "threads": th, "hashtags": hashtags(facts), "generator": "template"}


EMPATHY_FALLBACK = [
    "택배 뜯다가 '이거 왜 샀더라?' 하는 거 저만 그래요?\n이번 달에 그런 거 하나만 말해주세요.",
    "장 볼 때 1+1이랑 대용량 중에 뭐가 이득인지\n매번 계산기 두드리는 사람 손 🙋\n여러분은 장 볼 때 뭐부터 보세요?",
    "다음 주 '사기 전 체크' 뭐부터 할까요?\n1 세제  2 기저귀  3 냉동밥\n번호만 남겨주세요.",
    "할인율 70%보다 '한 개당 얼마'가 더 와닿지 않아요?\n할인율에 낚여서 산 거 하나만 고백해주세요.",
    "이번 주에 산 것 중에 제일 잘 산 거 하나만 자랑해주세요.\n다음 주 비교 주제로 쓸게요.",
    "장바구니에 넣어두고 일주일째 결제 못 한 거 있는 사람?\n뭔지 하나만 말해주세요. 같이 따져볼게요.",
    "냉동실 열면 뭐가 들었는지 모르는 집 저만 그래요?\n지금 냉동실에 제일 많은 거 하나만 🙋",
    "애들 간식 한 달에 얼마 쓰는지 계산해본 적 있으세요?\n1 5만원 이하  2 5~10만원  3 10만원 넘음",
    "택배 상자 뜯는 속도보다 쌓이는 속도가 빠른 집 손 🙋\n일주일에 택배 몇 개 오세요?",
    "마트 갈 때 장보기 목록 쓰는 편이에요, 그냥 가는 편이에요?\n목록 써도 꼭 하나씩 더 사오게 되더라고요.",
    "세일한다고 쟁였는데 유통기한 지나서 버린 거 있는 사람?\n제일 아까웠던 거 하나만.",
    "'이건 진짜 잘 샀다' 싶은 만원 이하 살림템 하나씩만 추천해주세요.\n모아서 다음 주에 정리해볼게요.",
    "배송비 3,000원 아끼려고 필요 없는 거 하나 더 담아본 적 있죠?\n그때 뭐 담으셨어요?",
    "주말에 장 몰아서 보는 집이에요, 매일 조금씩 보는 집이에요?\n1 몰아서  2 매일",
]


# ---------------------------------------------------------------- LLM ---
SYSTEM = """너는 '인생템연구소'(@insaengtem_lap) 숏폼 카피라이터다. 타깃: 살림·육아하는 30~40대 부부.
얼굴·실물 촬영 없이 숫자 비교 + 퀴즈 + 체크리스트로 '안 사면 손해' 느낌을 만든다.

절대 규칙
1. 숫자(가격·단가·배송비·할인율·용량·인증)는 입력 FACTS·LOCKED_NUMBERS 에 있는 것만. 새 숫자를 만들지 않는다.
2. 1인칭 사용 후기 금지: "써봤", "먹어봤", "바꿨어요", "저희 집은 이거 써요", "들고 나가요" 등. 스펙 비교·질문 톤.
3. 효능 보장/의학 표현 금지(치료, 완치, 100%, 부작용 없음). 최고·1위 등 근거 없는 최상급 금지.
4. 광고 게시물 첫 줄은 반드시 "[광고]". 무광고 공감글(empathy)은 [광고] 없이, 제품명·링크도 없이.
5. 커버 big 7자 이내(숫자나 질문), top 15자 이내, sticker 는 2줄(\\n) 각 4자 이내.
6. 스레드 본문(text)은 공감 질문형, 답글이 1단어/번호로 가능하게 끝낸다. 링크·URL 금지. 제품명·계산은 2번째 칸(reply).
   reply 는 "[광고] ... 링크예요" + 마지막 줄 정확히 "{link}".
7. 인스타 캡션 끝 고정 순서: "🔖 저장해두고 … 꺼내보세요" / "📩 … 보내두기"(보낼 대상 명확히) / "🔗 구매 링크는 프로필에" / 해시태그 정확히 5개, 마지막 #사기전에.
8. 레퍼런스는 구조·훅 패턴만 빌리고 문구는 새로 쓴다. 레퍼런스 문장을 베끼지 않는다.
9. 출력은 JSON 하나. 설명 금지."""

SCHEMA_HINT = {
    "hook": ["줄1(10자 내외)", "줄2(핵심 숫자/단어, 8자 이내)", "줄3(반전·보강, 16자 이내)"],
    "usp_title": "15자 이내",
    "usp_rows": [["제목", "부연(없으면 빈 문자열)"], ["", ""], ["", ""]],
    "covers": {"v1": {"top": "", "big": "", "sticker": "두\n줄"}, "v2": {"top": "", "big": "", "sticker": "3초\n퀴즈"},
               "v3": {"top": "", "big": "", "sticker": ""}},
    "reasons": [["제목", "부연"], ["", ""], ["", ""]],
    "instagram": {"v1": "캡션", "v2": "캡션", "v3": "캡션"},
    "threads": {"v1": {"text": "", "reply": "[광고] ... 링크예요\n{link}"}, "v2": {"text": "", "reply": ""},
                "v3": {"text": "", "reply": ""}},
    "empathy": ["무광고 공감글 1", "공감글 2", "공감글 3"],
    "patterns_used": ["패턴 id"],
}


def _client():
    try:
        import anthropic
    except ImportError:
        return None
    if not (env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN")):
        return None
    return anthropic.Anthropic()


def _references(limit: int = 8) -> list[dict]:
    p = TRENDS / "latest.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("references", [])[:limit]


def llm_creative(key: str, facts: dict, u: UspResult, base: dict, feedback: str = "") -> dict | None:
    client = _client()
    if client is None:
        return None
    import anthropic
    s = settings()["llm"]
    patterns = json.loads((TRENDS / "patterns.json").read_text(encoding="utf-8"))
    refs = _references()
    user = {
        "FACTS": {k: facts.get(k) for k in ("name", "category", "bullets", "list_price", "sale_price", "shipping_fee", "free_over", "options")},
        "LOCKED_NUMBERS": u.lines,
        "QUIZ_V2(고정, 문구만 참고)": base["variants"]["v2"]["quiz"],
        "PATTERNS": {k: [{x: p[x] for x in ("id", "name", "structure", "weight")} for p in patterns[k]] for k in ("instagram", "threads")},
        "REFERENCES(패턴만 참고, 문구 복사 금지)": [{"platform": r.get("platform"), "first_line": r.get("first_line"),
                                             "pattern": r.get("patterns"), "score": r.get("score")} for r in refs],
        "OUTPUT_SHAPE": SCHEMA_HINT,
    }
    if feedback:
        user["FIX_THESE_ISSUES"] = feedback
    kwargs = dict(model=s["model"], max_tokens=s["max_tokens"], system=SYSTEM,
                  output_config={"effort": s.get("effort", "medium")},
                  messages=[{"role": "user", "content": json.dumps(user, ensure_ascii=False)}])
    try:
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)  # fallbacks 미지원 환경
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
        print(f"[llm] 호출 실패 → 템플릿 사용: {e}")
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"[llm] stop_reason={resp.stop_reason} → 템플릿 사용")
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def merge_creative(base: dict, posts: dict, c: dict) -> tuple[dict, dict]:
    cfg = json.loads(json.dumps(base))
    sizes = [100, 170, 70]
    styles = [None, "accent", "mark"]
    if len(c.get("hook", [])) == 3:
        cfg["hook"] = [{"t": t, "s": sizes[i], **({"style": styles[i]} if styles[i] else {})} for i, t in enumerate(c["hook"])]
    if c.get("usp_title"):
        cfg["usp"]["title"] = c["usp_title"]
    if len(c.get("usp_rows", [])) == 3:
        cfg["usp"]["rows"] = [list(r)[:2] for r in c["usp_rows"]]
    for v in ("v1", "v2", "v3"):
        cv = c.get("covers", {}).get(v)
        if cv:
            cfg["variants"][v]["cover"] = {k: cv.get(k) or cfg["variants"][v]["cover"][k] for k in ("top", "big", "sticker")}
    if len(c.get("reasons", [])) == 3:
        cfg["variants"]["v3"]["reasons"] = [list(r)[:2] for r in c["reasons"]]
    p = json.loads(json.dumps(posts))
    for v in ("v1", "v2", "v3"):
        if c.get("instagram", {}).get(v):
            p["instagram"][v] = c["instagram"][v]
        t = c.get("threads", {}).get(v)
        if t and t.get("text") and t.get("reply"):
            p["threads"][v] = {"text": t["text"], "reply": t["reply"]}
    if c.get("empathy"):
        p["empathy"] = c["empathy"]
    p["generator"] = "llm:" + settings()["llm"]["model"]
    p["patterns_used"] = c.get("patterns_used", [])
    return cfg, p


def check_all(key: str, facts: dict, u: UspResult, cfg: dict, posts: dict) -> list[qa.Issue]:
    allowed = allowed_amounts(u, [facts.get("list_price") or 0, facts.get("sale_price") or 0])
    refs = [r.get("text", "") for r in _references(50)]
    issues = qa.check_product_cfg(cfg, facts, allowed, key)
    for v, cap in posts["instagram"].items():
        issues += qa.check_text(cap, where=f"{key}.ig.{v}", is_ad=True, allowed=allowed, platform="instagram", references=refs)
    for v, t in posts["threads"].items():
        issues += qa.check_text(t["text"], where=f"{key}.th.{v}.text", is_ad=True, allowed=allowed, platform="threads_root", references=refs)
        issues += qa.check_text(t["reply"], where=f"{key}.th.{v}.reply", is_ad=True, allowed=allowed, platform="threads_reply")
    for i, e in enumerate(posts.get("empathy", [])):
        issues += qa.check_text(e, where=f"{key}.empathy{i}", is_ad=False, platform="threads_root", references=refs)
        if "[광고]" in e or "yo-go" in e:
            issues.append(qa.Issue("error", "EMPATHY_AD", "무광고 공감글에 광고/링크", f"{key}.empathy{i}"))
    return issues


def generate(key: str, use_llm: bool = True, write: bool = True, keep_existing_cfg: bool = False) -> tuple[dict, dict, list]:
    facts = load_facts(key)
    if facts.get("soldout"):
        raise SystemExit(f"{key}: 품절 → 제작 제외")
    u = usp_of(facts)
    base = template_cfg(key, facts, u)
    posts = template_posts(key, facts, u, base)
    posts["empathy"] = EMPATHY_FALLBACK[:3]
    cfg = base
    if use_llm:
        c = llm_creative(key, facts, u, base)
        if c:
            cfg2, posts2 = merge_creative(base, posts, c)
            issues = [i for i in check_all(key, facts, u, cfg2, posts2) if i.level == "error"]
            if issues:
                c = llm_creative(key, facts, u, base, feedback="\n".join(map(str, issues)))
                if c:
                    cfg2, posts2 = merge_creative(base, posts, c)
                    issues = [i for i in check_all(key, facts, u, cfg2, posts2) if i.level == "error"]
            if not issues:
                cfg, posts = cfg2, posts2
            else:
                print(f"[llm] 검수 불합격 {len(issues)}건 → 템플릿 사용")
        else:
            print("[gen] LLM 미사용(키 없음/실패) → 규칙 기반 템플릿")
    if keep_existing_cfg and (PRODUCTS / f"{key}.json").exists():
        # 사람이 다듬은 기존 영상 JSON 은 유지하고, 없는 버전(v4~v6 등)만 채운다
        old = json.loads((PRODUCTS / f"{key}.json").read_text(encoding="utf-8"))
        for v, d in cfg["variants"].items():
            old["variants"].setdefault(v, d)
        cfg = old
    issues = check_all(key, facts, u, cfg, posts)
    if write:
        (PRODUCTS / f"{key}.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        (PRODUCTS / f"{key}.posts.json").write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg, posts, issues
