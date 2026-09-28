"""2단계: 기사를 AI(GPT 또는 Claude)에게 보내 블로그 글을 만든다.

.env에 API 키가 없으면 '수동 모드'로 동작한다:
프롬프트 파일을 만들어 주면, 그걸 claude.ai나 ChatGPT 사이트에 붙여 넣고 결과를 다시 붙여 넣으면 된다.
(영상에서 하던 방식과 똑같다)
"""
import os
from datetime import datetime

from common import POSTS_DIR, ROOT


def build_prompt(article):
    template = (ROOT / "prompt.txt").read_text(encoding="utf-8")
    return (
        template.replace("{title}", article["title"])
        .replace("{url}", article["url"])
        .replace("{body}", article["body"])
    )


def ask_openai(prompt):
    from openai import OpenAI

    client = OpenAI()  # .env의 OPENAI_API_KEY를 자동으로 사용
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def ask_claude(prompt):
    import anthropic

    client = anthropic.Anthropic()  # .env의 ANTHROPIC_API_KEY를 자동으로 사용
    response = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def ask_manually(prompt, post_path):
    prompt_path = post_path.with_name(post_path.stem + "_프롬프트.txt")
    prompt_path.write_text(prompt, encoding="utf-8")
    post_path.write_text("", encoding="utf-8")
    print("\n[수동 모드] API 키가 없어서 직접 AI 사이트(claude.ai 또는 ChatGPT)를 사용합니다.")
    print(f"  1) 이 파일 내용을 전부 복사해서 claude.ai(또는 ChatGPT)에 붙여 넣으세요: {prompt_path}")
    print(f"  2) AI가 쓴 글을 이 파일에 붙여 넣고 저장하세요:   {post_path}")
    input("  다 했으면 Enter... ")
    return post_path.read_text(encoding="utf-8")


def write_post(article):
    """기사로 블로그 글을 만들어 posts 폴더에 저장하고, 파일 경로를 돌려준다."""
    post_path = POSTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}.txt"
    prompt = build_prompt(article)

    if os.getenv("OPENAI_API_KEY"):
        print("GPT가 글을 쓰는 중...")
        text = ask_openai(prompt)
    elif os.getenv("ANTHROPIC_API_KEY"):
        print("Claude가 글을 쓰는 중...")
        text = ask_claude(prompt)
    else:
        text = ask_manually(prompt, post_path)

    post_path.write_text(text.strip() + "\n", encoding="utf-8")
    return post_path
