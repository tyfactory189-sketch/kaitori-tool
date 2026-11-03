"""楽天APIの接続確認（数件だけ検索して data/rakuten_test.json に結果を書く）。"""
import json, os, time
from pathlib import Path
import rakuten
from scrapers.http import Client

out = {"at": time.strftime("%Y-%m-%d %H:%M"), "has_id": bool(os.environ.get("RAKUTEN_APP_ID")), "has_key": bool(os.environ.get("RAKUTEN_ACCESS_KEY")), "results": []}
c = Client(delay=1.2, retries=1, backoff=3)
import rakuten as R
raw_c = Client(delay=1.2, retries=1, backoff=3)
for jan in ["4548736132610", "4549995635232"]:
    try:
        d = raw_c.get(R.API_NEW, params={"applicationId": os.environ.get("RAKUTEN_APP_ID", ""), "accessKey": os.environ.get("RAKUTEN_ACCESS_KEY", ""), "keyword": jan, "hits": 10, "format": "json", "formatVersion": 2},
                      as_json=True, headers={"Origin": R.ORIGIN, "Referer": R.ORIGIN + "/"})
        its = d.get("Items") or d.get("items") or []
        out.setdefault("raw", []).append({"jan": jan, "keys": list(d.keys())[:10], "count": d.get("count"), "n": len(its),
            "first": [{"name": (i.get("itemName") or "")[:80], "price": i.get("itemPrice"), "avail": i.get("availability"), "jan_in_caption": jan in (i.get("itemCaption") or ""), "keys": list(i.keys())[:40]} for i in its[:4]]})
    except Exception as e:  # noqa: BLE001
        out.setdefault("raw", []).append({"jan": jan, "error": str(e)[:300]})
for jan, buy in [("4548736132610", 40000), ("4902370550733", 40000), ("4549995635232", 30000)]:
    try:
        offers = rakuten.search_jan(c, os.environ.get("RAKUTEN_APP_ID", ""), os.environ.get("RAKUTEN_ACCESS_KEY", ""), jan, buy, keep=3)
        out["results"].append({"jan": jan, "n": len(offers), "top": [{k: o[k] for k in ("n", "p", "pt", "ptr", "sh", "s")} for o in offers]})
    except Exception as e:  # noqa: BLE001
        out["results"].append({"jan": jan, "error": str(e)[:400]})
Path("data/rakuten_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False)[:2000])
