"""楽天市場 商品検索API で JAN ごとの新品・在庫ありの安い出品を取る。

- 新しい公開API（openapi.rakuten.co.jp）は applicationId と accessKey が必要で、
  アプリに登録した「許可するWebサイト」を Origin ヘッダーで送る必要がある。
- 利用制限は 1リクエスト/秒。
- JAN を keyword に入れて検索する（楽天側の商品情報のJANで見つかる）。
  別物が混ざることがあるので、除外語・価格・在庫で絞り、画面側で型番の一致も確認する。
"""
import os
import re

from scrapers.http import Client
from yahoo import EXCLUDE, SKIP_ITEM, _model_tokens
import unicodedata

API_NEW = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
API_OLD = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20260701"
ORIGIN = os.environ.get("RAKUTEN_ORIGIN", "https://tyfactory189-sketch.github.io")
RE_USED = re.compile(r"ほぼ新品|新品同様|\d大特典|特典付|_set\b|セット品|中古|ユーズド|USED|訳あり|アウトレット|展示品|ジャンク|レンタル|整備済|再生品|未使用|箱難|箱つぶれ|箱潰れ|保証期間\d+\s*[ヶケか]月", re.I)


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


def name_ok(offer_name: str, names) -> bool:
    """買取側の型番が出品名に入っているか（型番が無い商品は判定しない）。古いキャッシュにも使う。"""
    toks = _model_tokens(names)
    if not toks:
        return True
    n = re.sub(r"[\s\-_/]", "", unicodedata.normalize("NFKC", offer_name or "")).upper()
    return any(t in n for t in toks) and not RE_USED.search(offer_name or "")


def search_jan(client: Client, app_id: str, access_key: str, jan: str, buy_price: int, keep: int = 5, names=()):
    params = {
        "applicationId": app_id,
        "keyword": jan.zfill(13) if len(jan) == 12 else jan,
        "hits": 30,
        "sort": "+itemPrice",
        "minPrice": max(1, int(buy_price * 0.5)),  # 安い付属品（ケース等）で30件が埋まらないように
        "NGKeyword": "中古 中古品 ジャンク 訳あり レンタル 整備済",  # 中古で安い順の上位が埋まらないように
        "availability": 1,
        "format": "json",
        "formatVersion": 2,
    }
    items = []
    for page in (1, 2, 3):  # 安い順に最大90件まで見る（条件に合う出品が keep 件そろえば終わり）
        params["page"] = page
        if access_key:
            params["accessKey"] = access_key
            data = client.get(API_NEW, params=params, as_json=True, headers={"Origin": ORIGIN, "Referer": ORIGIN + "/"})
        else:
            data = client.get(API_OLD, params=params, as_json=True)
        got = data.get("Items") or data.get("items") or []
        items += got
        ok = [x for x in items if not (EXCLUDE.search(x.get("itemName") or "") or RE_USED.search(x.get("itemName") or ""))]
        if len(ok) >= keep or len(got) < 30 or page >= int(data.get("pageCount") or 1):
            break
    # 買取側の商品名にある型番が、出品名にも入っているものだけにする（楽天はJAN検索で別物が混ざるため）
    toks = _model_tokens(names)
    norm = lambda t: re.sub(r"[\s\-_/]", "", unicodedata.normalize("NFKC", t)).upper()  # noqa: E731
    offers = []
    for it in items:
        it = it.get("Item", it) if isinstance(it, dict) else {}
        if int(it.get("availability") or 0) != 1:
            continue
        name = it.get("itemName") or ""
        if EXCLUDE.search(name) or SKIP_ITEM.search(name) or RE_USED.search(name):
            continue
        if toks and not any(t in norm(name) for t in toks):
            continue
        o = _offer(it)
        lo, hi = int(it.get("itemPriceMin1") or 0), int(it.get("itemPriceMax1") or 0)
        if lo and hi and hi > lo:  # 色・容量などで価格が違う出品：どれがこのJANか分からないので高い方で計算
            o["pv"] = [lo, hi]
            if hi > o["p"]:
                o["pt"] = int(o["pt"] * hi / o["p"]) if o["p"] else 0
                o["p"] = hi
        if o["p"] <= 0 or o["p"] < buy_price * 0.5:
            continue
        offers.append(o)
    offers.sort(key=lambda o: o["p"] - o["pt"])
    return offers[:keep]
