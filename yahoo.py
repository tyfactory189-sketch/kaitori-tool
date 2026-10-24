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


# ---------- 商品ページで「仕様選択」による価格差を確認 ----------
# 検索APIの価格は、色・容量などの選択肢のうち一番安いものになっていることがある。
# 商品ページの埋め込みデータ（__NEXT_DATA__）から選択肢ごとの価格と必須オプション料金を読む。
RE_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _choices(item: dict):
    """(選択肢名, 価格 or None, skuId) を列挙。価格 None は基本価格と同じ。"""
    t1, t2 = item.get("stockTableOneAxis"), item.get("stockTableTwoAxis")
    if t1:
        for c in (t1.get("firstOption") or {}).get("choiceList") or []:
            yield c.get("choiceName", ""), c.get("price"), str(c.get("skuId") or "")
    if t2:
        for f in (t2.get("firstOption") or {}).get("choiceList") or []:
            for c in ((f.get("secondOption") or {}).get("choiceList") or []):
                yield f"{f.get('choiceName', '')} {c.get('choiceName', '')}", c.get("price"), str(c.get("skuId") or "")


def parse_item_page(html: str, jan: str):
    """商品ページから、そのJANを買うときの価格情報を返す。読めなければ None。

    戻り値: {"base": 基本価格, "jp": JANに一致した選択肢の価格 or None,
             "min": 選択肢の最安, "max": 選択肢の最高, "add": 必須オプションの最低料金}
    """
    import json
    m = RE_NEXT.search(html)
    if not m:
        return None
    try:
        item = json.loads(m.group(1))["props"]["pageProps"]["item"]
    except (KeyError, ValueError, TypeError):
        return None
    base = int(item.get("applicablePrice") or 0)
    if base <= 0:
        return None
    prices, jp = [], None
    for _name, price, sku in _choices(item):
        p = int(price) if price else base
        prices.append(p)
        if sku and (sku == jan or sku.endswith(jan)):
            jp = p
    # 全ての選択肢に料金がかかるオプション（保証・付属品の有無など）は必ず上乗せされる
    add = 0
    for opt in item.get("selectOptionList") or []:
        charges = [c.get("charge") or 0 for c in opt.get("choiceList") or [] if c.get("isSelectable", True)]
        if charges and min(charges) > 0:
            add += min(charges)
    return {"base": base, "jp": jp, "min": min(prices) if prices else base,
            "max": max(prices) if prices else base, "add": add}


def check_offer(client: Client, offer: dict, jan: str):
    """出品の価格を商品ページの情報で補正する（変更があれば offer を書き換えて True）。

    - 選択肢の中にJANが一致するものがあれば、その価格を使う
    - 一致がなく選択肢で価格が違う場合は、高い方の価格で計算し、範囲を "pv" に残す
    - 必須オプション料金は加算して "add" に残す
    """
    url = offer.get("u", "")
    if "store.shopping.yahoo.co.jp" not in url:
        return False  # LOHACO 等はページ構造が違うので対象外
    info = parse_item_page(client.get(url), jan)
    offer["chk"] = 1
    if not info:
        return False
    old = offer["p"]
    if info["jp"] is not None:
        price = info["jp"]
    elif info["max"] != info["min"]:
        price = info["max"]
        offer["pv"] = [info["min"], info["max"]]
    else:
        price = old
    price += info["add"]
    if info["add"]:
        offer["add"] = info["add"]
    if price == old:
        return False
    ratio = price / old if old else 1
    offer["p"] = price
    offer["pp"] = round(offer["pp"] * ratio) if offer.get("pp") else price
    offer["pt"] = round(offer.get("pt", 0) * ratio)
    offer["ptp"] = round(offer.get("ptp", 0) * ratio)
    return True
