from datetime import date

from insaengtem.schedule import build_week, load_week1, validate


def test_week1_has_known_violation():
    issues = [i for i in validate(load_week1()) if i.level == "error"]
    assert any(i.code == "SAME_PRODUCT_DAY" and "2026-11-05" in i.where for i in issues)


def test_build_week_respects_rules():
    plan, notes = build_week(date(2026, 11, 9), days=7, products=["egg", "seolleong", "shake", "shampoo"])
    errs = [i for i in validate(plan) if i.level == "error"]
    assert not errs, errs
    ig = [p for p in plan if p["platform"] == "instagram"]
    assert len(ig) == 21                                  # 7일×3슬롯, 4제품×6버전 풀
    assert any("threads: 빈 슬롯" in n for n in notes)     # 스레드 28슬롯 > 24영상 → 부족 알림
    th_text = [p for p in plan if p["platform"] == "threads" and p["kind"] == "text"]
    assert all(p["when_kst"].endswith("00:00") for p in th_text)


def test_reuse_block_from_history():
    hist = [{"platform": "instagram", "when_kst": "2026-11-05 12:30", "product": "egg", "variant": "v1"}]
    plan, _ = build_week(date(2026, 11, 9), days=7, products=["egg"], history=hist)
    assert not any(p["platform"] == "instagram" and p["variant"] == "v1" for p in plan)
