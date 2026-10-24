"""森森買取（morimori-kaitori.jp）の新品買取価格を取得する。

トップページの /category/<2桁> を大分類として、?page=N で全件たどる（50件/ページ）。
各商品: .mm1551-prow
  名前  .mm1551-prow__name
  JAN   .mm1551-prow__meta 内「JAN:xxxx」/ 状態「新品」「中古」
  価格  .mm1551-prow__cur-val（現在価格）
"""
import re
from bs4 import BeautifulSoup

from .http import Client

BASE = "https://www.morimori-kaitori.jp"
SOURCE = "morimori"
# トレカ(12)など JAN でYahoo照合しにくい大分類を除外したい場合はここに追加
EXCLUDE_TOP: set[str] = set()

RE_JAN = re.compile(r"JAN[：:]\s*(\d{8,14})")
RE_COUNT = re.compile(r"該当\s*([\d,]+)\s*件")
RE_YEN = re.compile(r"([\d,]+)\s*円")


def list_top_categories(html: str):
    tops = []
    for c in re.findall(r'href="(?:https?://www\.morimori-kaitori\.jp)?/category/(\d{2})"', html):
        if c not in tops and c not in EXCLUDE_TOP:
            tops.append(c)
    return tops


def parse_list(html: str, cat: str = ""):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for row in soup.select(".mm1551-prow"):
        meta = row.select_one(".mm1551-prow__meta")
        meta_text = meta.get_text(" ", strip=True) if meta else ""
        jan = RE_JAN.search(meta_text)
        # 状態の表記が無い商品は新品扱い。中古だけ除外する
        if not jan or "中古" in meta_text:
            continue
        # 「現在価格」欄（価格が「ASK」の商品は数字が無いので飛ばす）
        price_el = row.select_one(".mm1551-prow__cur")
        m = RE_YEN.search(price_el.get_text(" ", strip=True)) if price_el else None
        if not m:
            continue
        name_el = row.select_one(".mm1551-prow__name")
        link = row.select_one(".mm1551-prow__name a[href]") or row.select_one("a[href*='/product/']")
        href = link["href"] if link else f"/category/{cat}"
        items.append({
            "source": SOURCE,
            "jan": jan.group(1),
            "name": name_el.get_text(" ", strip=True) if name_el else "",
            "price": int(m.group(1).replace(",", "")),
            "category": cat,
            "url": href if href.startswith("http") else BASE + href,
            "note": "",
        })
    cm = RE_COUNT.search(soup.get_text(" ", strip=True))
    count = int(cm.group(1).replace(",", "")) if cm else 0
    return items, count, len(soup.select(".mm1551-prow"))


def scrape(client: Client | None = None, log=print):
    client = client or Client(delay=1.0)
    out = []
    for top in list_top_categories(client.get(BASE + "/")):
        url = f"{BASE}/category/{top}"
        items, count, per = parse_list(client.get(url), top)
        out += items
        pages = -(-count // per) if per else 1
        for p in range(2, pages + 1):
            more, _, _ = parse_list(client.get(url, params={"page": p}), top)
            out += more
        log(f"[morimori] {top}: {count}件 / {pages}ページ")
    return out
