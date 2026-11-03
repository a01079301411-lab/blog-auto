from insaengtem import qa


def test_ad_label_and_banned():
    iss = qa.check_text("요즘은 쿨링 샴푸로 바꿨어요", where="t", is_ad=True)
    codes = {i.code for i in iss}
    assert "AD_LABEL" in codes and "BANNED" in codes


def test_hashtag_limit_and_number():
    cap = "[광고] 1알 557원\n📩 보내두기\n#a #b #c #d #e #사기전에"
    iss = qa.check_text(cap, where="c", is_ad=True, platform="instagram", allowed={557})
    assert any(i.code == "HASHTAG_MAX" for i in iss)
    iss = qa.check_text("[광고] 1알 600원", where="c", is_ad=True, allowed={557})
    assert any(i.code == "NUMBER" for i in iss)


def test_threads_root_link_and_nfd():
    iss = qa.check_text("[광고] 링크 https://x.y", where="r", is_ad=True, platform="threads_root")
    assert any(i.code == "TH_ROOT_LINK" for i in iss)
    nfd = "바꿨어요".encode().decode()
    import unicodedata
    iss = qa.check_text(unicodedata.normalize("NFD", nfd), where="n", is_ad=False)
    assert any(i.code == "UNICODE_NFC" for i in iss)


def test_copy_guard():
    ref = "택배 오면 이거 왜 샀더라 하는 사람 저만 그래요?"
    iss = qa.check_text("택배 오면 이거 왜 샀더라 하는 사람 저만?", where="x", is_ad=False, references=[ref])
    assert any(i.code == "COPY" for i in iss)


def test_math_check():
    cfg = {"math": {"formula": "4팩 30,800원 ÷ 4", "value": 7600, "fmt": "1팩 {}원"}, "variants": {}}
    assert any(i.code == "MATH" for i in qa.check_product_cfg(cfg, None, None, "k"))
