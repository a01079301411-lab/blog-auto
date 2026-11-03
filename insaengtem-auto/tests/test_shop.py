import json

from insaengtem import catalog


def test_bulk_add_and_skip(tmp_path, monkeypatch):
    cat = [{"key": "egg", "product_no": 3874, "no": 1, "available": True}]
    store = {"cat": cat}
    monkeypatch.setattr(catalog, "load_catalog", lambda: json.loads(json.dumps(store["cat"])))
    monkeypatch.setattr(catalog, "save_catalog", lambda c: store.__setitem__("cat", c))
    monkeypatch.setattr(catalog, "LINKS_FILE", tmp_path / "links.json")
    monkeypatch.setattr(catalog, "SECRETS", tmp_path)
    txt = ("https://yo-go.co.kr/product/detail.html?product_no=3874&sl=AAA111\n"
           "메모 https://yo-go.co.kr/product/detail.html?product_no=5555&sl=BBB222, "
           "https://yo-go.co.kr/product/detail.html?product_no=6666")
    r = catalog.add_links_bulk(txt)
    assert r["updated"] == ["egg"] and r["added"] == ["p5555"] and len(r["skipped"]) == 1
    new = [c for c in store["cat"] if c["key"] == "p5555"][0]
    assert new["no"] == 2
    assert "sl=BBB222" in json.loads((tmp_path / "links.json").read_text())["p5555"]
    assert "sl=" not in new["link"]


def test_guess_category():
    assert catalog.guess_category("[이남장] 설렁탕 550g") == "food"
    assert catalog.guess_category("하기스 기저귀 4단계") == "baby"
    assert catalog.guess_category("무언가") == "etc"
