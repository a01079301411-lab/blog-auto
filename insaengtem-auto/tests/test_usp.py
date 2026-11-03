from insaengtem.usp import Option, allowed_amounts, unit_prices


def test_egg_unit_prices_and_approx():
    r = unit_prices([Option("20구", 13900, 20, "알"), Option("40구", 23900, 40, "알"), Option("60구", 33400, 60, "알")])
    assert r.best.option.label == "60구"
    assert r.best.per_unit == 557 and not r.best.exact
    assert r.best.text == "1알 약 557원"
    assert r.rows[0].text == "1알 695원"            # 나눠떨어짐 → '약' 없음
    assert r.rows[1].per_unit == 598                  # 597.5 → 반올림(ROUND_HALF_UP)
    assert r.lines["formula"] == "60구 33,400원 ÷ 60"
    assert r.lines["fmt"] == "1알 약 {}원"
    assert r.lines["ship_line"] == "무료배송이라 추가 비용 0원"
    assert r.lines["saving_line"] == "60구가 20구보다 1알 약 138원 저렴"


def test_shipping_included_and_josa():
    r = unit_prices([Option("1팩", 8900, 1, "팩"), Option("4팩", 30800, 4, "팩")], shipping_fee=3500)
    assert r.best.per_unit == 7700 and r.best.exact
    assert r.lines["ship_line"] == "배송비 3,500원까지 넣어도 1팩 8,575원"
    assert r.lines["saving_line"].startswith("4팩이 ")


def test_free_over_threshold():
    r = unit_prices([Option("단품", 28900, 1, "통"), Option("2종", 57600, 2, "통")], shipping_fee=3000, free_over=50000)
    assert r.rows[0].shipping == 3000 and r.rows[1].shipping == 0


def test_discount_and_allowed():
    r = unit_prices([Option("7포", 30900, 7, "포")], shipping_fee=3500, list_price=38500, sale_price=30900)
    assert r.discount_rate == 20
    assert r.best.text == "1포 약 4,414원"
    a = allowed_amounts(r)
    assert {30900, 4414, 3500, 4914} <= a
