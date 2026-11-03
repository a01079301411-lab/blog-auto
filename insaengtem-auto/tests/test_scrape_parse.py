from insaengtem.scrape_yogo import clean_name, guess_qty, parse_option, parse_shipping


def test_parse():
    assert clean_name("[이남장] 설렁탕 550g_COSY 상시") == "[이남장] 설렁탕 550g"
    assert parse_shipping("배송비 2,500원 (20,000원 이상 구매 시 무료)") == (2500, 20000)
    assert parse_shipping("무료배송") == (0, None)
    assert guess_qty("60구") == (60, "알")
    assert guess_qty("50g×7포") == (7, "포")
    o = parse_option("60구 (+19,500원)", 13900)
    assert o == {"label": "60구", "price": 33400, "qty": 60, "unit": "알"}
    assert parse_option("- [필수] 옵션을 선택해 주세요 -", 100) is None
    assert parse_option("40구 (+10,000원) [품절]", 100) is None
