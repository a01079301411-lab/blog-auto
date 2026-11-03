"""처음 설치 도우미: 0_처음설치.bat 을 더블클릭하면 실행된다.

필요한 부품 설치 → 크롬 부품 설치 → .env 설정 파일 만들기 → 메모장으로 열기
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(step, args):
    print(f"\n[{step}] 진행 중... (몇 분 걸릴 수 있어요)")
    result = subprocess.run([sys.executable, *args], cwd=ROOT)
    if result.returncode != 0:
        print(f"\n[{step}] 실패했어요. 이 화면을 캡처해서 보내 주세요.")
        input("Enter를 누르면 닫힙니다...")
        sys.exit(1)
    print(f"[{step}] 완료")


def main():
    print("블로그 자동화 프로그램 설치를 시작합니다.")
    run("1/3 부품 설치", ["-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"])
    run("2/3 크롬 부품 설치", ["-m", "playwright", "install", "chromium"])

    env, example = ROOT / ".env", ROOT / ".env.example"
    print("\n[3/3 설정 파일]")
    if env.exists():
        print(".env 파일이 이미 있어요. 그대로 둡니다.")
    else:
        shutil.copy(example, env)
        print(".env 파일을 만들었어요. 곧 메모장이 열리면 아래 항목을 채우고 Ctrl + S로 저장하세요.")
        print("  BLOG_ID, ANTHROPIC_API_KEY, COMPANY_PHONE")
        if sys.platform == "win32":
            subprocess.Popen(["notepad", str(env)])

    print("\n설치 끝! 다음 순서로 진행하세요.")
    print("  1) .env 저장을 마쳤는지 확인")
    print("  2) 1_네이버로그인 더블클릭 → 크롬에서 로그인")
    print("  3) 2_글미리보기 로 글이 잘 만들어지는지 확인")


if __name__ == "__main__":
    main()
