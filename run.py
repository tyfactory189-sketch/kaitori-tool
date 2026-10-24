"""買取価格とYahoo価格を集めて docs/data.json を作るメインスクリプト。

使い方:
  YAHOO_APPID=xxxx python run.py              # 買取商店を取得 → Yahoo照合 → 出力
  python run.py --skip-buyback                 # 買取価格は取り直さず Yahooだけ更新
  python run.py --skip-yahoo                   # 買取価格だけ更新
  python run.py --sources shouten,wiki         # 取得する買取サイトを指定（PCで動かす場合など）

買取wiki・森森買取は GitHub のサーバーからのアクセスを拒否するため、
通常はブラウザのブックマーク（docs/bookmarklet.html）で取得して data/ に保存する。

環境変数:
  YAHOO_APPID       Yahoo!デベロッパーのClient ID（必須）
  MIN_BUY           Yahoo照合する最低買取価格（既定 3000）
  YAHOO_BUDGET_MIN  1回の実行でYahoo照合に使う最大分数（既定 240）
"""
import argparse
import json
import os
import re
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

# Yahoo の実質価格（価格−ストアポイント）が買取価格のこの倍率を超える出品は、
# 還元を最大まで積んでも利益が出ないので保存しない（データを軽くするため）
KEEP_RATIO = 1.35
KEEP_OFFERS = 3

# 実行結果の記録（data/run_log.json に保存。Actionsのログを見なくても状況が分かるように）
RUN_LOG: dict = {}


def now_iso():
    return datetime.now(JST).isoformat(timespec="minutes")


def log(msg):
    print(msg, flush=True)


def load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            log(f"[warn] {path.name} を読めません: {e}")
    return default


def save(path: Path, obj, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = {"separators": (",", ":")} if compact else {"indent": 1}
    path.write_text(json.dumps(obj, ensure_ascii=False, **kw), encoding="utf-8")


def load_buyback(key):
    """data/buyback_<key>.json を読む。

    サーバー取得分はリスト、ブラウザ取得分は {"updated":..., "items":[...]} の形。
    戻り値: (items, updated or None)
    """
    raw = load(DATA / f"buyback_{key}.json", [])
    if isinstance(raw, dict):
        return raw.get("items", []), raw.get("updated")
    return raw, None


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


def source_status():
    status = load(DATA / "status.json", {})
    out = {}
    for key in SCRAPERS:
        items, updated = load_buyback(key)
        if updated:  # ブラウザ取得分はファイル自体の日時を使う
            out[key] = {"label": SOURCE_LABELS[key], "count": len(items),
                        "updated": updated, "error": "", "manual": True}
        elif not items:  # まだ一度も取得していない
            out[key] = {"label": SOURCE_LABELS[key], "count": 0, "manual": True}
        else:
            out[key] = {"label": SOURCE_LABELS[key], **status.get(key, {})}
    return out


def merged_buyback():
    """JANごとに各買取サイトの価格をまとめる。"""
    by_jan = {}
    for key in SCRAPERS:
        items, _ = load_buyback(key)
        for it in items:
            jan, price = str(it.get("jan", "")), it.get("price")
            if not jan or not isinstance(price, (int, float)) or price <= 0:
                continue
            rec = by_jan.setdefault(jan, {"jan": jan, "name": it.get("name", ""), "buys": {}})
            cur = rec["buys"].get(key)
            if not cur or price > cur["p"]:
                rec["buys"][key] = {"p": int(price), "u": it.get("url", ""), "note": it.get("note", "")}
            if len(it.get("name", "")) > len(rec["name"]):
                rec["name"] = it["name"]
    return by_jan


def top_buy(rec):
    return max(b["p"] for b in rec["buys"].values())


def trim_offers(offers, buy):
    """利益の見込みがない出品を落とし、上位だけ残す。"""
    keep = [o for o in offers
            if o["p"] - o.get("pt", 0) <= buy * KEEP_RATIO and not yahoo.EXCLUDE.search(o.get("n", ""))]
    return keep[:KEEP_OFFERS]


def update_yahoo(by_jan, cache, appid, min_buy, budget_min):
    """前回照合が古いもの（未照合が最優先）から順にYahooを検索。時間切れなら残りは次回へ。"""
    targets = []
    for jan, rec in by_jan.items():
        top = top_buy(rec)
        if top >= min_buy:
            targets.append((cache.get(jan, {}).get("at", ""), -top, jan, top))
    targets.sort()
    client = Client(delay=1.1, retries=2, backoff=5)
    deadline = time.time() + budget_min * 60
    done = fails = streak = 0
    errors: dict[str, int] = {}
    last_error = ""
    stopped = ""
    for _, _, jan, top in targets:
        if time.time() > deadline:
            stopped = "時間切れ（残りは次回）"
            break
        try:
            offers = yahoo.search_jan(client, appid, jan, top, keep=10)
        except Exception as e:  # noqa: BLE001
            fails += 1
            streak += 1
            last_error = str(e)[:300]
            m = re.search(r"HTTP (\d{3})", last_error)
            key = f"HTTP {m.group(1)}" if m else type(e).__name__
            errors[key] = errors.get(key, 0) + 1
            log(f"[yahoo] {jan} 失敗: {last_error}")
            if streak >= 15:
                stopped = "Yahoo APIが連続で失敗したため中断"
                log(f"[yahoo] {stopped}: {last_error}")
                break
            continue
        streak = 0
        cache[jan] = {"at": now_iso(), "o": trim_offers(offers, top)}
        done += 1
        if done % 500 == 0:
            log(f"[yahoo] {done}/{len(targets)}")
            save(DATA / "yahoo_cache.json", cache, compact=True)
    cache = {k: v for k, v in cache.items() if k in by_jan}
    save(DATA / "yahoo_cache.json", cache, compact=True)
    log(f"[yahoo] 更新 {done}件 / 失敗 {fails}件 / 対象 {len(targets)}件 {stopped}")
    RUN_LOG["yahoo"] = {"targets": len(targets), "done": done, "failed": fails,
                        "errors": errors, "last_error": last_error, "stopped": stopped}
    return cache


def build(by_jan, cache):
    items = []
    for jan, rec in by_jan.items():
        y = cache.get(jan)
        if not y:
            continue
        offers = trim_offers(y.get("o", []), top_buy(rec))
        if not offers:
            continue
        items.append({"jan": jan, "name": rec["name"], "buys": rec["buys"], "offers": offers, "at": y["at"]})
    out = {"updated": now_iso(), "sources": source_status(), "items": items, "yahoo": RUN_LOG.get("yahoo")}
    save(DOCS / "data.json", out, compact=True)
    log(f"[build] {len(items)}件を docs/data.json に出力")
    RUN_LOG.update({"finished": now_iso(), "items": len(items)})
    save(DATA / "run_log.json", RUN_LOG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="shouten", help="取得する買取サイト（カンマ区切り）")
    ap.add_argument("--skip-buyback", action="store_true")
    ap.add_argument("--skip-yahoo", action="store_true")
    args = ap.parse_args()
    RUN_LOG["started"] = now_iso()

    if not args.skip_buyback:
        update_buyback([s for s in args.sources.split(",") if s in SCRAPERS])
    by_jan = merged_buyback()
    log(f"買取データ {len(by_jan)} JAN")

    cache = load(DATA / "yahoo_cache.json", {})
    if not args.skip_yahoo:
        appid = os.environ.get("YAHOO_APPID", "").strip()
        if not appid:
            build(by_jan, cache)
            sys.exit("★エラー: YAHOO_APPID が設定されていません。"
                     "Settings → Secrets and variables → Actions に登録してください")
        cache = update_yahoo(
            by_jan, cache, appid,
            int(os.environ.get("MIN_BUY", "3000")),
            int(os.environ.get("YAHOO_BUDGET_MIN", "300")),
        )
    build(by_jan, cache)


if __name__ == "__main__":
    main()
