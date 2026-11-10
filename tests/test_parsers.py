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


def test_bara():
    item = {"applicablePrice": 5010, "stock": {"isAvailable": True},
            "caption": "Nintendo Switch 選べるカラー Joy-Con (左または右) 純正品<br>※Joy-Conの単品販売（左または右）となります。外箱は付属できません。"}
    assert yahoo.parse_item_page(_page(item), "4902370544060")["ng"] == "ばら売り"
    item["caption"] = "新品未開封のメーカー正規品です。"
    assert yahoo.parse_item_page(_page(item), "4902370544060")["ng"] == ""


if __name__ == "__main__":
    test_bara()
    print("ok test_bara")


def test_postage():
    import json
    def page(pg):
        return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"item": {"applicablePrice": 7898}, "postage": pg}}}) + "</script>"
    i = yahoo.parse_item_page(page({"fee": 660, "prefecture": "愛知県", "conditionFreeText": "同一ストア15,000円以上で", "isPostageFree": False}), "1")
    assert i["sf"] == 660 and i["sfc"] == 15000
    i = yahoo.parse_item_page(page({"fee": 0, "isPostageFree": True, "conditionFreeText": ""}), "1")
    assert i["sf"] == 0 and "sfc" not in i
    class C:
        def get(self, url):
            return page({"fee": 1400, "conditionFreeText": ""})
    o = {"p": 7898, "pt": 0, "u": "https://store.shopping.yahoo.co.jp/x/1.html"}
    yahoo.check_offer(C(), o, "1")
    assert o["sf"] == 1400


if __name__ == "__main__":
    test_postage()
    print("ok test_postage")


def test_rakuten():
    import rakuten
    class C:
        def __init__(self): self.h = None
        def get(self, url, params=None, as_json=False, headers=None):
            self.h = headers; self.url = url
            return {"Items": [
                {"itemName": "SONY WH-1000XM5 ブラック 新品", "itemPrice": 44000, "itemUrl": "https://item.rakuten.co.jp/a/1/?x=1", "shopName": "A", "shopCode": "a",
                 "pointRate": 10, "postageFlag": 0, "availability": 1, "mediumImageUrls": ["https://thumbnail.image.rakuten.co.jp/x.jpg?_ex=128x128"], "itemCaption": "JAN:4548736132610"},
                {"itemName": "WH-1000XM5 中古 美品", "itemPrice": 30000, "itemUrl": "u2", "availability": 1, "itemCaption": "4548736132610"},
                {"itemName": "イヤーパッド XM5用", "itemPrice": 3000, "itemUrl": "u3", "availability": 1, "itemCaption": "4548736132610"},
                {"itemName": "SONY WH-1000XM5", "itemPrice": 45000, "itemUrl": "u4", "availability": 1, "itemCaption": "別のJAN"},
            ]}
    c = C()
    offers = rakuten.search_jan(c, "id", "key", "4548736132610", 42000)
    assert len(offers) == 2, offers  # 中古・付属品(価格)は除外、説明文にJANが無くても対象
    o = offers[0]
    assert o["u"] == "https://item.rakuten.co.jp/a/1/" and o["sh"] == 2 and o["src"] == "r" and o["pt"] == int(44000 / 1.1 * 9 / 100)
    assert c.h["Origin"].startswith("https://") and "openapi" in c.url
    # 型番が出品名に無い別物（JAN検索で混ざる）は除外
    o2 = rakuten.search_jan(c, "id", "key", "4548736132610", 42000, names=["SONY WH-1000XM5 ブラック"])
    assert [x["n"][:14] for x in o2] == ["SONY WH-1000X", "SONY WH-1000X"] or all("1000XM5" in x["n"] for x in o2)
    o3 = rakuten.search_jan(c, "id", "key", "4548736132610", 42000, names=["Pioneer DDJ-GRV6"])
    assert o3 == []


if __name__ == "__main__":
    test_rakuten()
    print("ok test_rakuten")


KAIKYO = '''<form action="/" data-ajax="true" id="G01_ProdutShow_searchForm" method="post"> <input type="hidden" id="g01Search" name="g01Search" /> <input type="hidden" id="g01tagNameLevel1" name="g01tagNameLevel1" value="家電買取" /> </form>
<div class="card-body text-center py-1 px-0"> <label class="hideText mb-0 px-2 w-100" data-toggle="tooltip" data-placement="top" title="Nintendo Switch 2 Proコントローラー ゼルダの伝説 40周年 アニバーサリーエディション" style="height:21px"> x </label> <label class="hideText mb-0 px-2 w-100" data-toggle="tooltip" data-placement="top" title="ディスプレイスタンド付き" style="height:21px"> x </label> <small class="text-muted my-1"> JAN:4902370554564 </small> <label class="hideText mb-0 px-5 w-100" data-toggle="tooltip" data-placement="top" title=""> </label> <label class="mb-0">新品</label> <label style="color:orangered" for="New_S013814" class="mb-0 text-right" id="NewPrice_S013814"> 13,000円 </label> <input type="button" id="BtnAdd_S013814" value="カートに入れる" disabled></div>
<div class="card-body text-center py-1 px-0"> <label class="hideText mb-0 px-2 w-100" title="iPhone Duo 256GB" > x </label> <label class="mb-0">新品</label> <label id="NewPrice_S1"> 368,000円 </label> <input type="button" id="BtnAdd_S1"></div>
<ul class="pagination my-pagination" data-pagecount="13" data-urlformat="/G01_ProdutShow/Index/__id__?kid=2&amp;bid=01&amp;fromPager=abc" id="bootstrappager"></ul>'''


def test_kaikyo():
    from scrapers import kaikyo
    items = kaikyo.parse_list(KAIKYO)
    assert items == [{"jan": "4902370554564", "name": "Nintendo Switch 2 Proコントローラー ゼルダの伝説 40周年 アニバーサリーエディション ディスプレイスタンド付き", "price": 13000}], items
    assert kaikyo.parse_pager(KAIKYO) == ("/G01_ProdutShow/Index/__id__?kid=2&bid=01&fromPager=abc", 13)
    assert kaikyo.form_data(KAIKYO) == {"g01Search": "", "g01tagNameLevel1": "家電買取"}


if __name__ == "__main__":
    test_kaikyo()
    print("ok test_kaikyo")


def test_amazon_parse():
    import amazon
    res = {"searchResult": {"items": [{"asin": "B0TEST", "itemInfo": {"title": {"displayValue": "ソニー WH-1000XM5 ブラック"}},
        "offersV2": {"listings": [{"price": {"money": {"amount": 41800, "currency": "JPY"}}, "condition": {"value": "New"},
                                   "merchantInfo": {"name": "Amazon.co.jp"}, "availability": {"type": "IN_STOCK"}, "isBuyBoxWinner": True},
                                  {"price": {"money": {"amount": 30000}}, "condition": {"value": "Used"}}]}}]}}
    rows = amazon.parse(res)
    assert len(rows) == 2 and rows[0]["price"] == 41800 and rows[0]["merchant"] == "Amazon.co.jp"
    class A:
        def search(self, kw, page=1):
            return res
    o = amazon.search_jan(A(), "4548736132610", 40000, names=["SONY WH-1000XM5"])
    assert [x["p"] for x in o] == [41800] and o[0]["u"].endswith("/dp/B0TEST") and o[0]["src"] == "a"


if __name__ == "__main__":
    test_amazon_parse()
    print("ok test_amazon_parse")


EARTH = '''<div class="text-center mt-2 fs-20"> <span class="bd "> <span>1,119</span> 件 </span> の商品が見つかりました。 </div>
<table class="product_list bd fs-14 mb-4"> <tbody> <tr> <th>メーカー</th> </tr>
<tr> <td>Amazon</td> <td> <span></span> <span>家電</span> </td> <td>Fire TV Stick 4K Select</td> <td class="text-nowrap text-right fs-20 fc-red"> ¥ <span>0</span> </td> <td class="text-center text-nowrap"> <a href="/products/detail/5785">詳しく<br>見る</a> </td> </tr>
<tr> <td>パナソニック</td> <td> <span>家電</span> <span> / </span> <span>FAX</span> </td> <td>KX-PD750DW-N</td> <td class="text-nowrap text-right fs-20 fc-red"> ¥ <span>33,700</span> </td> <td class="text-center text-nowrap"> <a href="/products/detail/2417">詳しく<br>見る</a> </td> </tr>'''


def test_earth():
    from scrapers import earth
    items, total = earth.parse_list(EARTH)
    assert total == 1119 and items == [{"name": "KX-PD750DW-N", "maker": "パナソニック", "cat": "家電 / FAX", "price": 33700, "url": "https://bakusokukaitori.com/products/detail/2417"}], items


def test_match_by_model():
    import run
    from unittest import mock
    by = {"4549980000001": {"jan": "4549980000001", "name": "パナソニック FAX KX-PD750DW-N", "names": {"パナソニック FAX KX-PD750DW-N"}, "buys": {"wiki": {"p": 30000}}},
          "4549980000002": {"jan": "4549980000002", "name": "パナソニック FAX KX-PD750DW-W", "names": {"パナソニック FAX KX-PD750DW-W"}, "buys": {}}}
    earth_items = [{"name": "KX-PD750DW-N", "price": 33700, "url": "u1"}, {"name": "Fire TV Stick", "price": 3000, "url": "u2"}]
    with mock.patch.object(run, "load_buyback", lambda k: (earth_items, None) if k == "earth" else ([], None)), mock.patch.object(run, "load", lambda p, d: {}):
        st = run.match_by_model(by)
    assert by["4549980000001"]["buys"]["earth"]["p"] == 33700 and "earth" not in by["4549980000002"]["buys"], by
    assert st["earth"]["matched"] == 1


if __name__ == "__main__":
    test_earth(); test_match_by_model()
    print("ok test_earth / test_match_by_model")
