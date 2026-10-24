"""Yahoo!ショッピング 商品検索API(v3) で JAN ごとの新品・在庫ありの安い出品を取る。

利用制限は 1クエリ/秒 なので、Client の delay を 1.1 秒にしている。
"""
import re

from scrapers.http import Client

API = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"

# 同じJANで出品されている部品・付属品・中古などを除外する
EXCLUDE = re.compile(
    r"パーツ|部品|ドラグノブ|替刃|替え刃|交換用|保護フィルム|互換|替えブラシ|替ブラシ|"
    r"中古|訳あり|わけあり|アウトレット|展示品|開封品|ジャンク|レンタル|外箱傷|箱傷|箱つぶれ|"
    r"再生品|整備品|リファービッシュ|海外版|並行輸入|"
    r"左耳|右耳|片耳|バラ売り|ケースのみ|充電ケース単品|箱のみ|空箱|付属品のみ"
)


def _offer(hit: dict) -> dict:
    pt = hit.get("point") or {}
    seller = hit.get("seller") or {}
    img = (hit.get("image") or {}).get("small") or ""
    return {
        "n": (hit.get("name") or "")[:90],
        "p": int(hit.get("price") or 0),
        "pp": int(hit.get("premiumPrice") or 0),
        "pt": int(pt.get("lyLimitedBonusAmount") or 0),
        "ptp": int(pt.get("lyLimitedPremiumBonusAmount") or 0),
        "sh": int((hit.get("shipping") or {}).get("code") or 0),  # 2=送料無料 3=条件付き
        "s": seller.get("name") or "",
        "sid": seller.get("sellerId") or "",
        "bs": bool(seller.get("isBestSeller")),
        "u": hit.get("url") or "",
        "img": img,
    }


def search_jan(client: Client, appid: str, jan: str, buy_price: int, keep: int = 5):
    data = client.get(API, params={
        "appid": appid,
        "jan_code": jan,
        "condition": "new",
        "in_stock": "true",
        "sort": "+price",
        "results": 30,
    }, as_json=True)
    offers = []
    for hit in data.get("hits", []):
        code = (hit.get("janCode") or "").strip()
        if code and code != jan:
            continue
        name = hit.get("name") or ""
        if EXCLUDE.search(name):
            continue
        o = _offer(hit)
        # 買取価格の半分未満は付属品・別物の可能性が高い
        if o["p"] <= 0 or o["p"] < buy_price * 0.5:
            continue
        offers.append(o)
    offers.sort(key=lambda o: o["p"] - o["pt"])
    return offers[:keep]
