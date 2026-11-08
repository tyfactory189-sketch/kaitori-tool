"""Amazon（Creators API）で JAN ごとの新品の出品価格を取る。

- Amazon アソシエイトの「Creators API」の認証情報（Credential ID / Secret / Version）と
  トラッキングID（partnerTag, 例: xxxx-22）が必要。
- 認証は OAuth の client_credentials。日本は Version 3.3（api.amazon.co.jp）か 2.3（Cognito）。
  トークンは1時間ほど使い回す。
- searchItems に JAN を keywords で渡して検索し、offersV2 の価格・状態・出品者を読む。
- 楽天と同じく、型番が出品名に入っていない別物は除外する。
"""
import os
import re
import time
import unicodedata

from scrapers.http import Client
from yahoo import EXCLUDE, SKIP_ITEM, _model_tokens

API = "https://creatorsapi.amazon/catalog/v1/searchItems"
MARKETPLACE = "www.amazon.co.jp"
TOKEN_URLS = {
    "3.1": "https://api.amazon.com/auth/o2/token",
    "3.2": "https://api.amazon.co.uk/auth/o2/token",
    "3.3": "https://api.amazon.co.jp/auth/o2/token",
    "2.1": "https://creatorsapi.auth.us-east-1.amazoncognito.com/oauth2/token",
    "2.2": "https://creatorsapi.auth.eu-south-2.amazoncognito.com/oauth2/token",
    "2.3": "https://creatorsapi.auth.us-west-2.amazoncognito.com/oauth2/token",
}
RE_USED = re.compile(r"中古|ユーズド|USED|訳あり|アウトレット|整備済|再生品|ジャンク|レンタル", re.I)
RESOURCES = [
    "itemInfo.title",
    "images.primary.medium",
    "offersV2.listings.price",
    "offersV2.listings.condition",
    "offersV2.listings.merchantInfo",
    "offersV2.listings.availability",
    "offersV2.listings.isBuyBoxWinner",
]


class Creators:
    def __init__(self, cred_id: str, secret: str, version: str, partner_tag: str):
        self.cred_id, self.secret, self.version, self.tag = cred_id, secret, (version or "3.3").strip(), partner_tag
        self.client = Client(delay=float(os.environ.get("AMAZON_DELAY", "1.2")), retries=2, backoff=10)
        self._token, self._exp = None, 0.0

    def token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        v3 = self.version.startswith("3")
        body = {"grant_type": "client_credentials", "client_id": self.cred_id, "client_secret": self.secret,
                "scope": "creatorsapi::default" if v3 else "creatorsapi/default"}
        url = TOKEN_URLS.get(self.version) or TOKEN_URLS["3.3"]
        s = self.client.session
        r = s.post(url, json=body, timeout=30) if v3 else s.post(url, data=body, timeout=30)
        if r.status_code >= 400 and v3:  # 形式違いで失敗することがあるので、もう一方も試す
            r = s.post(url, data=body, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"Amazonのトークン取得に失敗（HTTP {r.status_code} {r.text[:200]}）")
        j = r.json()
        self._token, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 3600))
        return self._token

    def search(self, keywords: str, page: int = 1):
        body = {"partnerTag": self.tag, "marketplace": MARKETPLACE, "keywords": keywords,
                "itemCount": 10, "itemPage": page, "resources": RESOURCES}
        for attempt in range(4):
            self.client._wait()
            auth = "Bearer " + self.token() + ("" if self.version.startswith("3") else f", Version {self.version}")
            r = self.client.session.post(API, json=body, timeout=30, headers={
                "Authorization": auth, "x-marketplace": MARKETPLACE, "Content-Type": "application/json"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                self._token = None
            elif r.status_code == 403:
                raise RuntimeError(f"Amazon 403（{r.text[:200]}）")  # AssociateNotEligible など
            elif r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Amazon HTTP {r.status_code} {r.text[:200]}")
            time.sleep(min(30, 3 * 2 ** attempt))
        raise RuntimeError(f"Amazon searchItems 失敗（HTTP {r.status_code}）")


def _g(d, *path):
    for p in path:
        if isinstance(d, list):
            d = d[0] if d else None
        if not isinstance(d, dict):
            return None
        d = d.get(p) or d.get(p[:1].upper() + p[1:])
    return d


def parse(result: dict):
    """searchItems の応答から出品を取り出す（キー名の大文字・小文字の違いに対応）。"""
    sr = result.get("searchResult") or result.get("SearchResult") or {}
    out = []
    for it in sr.get("items") or sr.get("Items") or []:
        title = _g(it, "itemInfo", "title", "displayValue") or ""
        asin = it.get("asin") or it.get("ASIN") or ""
        img = _g(it, "images", "primary", "medium", "url") or ""
        for lst in (_g(it, "offersV2") or {}).get("listings") or (_g(it, "offersV2") or {}).get("Listings") or []:
            amount = _g(lst, "price", "money", "amount")
            if amount is None:
                continue
            cond = (_g(lst, "condition", "value") or "New")
            merchant = _g(lst, "merchantInfo", "name") or ""
            out.append({"asin": asin, "title": title, "price": int(float(amount)), "cond": str(cond),
                        "merchant": merchant, "img": img,
                        "avail": str(_g(lst, "availability", "type") or ""), "buybox": bool(_g(lst, "isBuyBoxWinner"))})
    return out


def search_jan(api: Creators, jan: str, buy_price: int, keep: int = 5, names=()):
    rows = parse(api.search(jan.zfill(13) if len(jan) == 12 else jan))
    toks = _model_tokens(names)
    norm = lambda t: re.sub(r"[\s\-_/]", "", unicodedata.normalize("NFKC", t)).upper()  # noqa: E731
    offers = []
    for r in rows:
        name = r["title"]
        if r["cond"].lower() not in ("new", "新品"):
            continue
        if EXCLUDE.search(name) or SKIP_ITEM.search(name) or RE_USED.search(name):
            continue
        if toks and not any(t in norm(name) for t in toks):
            continue
        if r["price"] <= 0 or r["price"] < buy_price * 0.5:
            continue
        if r["avail"] and r["avail"].lower() in ("outofstock", "unavailable"):
            continue
        offers.append({"src": "a", "n": name[:200], "p": r["price"], "pt": 0, "sh": 2,
                       "s": r["merchant"] or "Amazon", "sid": r["asin"],
                       "u": f"https://www.amazon.co.jp/dp/{r['asin']}", "img": r["img"], "bb": r["buybox"]})
    offers.sort(key=lambda o: o["p"])
    # 同じASINは最安の1件に
    seen, uniq = set(), []
    for o in offers:
        if o["sid"] in seen:
            continue
        seen.add(o["sid"])
        uniq.append(o)
    return uniq[:keep]
