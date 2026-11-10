"""爆速買取のアース（bakusokukaitori.com）の買取価格を取得する。

- EC-CUBE の一覧 /products/list?pageno=N（1ページ20件、全カテゴリ）を順に読む。
- 表の列：メーカー / カテゴリ / 商品名・型番 / 金額 / 詳細リンク。
- JAN が載っていないので、ここでは型番（商品名）だけ保存し、
  run.py が他の買取サイトやYahoo出品名の型番と突き合わせてJANを決める。
- 金額0円（買取停止）の商品は飛ばす。
"""
import html as _html
import re

from .http import Client

BASE = "https://bakusokukaitori.com"
SOURCE = "earth"
NEEDS_JAN_MATCH = True  # JANが無いので型番で照合する

RE_ROW = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td[^>]*>\s*¥\s*<span>([\d,]+)</span>\s*</td>\s*<td[^>]*>\s*<a href=\"(/products/detail/\d+)\"", re.S)
RE_TOTAL = re.compile(r"<span>([\d,]+)</span>\s*件\s*</span>\s*の商品が見つかりました")


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_list(html: str):
    items = []
    for maker, cat, name, price, href in RE_ROW.findall(html):
        p = int(price.replace(",", ""))
        if p <= 0:
            continue
        items.append({"name": _txt(name), "maker": _txt(maker), "cat": _txt(cat), "price": p, "url": BASE + href})
    total = RE_TOTAL.search(html)
    return items, int(total.group(1).replace(",", "")) if total else None


def scrape(client: Client | None = None, log=print):
    client = client or Client(delay=1.0)
    out, page, total = [], 1, None
    while True:
        html = client.get(f"{BASE}/products/list?pageno={page}")
        items, t = parse_list(html)
        total = total or t
        if "/products/detail/" not in html:
            break
        out += items
        if total and page * 20 >= total:
            break
        page += 1
        if page > 1000:
            break
    log(f"[earth] {page}ページ → 価格あり {len(out)}件（全{total}件）")
    return out
