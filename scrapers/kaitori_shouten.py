"""買取商店（kaitorishouten-co.jp）の新品買取価格を取得する。

トップページから /category/<大分類>/<小分類> のリンクを集める
（1=iPhone, 2=家電。3=お酒は対象外）。
カテゴリページの JSON-LD (ItemList) から商品URLを集め、
商品ページの JSON-LD (Product) から gtin13 と offers.price（新品価格）を読む。
"""
import json
import re

from .http import Client

BASE = "https://www.kaitorishouten-co.jp"
SOURCE = "shouten"
TOP_CATEGORIES = ("1", "2")

RE_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _ld_blocks(html: str):
    out = []
    for raw in RE_LD.findall(html):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def list_categories(html: str):
    cats = []
    for top, sub in re.findall(r'href="(?:https?://www\.kaitorishouten-co\.jp)?/category/(\d+)/(\d+)"', html):
        key = f"/category/{top}/{sub}"
        if top in TOP_CATEGORIES and key not in cats:
            cats.append(key)
    return cats


def parse_category(html: str):
    urls = []
    for ld in _ld_blocks(html):
        if ld.get("@type") == "ItemList":
            for el in ld.get("itemListElement", []):
                u = el.get("url")
                if u:
                    urls.append(u if u.startswith("http") else BASE + u)
    next_pages = sorted(set(re.findall(r'href="([^"]*[?&]page=\d+[^"]*)"', html)))
    return urls, next_pages


def parse_product(html: str, url: str = ""):
    for ld in _ld_blocks(html):
        if ld.get("@type") == "Product":
            jan = str(ld.get("gtin13") or ld.get("sku") or "").strip()
            offers = ld.get("offers") or {}
            price = offers.get("price")
            if not (re.fullmatch(r"\d{8,14}", jan) and price):
                return None
            return {
                "source": SOURCE,
                "jan": jan,
                "name": ld.get("name", ""),
                "price": int(float(price)),
                "category": ld.get("category", ""),
                "url": ld.get("url") or url,
                "note": "",
            }
    return None


def scrape(client: Client | None = None, log=print):
    client = client or Client(delay=0.8)
    cats = list_categories(client.get(BASE + "/"))
    product_urls: list[str] = []
    seen_pages = set()
    for cat in cats:
        queue = [BASE + cat]
        while queue:
            page = queue.pop(0)
            if page in seen_pages:
                continue
            seen_pages.add(page)
            urls, nexts = parse_category(client.get(page))
            product_urls += [u for u in urls if u not in product_urls]
            for n in nexts:
                full = n if n.startswith("http") else BASE + n
                if full not in seen_pages:
                    queue.append(full)
    log(f"[shouten] カテゴリ{len(cats)}件 → 商品{len(product_urls)}件")
    out = []
    for i, u in enumerate(product_urls, 1):
        try:
            item = parse_product(client.get(u), u)
        except RuntimeError as e:
            log(f"[shouten] skip {u}: {e}")
            continue
        if item:
            out.append(item)
        if i % 200 == 0:
            log(f"[shouten] {i}/{len(product_urls)}")
    return out
