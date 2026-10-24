"""サイト構造（2026-10-22時点で確認）を模したHTMLでパーサを確認する。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import kaitori_wiki, kaitori_shouten, morimori  # noqa: E402
import yahoo  # noqa: E402

WIKI = """
<div>314件該当しました。</div>
<div class="pro-border gutter-10 row pro_list"><div><a href="/product/detail/1">img</a>
 <div class="sub-pro"><div class="sub-pro-name">REPRONIZER リュミエリーナ REP4D-JP 4562183854109</div></div>
 <p>正規代理店の購入証明(納品書、レシート等)のご提示が必要となります。</p>
 <p>JAN：4562183854109</p><p>買取価格: 47,500円</p></div></div>
<div class="pro-border gutter-10 row pro_list"><div class="sub-pro"><div class="sub-pro-name">MTG ReFa RE-AF00A 4573176151419</div></div>
 <p>JAN：4573176151419</p><p>買取価格:&nbsp;14,700円</p></div>
"""

SHOUTEN_CAT = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
{"@type":"ListItem","position":1,"name":"AirPods Pro 第3世代 MFHP4J/A","url":"https://www.kaitorishouten-co.jp/products/detail/24586"}]}</script>
<a href="/category/2/277?page=2">2</a>"""
SHOUTEN_DETAIL = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"AirPods Pro 第3世代 MFHP4J/A",
"gtin13":"4549995635232","category":"家電","url":"https://www.kaitorishouten-co.jp/products/detail/24586",
"offers":{"@type":"Offer","price":32500,"priceCurrency":"JPY"}}</script>"""
SHOUTEN_HOME = '<a href="/category/1/17">iPhone</a><a href="/category/2/277">AirPods</a><a href="/category/3/5">山崎</a>'

MORI = """<div>該当 205 件（1〜50件を表示・50件/ページ）</div>
<div class="mm1551-prow"><div class="mm1551-prow__info"><div class="mm1551-prow__name">SONY プレイステーション5 CFI-2200B01</div>
<div class="mm1551-prow__meta">JAN:4948872417419 状態 新品</div></div>
<div class="mm1551-prow__price"><div class="mm1551-prow__cur"><span class="mm1551-prow__cur-label">現在価格</span>
<span class="mm1551-prow__cur-val">49,800円</span></div><div class="mm1551-prow__keep">預かり 50,536円</div></div></div>
<div class="mm1551-prow"><div class="mm1551-prow__name">中古品</div><div class="mm1551-prow__meta">JAN:4948872417410 状態 中古</div>
<span class="mm1551-prow__cur-val">30,000円</span></div>"""


def test_wiki():
    items, count, per = kaitori_wiki.parse_list(WIKI, "hair-dryer")
    assert count == 314 and per == 2 and len(items) == 2
    assert items[0]["jan"] == "4562183854109" and items[0]["price"] == 47500
    assert items[0]["note"] == "購入証明必要"
    assert items[0]["name"].endswith("REP4D-JP")
    assert items[1]["price"] == 14700


def test_shouten():
    assert kaitori_shouten.list_categories(SHOUTEN_HOME) == ["/category/1/17", "/category/2/277"]
    urls, nexts = kaitori_shouten.parse_category(SHOUTEN_CAT)
    assert urls == ["https://www.kaitorishouten-co.jp/products/detail/24586"]
    assert nexts == ["/category/2/277?page=2"]
    it = kaitori_shouten.parse_product(SHOUTEN_DETAIL)
    assert it["jan"] == "4549995635232" and it["price"] == 32500


def test_morimori():
    items, count, per = morimori.parse_list(MORI, "01")
    assert count == 205 and per == 2
    assert len(items) == 1  # 中古は除外
    assert items[0]["jan"] == "4948872417419" and items[0]["price"] == 49800


class FakeClient:
    def __init__(self, data):
        self.data = data

    def get(self, *a, **k):
        return self.data


def test_yahoo_filter():
    hit = lambda name, price, jan="4549995635232", pt=0: {  # noqa: E731
        "name": name, "price": price, "janCode": jan, "url": "u",
        "point": {"lyLimitedBonusAmount": pt}, "seller": {"name": "s"}, "shipping": {"code": 2}}
    data = {"hits": [
        hit("AirPods Pro 3 新品", 33000, pt=300),
        hit("AirPods Pro 3 外箱傷みあり", 30000),
        hit("イヤーチップ 交換用", 1500),
        hit("別JAN商品", 20000, jan="1234567890123"),
        hit("AirPods Pro 3", 32900),
    ]}
    offers = yahoo.search_jan(FakeClient(data), "id", "4549995635232", 32500)
    assert [o["p"] for o in offers] == [33000, 32900]  # ポイント差引後の安い順


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def _page(item):
    import json
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"item": item}}}) + "</script>"


def test_item_page_variants():
    two_axis = {"applicablePrice": 25850, "stockTableTwoAxis": {"firstOption": {"choiceList": [
        {"choiceName": "150P/右", "secondOption": {"choiceList": [{"choiceName": "220g", "price": None, "skuId": "4550133120602"}]}},
        {"choiceName": "150PL/左", "secondOption": {"choiceList": [{"choiceName": "220g", "price": 27000, "skuId": "4550133120619"}]}},
    ]}}, "selectOptionList": [{"name": "コーティング", "choiceList": [{"charge": None}, {"charge": 3190}]}]}
    # JAN一致の選択肢の価格。任意オプション（無料の選択肢あり）は加算しない
    assert yahoo.parse_item_page(_page(two_axis), "4550133120619") == {"base": 25850, "jp": 27000, "min": 25850, "max": 27000, "add": 0, "ng": ""}

    one_axis = {"applicablePrice": 30000, "stockTableOneAxis": {"firstOption": {"choiceList": [
        {"choiceName": "128GB", "price": None, "skuId": "a"}, {"choiceName": "256GB", "price": 38000, "skuId": "b"}]}},
        "selectOptionList": [{"name": "保証", "choiceList": [{"charge": 500}, {"charge": 1500}]}]}
    info = yahoo.parse_item_page(_page(one_axis), "4900000000000")
    assert info["jp"] is None and info["min"] == 30000 and info["max"] == 38000 and info["add"] == 500

    # check_offer: 一致なし → 高い方＋必須オプション。ポイントも比例して補正
    class C:
        def get(self, url):
            return _page(one_axis)
    o = {"p": 30000, "pp": 30000, "pt": 300, "ptp": 300, "u": "https://store.shopping.yahoo.co.jp/x/1.html"}
    assert yahoo.check_offer(C(), o, "4900000000000")
    assert o["p"] == 38500 and o["pv"] == [30000, 38000] and o["add"] == 500 and o["pt"] == 385

    # 仕様選択なし・必須オプションなし → 変更なし
    plain = {"applicablePrice": 30000, "selectOptionList": [{"name": "同意", "choiceList": [{"charge": None}]}]}
    class P:
        def get(self, url):
            return _page(plain)
    o2 = {"p": 30000, "pt": 300, "u": "https://store.shopping.yahoo.co.jp/x/2.html"}
    assert not yahoo.check_offer(P(), o2, "1") and o2["p"] == 30000
    assert yahoo.parse_item_page("<html></html>", "1") is None


if __name__ == "__main__":
    test_item_page_variants()
    print("ok test_item_page_variants")


def test_resolve_variant():
    import run
    g = {"variants": [
        {"sel": {"color": "スペースブラック", "gb": "256GB"}, "p": 168500},
        {"sel": {"color": "シルバー", "gb": "256GB"}, "p": 168500},
        {"sel": {"color": "シルバー", "gb": "512GB"}, "p": 205000},
        {"sel": {"color": "シルバー", "gb": "2TB"}, "p": 268000},
    ]}
    names = ["Apple iPad Pro 11インチ Wi-Fi 256GB 2025年秋モデル MDWL4J/A [シルバー]"]
    assert run.resolve_variant(g, names) == (168500, "シルバー 256GB")
    # 色が名前に無くても、その容量が全色同じ価格なら確定
    assert run.resolve_variant(g, ["iPad Pro 11 256GB"]) == (168500, "256GB")
    # 容量が分からなければ確定しない
    assert run.resolve_variant(g, ["iPad Pro 11インチ"]) is None
    # 全角表記ゆれ
    assert run.resolve_variant(g, ["ｉＰａｄ　Ｐｒｏ　５１２ＧＢ　シルバー"]) == (205000, "シルバー 512GB")
    assert run.is_multi_spec("wiki", {"name": "iPad Pro 11インチ (M5) Wi-Fi 2025年秋モデル", "url": "https://ipadkaitori.jp/x"})
    assert not run.is_multi_spec("wiki", {"name": "MacBook Neo 13インチ MHFA4J/A シルバー", "url": "https://pckaitori.tokyo/x"})


if __name__ == "__main__":
    test_resolve_variant()
    print("ok test_resolve_variant")


def test_item_page_stock():
    page = _page({"applicablePrice": 1000, "stock": {"isAvailable": False}})
    assert yahoo.parse_item_page(page, "1")["ng"] == "在庫なし"
    assert yahoo.parse_item_page(_page({"applicablePrice": 1000, "isUsed": True}), "1")["ng"] == "中古"
    assert yahoo.parse_item_page(_page({"applicablePrice": 1000, "stock": {"isAvailable": True}, "preOrderType": "None"}), "1")["ng"] == ""
    class C:
        def get(self, url):
            return page
    o = {"p": 1000, "pt": 10, "u": "https://store.shopping.yahoo.co.jp/x/1.html"}
    assert yahoo.check_offer(C(), o, "1") and o["ng"] == "在庫なし"


if __name__ == "__main__":
    test_item_page_stock()
    print("ok test_item_page_stock")


def test_choice_by_name():
    item = {"applicablePrice": 178000, "stockTableOneAxis": {"firstOption": {"choiceList": [
        {"choiceName": "ブラック", "price": None, "skuId": "3220-CAN-0019", "stock": {"isAvailable": False}},
        {"choiceName": "シルバー", "price": None, "skuId": "3220-CAN-0020", "stock": {"isAvailable": True}}]}},
        "stock": {"isAvailable": True}}
    info = yahoo.parse_item_page(_page(item), "4549292137743", ["デジタルカメラ PowerShot G7 X Mark III [ブラック]"])
    assert info["jp"] == 178000 and info["ng"] == "在庫なし"
    info = yahoo.parse_item_page(_page(item), "4549292137804", ["PowerShot G7 X Mark III [シルバー]"])
    assert info["ng"] == ""


if __name__ == "__main__":
    test_choice_by_name()
    print("ok test_choice_by_name")


def test_select_option_model():
    item = {"applicablePrice": 32753, "stock": {"isAvailable": True}, "selectOptionList": [{"name": "種類を選べる", "choiceList": [
        {"charge": None, "isSelectable": True, "name": "YJFD1N　ゴールド（4737）"},
        {"charge": None, "isSelectable": False, "name": "SP　YJFD2L　ネイビー（4836）"}]}]}
    info = yahoo.parse_item_page(_page(item), "4540790464836", ["YA-MAN ヤーマン 美顔器 EMS リフトロジーSP YJFD2L"])
    assert info["ng"] == "在庫なし", info
    info = yahoo.parse_item_page(_page(item), "x", ["YA-MAN リフトロジー YJFD1N ゴールド"])
    assert info["ng"] == "" and info["add"] == 0


if __name__ == "__main__":
    test_select_option_model()
    print("ok test_select_option_model")
