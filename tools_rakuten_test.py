"""楽天APIの接続確認（パラメータを変えて件数を比べ、data/rakuten_test.json に書く）。"""
import json, os, time
from pathlib import Path
import rakuten as R
from scrapers.http import Client

ID, KEY = os.environ.get("RAKUTEN_APP_ID", ""), os.environ.get("RAKUTEN_ACCESS_KEY", "")
c = Client(delay=1.3, retries=1, backoff=3)
H = {"Origin": R.ORIGIN, "Referer": R.ORIGIN + "/"}
jan = "4549995635232"
base = {"applicationId": ID, "accessKey": KEY, "keyword": jan, "hits": 30, "format": "json", "formatVersion": 2}
variants = {
    "base": {},
    "sort": {"sort": "+itemPrice"},
    "avail": {"availability": 1},
    "minPrice": {"minPrice": 15000},
    "elements": {"elements": "itemName,itemPrice,itemUrl,shopName,availability"},
    "all": {"sort": "+itemPrice", "availability": 1, "minPrice": 15000},
}
out = {"at": time.strftime("%Y-%m-%d %H:%M"), "tests": {}}
for k, v in variants.items():
    try:
        d = c.get(R.API_NEW, params={**base, **v}, as_json=True, headers=H)
        its = d.get("Items") or []
        out["tests"][k] = {"count": d.get("count"), "n": len(its), "first": [((i.get("itemName") or "")[:50], i.get("itemPrice"), i.get("availability")) for i in its[:3]]}
    except Exception as e:  # noqa: BLE001
        out["tests"][k] = {"error": str(e)[:300]}
try:
    from yahoo import EXCLUDE, SKIP_ITEM
    d = c.get(R.API_NEW, params={**base, "sort": "+itemPrice", "availability": 1, "minPrice": 15000}, as_json=True, headers=H)
    why = []
    for it in (d.get("Items") or [])[:30]:
        n = it.get("itemName") or ""
        m = EXCLUDE.search(n) or SKIP_ITEM.search(n) or R.RE_USED.search(n)
        why.append([n[:70], it.get("itemPrice"), it.get("availability"), m.group(0) if m else "", type(it.get("availability")).__name__])
    out["why"] = why
except Exception as e:  # noqa: BLE001
    out["why"] = str(e)[:300]
try:
    offers = R.search_jan(c, ID, KEY, jan, 30000, keep=3)
    out["search_jan"] = [{k: o[k] for k in ("n", "p", "pt", "ptr", "sh", "s")} for o in offers]
except Exception as e:  # noqa: BLE001
    out["search_jan"] = str(e)[:300]
Path("data/rakuten_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
