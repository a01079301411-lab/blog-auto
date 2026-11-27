"""처음 설치: 부품 설치 + .env 만들기 (0_처음설치.bat)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ask(label, current=""):
    v = input(f"{label}{' [그대로 두려면 엔터]' if current else ''}: ").strip()
    return v or current


def read_env(path):
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main():
    print("1/3 부품 설치 중...")
    subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])

    env_path = ROOT / ".env"
    env = read_env(ROOT / ".env.example")
    env.update(read_env(env_path))

    print("\n2/3 공공데이터포털 인증키")
    print("   data.go.kr > 마이페이지 > 개발계정 > 아무 서비스 클릭 > '일반 인증키(Decoding)' 복사")
    env["DATA_GO_KR_KEY"] = ask("   인증키 붙여넣기", env.get("DATA_GO_KR_KEY", ""))

    print("\n3/3 텔레그램 알림 (블로그 프로그램 폴더의 .env 에 있는 값과 같아도 됩니다. 건너뛰려면 엔터)")
    blog_env = None
    for cand in (ROOT.parent / ".env", ROOT.parent.parent / ".env"):
        if cand.exists() and "TELEGRAM_BOT_TOKEN" in cand.read_text(encoding="utf-8", errors="ignore"):
            blog_env = read_env(cand)
            break
    if blog_env and not env.get("TELEGRAM_BOT_TOKEN") and blog_env.get("TELEGRAM_BOT_TOKEN"):
        env["TELEGRAM_BOT_TOKEN"] = blog_env["TELEGRAM_BOT_TOKEN"]
        env["TELEGRAM_CHAT_ID"] = blog_env.get("TELEGRAM_CHAT_ID", "")
        print("   블로그 프로그램의 텔레그램 설정을 찾아서 그대로 썼어요.")
    else:
        env["TELEGRAM_BOT_TOKEN"] = ask("   봇 토큰", env.get("TELEGRAM_BOT_TOKEN", ""))
        env["TELEGRAM_CHAT_ID"] = ask("   채팅 ID", env.get("TELEGRAM_CHAT_ID", ""))

    print("\n(선택) 나이스 교육정보 인증키 - 대구·경북 전체 학교 행정실 전화번호용")
    print("   open.neis.go.kr 회원가입 → 인증키 신청 → 복사 (건너뛰려면 엔터)")
    env["NEIS_KEY"] = ask("   나이스 인증키", env.get("NEIS_KEY", ""))
    env_path.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8")
    print("\n설정 저장 완료. 다음: 1_연결점검.bat")


if __name__ == "__main__":
    main()
