"""처음 한 번만 실행: 크롬 창에서 직접 네이버에 로그인하면 로그인 상태가 저장된다.

실행:  python login.py
"""
from common import is_logged_in, open_browser

with open_browser() as page:
    page.goto("https://nid.naver.com/nidlogin.login")
    print("열린 크롬 창에서 네이버에 직접 로그인하세요.")
    print("(보안을 위해 아이디/비밀번호는 프로그램에 저장하지 않습니다)")
    print("※ '로그인 상태 유지'를 체크하면 더 오래 유지됩니다.")
    input("로그인을 마쳤으면 여기서 Enter를 누르세요... ")

    if is_logged_in(page):
        print("로그인 성공! 이제 python main.py 로 글을 발행할 수 있어요.")
    else:
        print("로그인이 확인되지 않았어요. 다시 python login.py 를 실행해 주세요.")
