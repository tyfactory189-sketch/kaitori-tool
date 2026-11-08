"""海峡通信（モバイル一番 mobile-ichiban.com）の新品買取価格を取得する。

- 大分類 /Prod/1（スマホ）と /Prod/2（家電）の一覧を読む（3=トレカ、4=中古品は対象外）。
- 1ページ20件。2ページ目以降は一覧に埋め込まれたページ送りのURL
  （/G01_ProdutShow/Index/<n>?kid=..&fromPager=..）へ、検索フォームの値を
  POST（Ajax）すると返ってくる。
- 商品カードの「JAN:xxxxxxxx」と「新品」の価格（NewPrice_*）を使う。
  JANの無い商品（iPhone本体など）は照合できないので飛ばす。
- 「来店+200」などの備考は店頭の上乗せなので無視（郵送買取の価格を使う）。
"""
import html as _html
import re

from .http import Client

BASE = "https://www.mobile-ichiban.com"
SOURCE = "kaikyo"
TOP_CATEGORIES = ("1", "2")

RE_CARD = re.compile(r'<div class="card-body text-center[^"]*">(.*?)id="BtnAdd_', re.S)
RE_LABEL = re.compile(r'<label class="hideText[^"]*"[^>]*title="([^"]*)"', re.S)
RE_JAN = re.compile(r"JAN:\s*(\d{8,14})")
RE_NEW = re.compile(r'id="NewPrice_[^"]*">\s*([\d,]+)\s*円')
RE_PAGER = re.compile(r'id="bootstrappager"|data-urlformat="([^"]+)"')
RE_URLFMT = re.compile(r'data-urlformat="([^"]+)"')
RE_PAGECOUNT = re.compile(r'data-pagecount="(\d+)"')
RE_FORM = re.compile(r'<form[^>]*id="G01_ProdutShow_searchForm"[^>]*>(.*?)</form>', re.S)
RE_INPUT = re.compile(r'<input[^>]*type="hidden"[^>]*>')


def parse_list(html: str):
    """一覧HTML（またはAjaxで返る部分HTML）から商品を読む。"""
    items = []
    for body in RE_CARD.findall(html):
        jan = RE_JAN.search(body)
        price = RE_NEW.search(body)
        if not jan or not price:
            continue
        titles = [_html.unescape(t).strip() for t in RE_LABEL.findall(body)]
        name = " ".join(t for t in titles[:2] if t)
        items.append({"jan": jan.group(1), "name": name, "price": int(price.group(1).replace(",", ""))})
    return items


def parse_pager(html: str):
    fmt = RE_URLFMT.search(html)
    cnt = RE_PAGECOUNT.search(html)
    return (_html.unescape(fmt.group(1)) if fmt else None, int(cnt.group(1)) if cnt else 1)


def form_data(html: str):
    m = RE_FORM.search(html)
    data = {}
    if not m:
        return data
    for tag in RE_INPUT.findall(m.group(1)):
        name = re.search(r'name="([^"]+)"', tag)
        if not name:
            continue
        val = re.search(r'value="([^"]*)"', tag)
        data[name.group(1)] = _html.unescape(val.group(1)) if val else ""
    return data


def scrape(client: Client | None = None, log=print):
    client = client or Client(delay=1.0)
    out, seen = [], set()
    for cat in TOP_CATEGORIES:
        first = client.get(f"{BASE}/Prod/{cat}")
        fmt, pages = parse_pager(first)
        data = form_data(first)
        found = parse_list(first)
        for n in range(2, pages + 1):
            if not fmt:
                break
            try:
                part = client.post(BASE + fmt.replace("__id__", str(n)), data=data,
                                   headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/Prod/{cat}"})
            except RuntimeError as e:
                log(f"[kaikyo] {cat} p{n} 失敗: {e}")
                continue
            found += parse_list(part)
        log(f"[kaikyo] 分類{cat}: {pages}ページ → JANつき {len(found)}件")
        for it in found:
            if it["jan"] in seen:
                continue
            seen.add(it["jan"])
            it["url"] = f"{BASE}/Prod/{cat}"
            out.append(it)
    return out
