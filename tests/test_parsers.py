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
