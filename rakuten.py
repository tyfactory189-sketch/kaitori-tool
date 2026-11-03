"""楽天市場 商品検索API で JAN ごとの新品・在庫ありの安い出品を取る。

- 新しい公開API（openapi.rakuten.co.jp）は applicationId と accessKey が必要で、
  アプリに登録した「許可するWebサイト」を Origin ヘッダーで送る必要がある。
- 利用制限は 1リクエスト/秒。
- JAN を keyword に入れて検索する（楽天はJANの専用項目がないため、商品名・説明文に
  JANが書かれている出品が見つかる）。別物が混ざりやすいので、除外語・価格・在庫で絞る。
"""
import os
import re

from scrapers.http import Client
from yahoo import EXCLUDE, SKIP_ITEM

API_NEW = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
API_OLD = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20260701"
ORIGIN = os.environ.get("RAKUTEN_ORIGIN", "https://tyfactory189-sketch.github.io")
RE_USED = re.compile(r"中古|ユーズド|USED|訳あり|アウトレット|展示品|ジャンク|レンタル|整備済|再生品", re.I)


def _clean_url(u: str) -> str:
    # アフィリエイト経由のURLやクエリは外して、商品ページのURLにそろえる
    return (u or "").split("?")[0]


def _offer(it: dict) -> dict:
    price = int(it.get("itemPrice") or 0)
    rate = int(it.get("pointRate") or 1)  # ショップのポイント倍率（1=通常1%）
    imgs = it.get("mediumImageUrls") or []
    img = imgs[0] if imgs and isinstance(imgs[0], str) else ((imgs[0] or {}).get("imageUrl") if imgs else "")
    return {
        "src": "r",
        "n": (it.get("itemName") or "")[:200],
        "p": price,
        "pt": int(price / 1.1 * max(rate - 1, 0) / 100),  # 通常1%を超えるショップ独自の上乗せ分（税抜に付与）
        "ptr": rate,
        "sh": 2 if int(it.get("postageFlag") or 0) == 0 else 1,  # 0=送料込み
        "s": it.get("shopName") or "",
        "sid": it.get("shopCode") or "",
        "u": _clean_url(it.get("itemUrl") or ""),
        "img": (img or "").split("?")[0],
    }


def search_jan(client: Client, app_id: str, access_key: str, jan: str, buy_price: int, keep: int = 5):
    params = {
        "applicationId": app_id,
        "keyword": jan.zfill(13) if len(jan) == 12 else jan,
        "hits": 30,
        "sort": "+itemPrice",
        "availability": 1,
        "format": "json",
        "formatVersion": 2,
        "elements": "itemName,itemPrice,itemUrl,shopName,shopCode,pointRate,postageFlag,availability,mediumImageUrls,itemCaption",
    }
    if access_key:
        params["accessKey"] = access_key
        data = client.get(API_NEW, params=params, as_json=True, headers={"Origin": ORIGIN, "Referer": ORIGIN + "/"})
    else:
        data = client.get(API_OLD, params=params, as_json=True)
    offers = []
    for it in data.get("Items") or data.get("items") or []:
        it = it.get("Item", it) if isinstance(it, dict) else {}
        if int(it.get("availability") or 0) != 1:
            continue
        name = it.get("itemName") or ""
        text = name + " " + (it.get("itemCaption") or "")
        if jan not in text and jan.zfill(13) not in text:
            continue  # JANが本文に書かれていない（キーワードの部分一致など）
        if EXCLUDE.search(name) or SKIP_ITEM.search(name) or RE_USED.search(name):
            continue
        o = _offer(it)
        if o["p"] <= 0 or o["p"] < buy_price * 0.5:
            continue
        offers.append(o)
    offers.sort(key=lambda o: o["p"] - o["pt"])
    return offers[:keep]
