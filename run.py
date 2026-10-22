"""買取価格とYahoo価格を集めて docs/data.json を作るメインスクリプト。

使い方:
  YAHOO_APPID=xxxx python run.py              # 全部
  python run.py --skip-yahoo                   # 買取価格だけ更新
  python run.py --sources wiki,morimori        # 買取サイトを絞る

環境変数:
  YAHOO_APPID       Yahoo!デベロッパーのClient ID（必須）
  MIN_BUY           Yahoo照合する最低買取価格（既定 3000）
  YAHOO_BUDGET_MIN  1回の実行でYahoo照合に使う最大分数（既定 240）
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scrapers import SCRAPERS, SOURCE_LABELS
from scrapers.http import Client
import yahoo

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
JST = timezone(timedelta(hours=9))


def now_iso():
    return datetime.now(JST).isoformat(timespec="minutes")


def log(msg):
    print(msg, flush=True)


def load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save(path: Path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = {"separators": (",", ":")} if compact else {"indent": 1}
    path.write_text(json.dumps(obj, ensure_ascii=False, **kw), encoding="utf-8")


def update_buyback(sources):
    """各買取サイトを取得して data/buyback_<source>.json に保存。失敗したら前回分を使う。"""
    status = load(DATA / "status.json", {})
    for key in sources:
        try:
            items = SCRAPERS[key].scrape(log=log)
            if not items:
                raise RuntimeError("0件（ページ構造が変わった可能性）")
            save(DATA / f"buyback_{key}.json", items)
            status[key] = {"count": len(items), "updated": now_iso(), "error": ""}
            log(f"[{key}] {len(items)}件 保存")
        except Exception as e:  # noqa: BLE001
            prev = status.get(key, {})
            status[key] = {**prev, "error": f"{now_iso()} {e}"[:300]}
            log(f"[{key}] 失敗: {e}（前回データを使用）")
    save(DATA / "status.json", status)


def merged_buyback():
    """JANごとに各買取サイトの価格をまとめる。"""
    by_jan = {}
    for key in SCRAPERS:
        for it in load(DATA / f"buyback_{key}.json", []):
            rec = by_jan.setdefault(it["jan"], {"jan": it["jan"], "name": it["name"], "buys": {}})
            cur = rec["buys"].get(key)
            if not cur or it["price"] > cur["p"]:
                rec["buys"][key] = {"p": it["price"], "u": it["url"], "note": it.get("note", "")}
            if len(it["name"]) > len(rec["name"]):
                rec["name"] = it["name"]
    return by_jan


def update_yahoo(by_jan, appid, min_buy, budget_min):
    """前回照合が古いものから順にYahooを検索。時間切れになったら残りは次回へ。"""
    cache = load(DATA / "yahoo_cache.json", {})
    targets = []
    for jan, rec in by_jan.items():
        top = max(b["p"] for b in rec["buys"].values())
        if top >= min_buy:
            targets.append((cache.get(jan, {}).get("at", ""), -top, jan, top))
    targets.sort()
    client = Client(delay=1.1)
    deadline = time.time() + budget_min * 60
    done = 0
    for _, _, jan, top in targets:
        if time.time() > deadline:
            log(f"[yahoo] 時間切れ。{done}/{len(targets)}件を更新、残りは次回")
            break
        try:
            offers = yahoo.search_jan(client, appid, jan, top)
            cache[jan] = {"at": now_iso(), "o": offers}
        except Exception as e:  # noqa: BLE001
            log(f"[yahoo] {jan} 失敗: {e}")
            continue
        done += 1
        if done % 500 == 0:
            log(f"[yahoo] {done}/{len(targets)}")
            save(DATA / "yahoo_cache.json", cache, compact=True)
    # 買取側から消えたJANはキャッシュからも消す
    cache = {k: v for k, v in cache.items() if k in by_jan}
    save(DATA / "yahoo_cache.json", cache, compact=True)
    log(f"[yahoo] 更新 {done}件 / 対象 {len(targets)}件")
    return cache


def build(by_jan, cache):
    status = load(DATA / "status.json", {})
    items = []
    for jan, rec in by_jan.items():
        y = cache.get(jan)
        if not y or not y["o"]:
            continue
        items.append({
            "jan": jan,
            "name": rec["name"],
            "buys": rec["buys"],
            "offers": y["o"],
            "at": y["at"],
        })
    out = {
        "updated": now_iso(),
        "sources": {k: {"label": SOURCE_LABELS[k], **status.get(k, {})} for k in SCRAPERS},
        "items": items,
    }
    save(DOCS / "data.json", out, compact=True)
    log(f"[build] {len(items)}件を docs/data.json に出力")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=",".join(SCRAPERS))
    ap.add_argument("--skip-buyback", action="store_true")
    ap.add_argument("--skip-yahoo", action="store_true")
    args = ap.parse_args()

    if not args.skip_buyback:
        update_buyback([s for s in args.sources.split(",") if s in SCRAPERS])
    by_jan = merged_buyback()
    log(f"買取データ {len(by_jan)} JAN")

    cache = load(DATA / "yahoo_cache.json", {})
    if not args.skip_yahoo:
        appid = os.environ.get("YAHOO_APPID", "").strip()
        if not appid:
            sys.exit("YAHOO_APPID が設定されていません")
        cache = update_yahoo(
            by_jan, appid,
            int(os.environ.get("MIN_BUY", "3000")),
            int(os.environ.get("YAHOO_BUDGET_MIN", "240")),
        )
    build(by_jan, cache)


if __name__ == "__main__":
    main()
