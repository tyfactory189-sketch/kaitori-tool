"""買取wiki（kadenkaitori.tokyo）の家電カテゴリ買取価格を取得する。

一覧: /category/<slug>/ と /category/<slug>/<page>
各商品: .pro_list 内に 「JAN：xxxxx」「買取価格: 12,345円」
"""
import re
from urllib.parse import quote
from bs4 import BeautifulSoup

from .http import Client

BASE = "https://kadenkaitori.tokyo"
SOURCE = "wiki"

RE_JAN = re.compile(r"JAN[：:]\s*(\d{8,14})")
RE_PRICE = re.compile(r"買取価格[：:]\s*([\d,]+)\s*円")
RE_COUNT = re.compile(r"([\d,]+)\s*件該当")


def parse_list(html: str, cat: str = ""):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for box in soup.select(".pro_list"):
        text = box.get_text(" ", strip=True)
        jan = RE_JAN.search(text)
        price = RE_PRICE.search(text)
        if not (jan and price):
            continue
        name_el = box.select_one(".sub-pro-name")
        name = name_el.get_text(" ", strip=True) if name_el else ""
        name = re.sub(r"\s*\d{13}\s*$", "", name)
        link = box.select_one("a[href]")
        href = link["href"] if link else "/"
        items.append({
            "source": SOURCE,
            "jan": jan.group(1),
            "name": name,
            "price": int(price.group(1).replace(",", "")),
            "category": cat,
            "url": href if href.startswith("http") else BASE + href,
            "note": "購入証明必要" if "購入証明" in text else "",
        })
    count_m = RE_COUNT.search(soup.get_text(" ", strip=True))
    count = int(count_m.group(1).replace(",", "")) if count_m else 0
    per_page = len(soup.select(".pro_list"))
    return items, count, per_page


def list_categories(client: Client):
    html = client.get(BASE + "/category/")
    slugs = []
    for href in re.findall(r'href="(?:https?://kadenkaitori\.tokyo)?/category/([^/"]+)/?"', html):
        if href not in slugs:
            slugs.append(href)
    return slugs


def scrape(client: Client | None = None, log=print):
    """全カテゴリ（スマホ・ゲーム機・カメラ等を含む）を /search/<page> でたどる。"""
    client = client or Client(delay=1.0)
    items, count, per = parse_list(client.get(f"{BASE}/search/1"))
    out = list(items)
    pages = -(-count // per) if per else 1
    for p in range(2, pages + 1):
        more, _, _ = parse_list(client.get(f"{BASE}/search/{p}"))
        out += more
        if p % 50 == 0:
            log(f"[wiki] {p}/{pages}ページ")
    log(f"[wiki] {count}件 / {pages}ページ")
    return out
