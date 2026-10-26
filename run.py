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
STARTED = time.time()
# 1回の実行全体の上限（分）。GitHub Actions の timeout-minutes(355) より十分短くし、
# 次の定期実行や拡張機能からの実行が長く待たされないようにする
JOB_MAX_MIN = int(os.environ.get("JOB_MAX_MIN", "170"))


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


# 買取wikiでは iPhone・iPad・Mac などが「容量・色を選ぶ1商品」として載っていて、
# 一覧の買取価格は一番高い仕様（例: 2TB）の金額になっていることがある。
# 商品名に容量が無いこれらの商品は「仕様で価格が変わる」印（m）を付け、画面側で扱いを選べるようにする。
RE_MULTI_FAMILY = re.compile(
    r"iPad|iPhone|MacBook|iMac|Mac ?mini|Mac ?Studio|Mac ?Pro|Pixel ?\d|Galaxy ?[ASZ]\d|Surface|Steam ?Deck")
RE_CAPACITY = re.compile(r"\d+\s*(GB|TB|G)\b|\d+G\+\d+G|\d+GB?/\d+", re.I)
MULTI_SITES = ("iphonekaitori.tokyo", "ipadkaitori.jp", "pckaitori.tokyo", "gamekaitori.jp")


# 「MHFA4J/A」のような型番が入っていれば仕様は1つに決まっている
RE_MODEL_NO = re.compile(r"\b[A-Z0-9]{4,6}\d?[A-Z]{0,2}/A\b")


def is_multi_spec(key, it):
    name, url = it.get("name", ""), it.get("url", "")
    return (key == "wiki" and any(d in url for d in MULTI_SITES)
            and bool(RE_MULTI_FAMILY.search(name)) and not RE_CAPACITY.search(name)
            and not RE_MODEL_NO.search(name))


def norm(s):
    """表記ゆれを吸収（全角→半角、空白除去、小文字）。"""
    import unicodedata
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def resolve_variant(goods, names):
    """容量・色ごとの買取価格（Chrome拡張が専用サイトから取得）から、このJANの仕様を商品名で特定する。

    goods: {"variants": [{"sel": {"color": "シルバー", "gb": "256GB"}, "p": 168500}, ...]}
    names: このJANの各店・Yahooの商品名
    戻り値: (価格, 仕様ラベル) か None
    """
    text = norm(" ".join(names))
    vs = [v for v in goods.get("variants", []) if v.get("p")]
    if not vs:
        return None
    hit = [v for v in vs if all(norm(lbl) in text for lbl in v["sel"].values() if lbl)]
    if not hit:
        # 容量だけ分かる場合、その容量の価格が全色同じなら確定
        caps = [v for v in vs if v["sel"].get("gb") and norm(v["sel"]["gb"]) in text]
        if caps and len({v["p"] for v in caps}) == 1:
            return caps[0]["p"], caps[0]["sel"]["gb"]
    if hit and len({v["p"] for v in hit}) == 1:
        v = hit[0]
        return v["p"], " ".join(x for x in v["sel"].values() if x)
    return None


def apply_variants(by_jan, extra_names=None):
    """data/wiki_variants.json を使って、買取wikiの「仕様で変わる」価格を確定させる。"""
    data = load(DATA / "wiki_variants.json", {})
    goods_by_jan = data.get("goods", {}) if isinstance(data, dict) else {}
    fixed = 0
    for jan, rec in by_jan.items():
        b = rec["buys"].get("wiki")
        g = goods_by_jan.get(jan)
        if not b or not g:
            continue
        if g.get("single"):
            b.pop("m", None)
            continue
        vs = [v["p"] for v in g.get("variants", []) if v.get("p")]
        if not vs:
            continue
        names = list(rec.get("names", [])) + list((extra_names or {}).get(jan, []))
        r = resolve_variant(g, names)
        if r:
            b["p"], b["v"] = r
            b.pop("m", None)
            fixed += 1
        else:
            b["m"] = 1
            b["r"] = [min(vs), max(vs)]
    return fixed


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
                if is_multi_spec(key, it):
                    rec["buys"][key]["m"] = 1
            if len(it.get("name", "")) > len(rec["name"]):
                rec["name"] = it["name"]
            rec.setdefault("names", set()).add(it.get("name", ""))
    # 扱わないジャンル（ポケモンカード）は商品ごと外す（Yahooの照合もしない）
    for jan in [j for j, r in by_jan.items() if any(yahoo.SKIP_ITEM.search(n or "") for n in r.get("names", ()))]:
        del by_jan[jan]
    apply_variants(by_jan)
    return by_jan


def top_buy(rec):
    return max((b["p"] for b in rec["buys"].values()), default=0)


def load_watch():
    """ウォッチリスト（過去に買った商品など）。画面から docs/watchlist.json に保存される。"""
    raw = load(DOCS / "watchlist.json", {})
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    return {str(w["jan"]): w for w in items if str(w.get("jan", "")).isdigit()}


def trim_offers(offers, buy, watched=False):
    """利益の見込みがない出品を落とし、上位だけ残す（ウォッチ商品は価格に関係なく残す）。"""
    if watched or buy <= 0:
        return [o for o in offers if not yahoo.EXCLUDE.search(o.get("n", "")) and not yahoo.SKIP_ITEM.search(o.get("n", ""))][:KEEP_OFFERS]
    keep = [o for o in offers
            if o["p"] - o.get("pt", 0) <= buy * KEEP_RATIO and not yahoo.EXCLUDE.search(o.get("n", "")) and not yahoo.SKIP_ITEM.search(o.get("n", ""))]
    return keep[:KEEP_OFFERS]


def check_variants(client, offers, jan, buy, watched, chk, names=()):
    """利益が出そうな出品だけ商品ページを開き、仕様選択・必須オプションによる価格差を反映する。"""
    # 還元を最大20%と見ても利益が出ない出品は確認しない（時間節約）
    cands = [o for o in offers if watched or o["p"] - o["pt"] - o["p"] / 1.1 * 0.20 <= buy][:2]
    for o in cands:
        try:
            if yahoo.check_offer(client, o, jan, names):
                chk["changed"] += 1
            chk["checked"] += 1
        except Exception as e:  # noqa: BLE001
            chk["failed"] += 1
            chk["last_error"] = str(e)[:200]
            # 最初から失敗続きなら（アクセス拒否など）、この実行では確認をやめる
            if chk["failed"] >= 10 and chk["checked"] == 0:
                chk["disabled"] = True
                log(f"[yahoo] 商品ページを開けないため確認を中止: {chk['last_error']}")
                return
    offers[:] = [o for o in offers if not o.get("ng")]  # 在庫なし・中古・予約などは除外
    offers.sort(key=lambda o: o["p"] - o["pt"])


def due_hours(entry):
    """前回の照合結果から、次に照合するまでの間隔（時間）を決める。
    Yahoo API は1日の利用回数に上限があるので、利益の見込みが薄い商品はたまにしか調べない。"""
    r = entry.get("r")
    if r is None:
        return 24
    if r <= 1.15:   # 実質価格が買取価格の1.15倍以内：毎回
        return 4
    if r <= 1.4:
        return 24
    return 72       # 見込みが薄い・Yahooに出品なし


# Yahoo API の 429（短時間にアクセスが多いと一時的に利用制限）を受けたときの待ち時間（秒）
LIMIT_WAITS = (60, 180, 600, 900)


def update_yahoo(by_jan, cache, appid, min_buy, budget_min, watch):
    """ウォッチ商品を毎回最初に照合し、その後は「照合の時期が来た」商品を見込みの高い順に。
    1回あたりの問い合わせ数は YAHOO_MAX_REQ（既定 9000）まで。時間切れ・上限なら残りは次回へ。"""
    max_req = int(os.environ.get("YAHOO_MAX_REQ", "9000"))
    now = datetime.now(JST)
    targets = []
    for jan in watch:  # ウォッチ商品は買取価格に関係なく毎回
        top = top_buy(by_jan[jan]) if jan in by_jan else 0
        targets.append((0, 0, "", jan, top))
    skipped = 0
    for jan, rec in by_jan.items():
        top = top_buy(rec)
        if top < min_buy or jan in watch:
            continue
        e = cache.get(jan, {})
        if len(jan) == 12 and e.get("r") == 9.9 and not e.get("o"):
            e = {}  # 以前 400 で失敗した12桁JAN（先頭0付きで再照合）
        try:
            age = (now - datetime.fromisoformat(e["at"])).total_seconds() / 3600
        except (KeyError, ValueError):
            age = 1e9  # 未照合
        if age < due_hours(e):
            skipped += 1
            continue
        targets.append((1, e.get("r", 0.0) if e else -1, e.get("at", ""), jan, top))
    targets.sort()
    targets = [(t[2], 0, t[3], t[4]) for t in targets][:max_req]
    log(f"[yahoo] 今回の照合対象 {len(targets)}件（時期が来ていない {skipped}件は省略）")
    client = Client(delay=float(os.environ.get("YAHOO_DELAY", "2.1")), retries=1, backoff=5)
    page_client = Client(delay=0.8, retries=1, backoff=3)
    chk = {"checked": 0, "changed": 0, "failed": 0, "last_error": "", "disabled": False}
    # 買取商店の取得などで使った時間を差し引き、全体が JOB_MAX_MIN に収まるようにする（集計・保存に10分残す）
    deadline = min(time.time() + budget_min * 60, STARTED + (JOB_MAX_MIN - 10) * 60)
    done = fails = streak = hits429 = 0
    first_429 = ""
    err = None
    started = time.time()
    errors: dict[str, int] = {}
    last_error = ""
    first_400 = ""
    stopped = ""
    for _, _, jan, top in targets:
        if time.time() > deadline:
            stopped = "時間切れ（残りは次回）"
            break
        offers = None
        for wait in (0, *LIMIT_WAITS):
            if wait:
                if time.time() + wait > deadline:
                    break
                log(f"[yahoo] 一時的な利用制限（429）。{wait}秒待って再開します（{done}件目のあと）")
                time.sleep(wait)
            try:
                offers = yahoo.search_jan(client, appid, jan, top, keep=10)
                break
            except Exception as e:  # noqa: BLE001
                err = e
                if "limit count" not in str(e):
                    break
                hits429 += 1
                first_429 = first_429 or f"{done}件目のあと（開始から{int(time.time() - started)}秒）"
        if offers is None:
            e = err
        try:
            if offers is None:
                raise e
        except Exception as e:  # noqa: BLE001
            fails += 1
            streak += 1
            last_error = str(e)[:300]
            m = re.search(r"HTTP (\d{3})", last_error)
            key = f"HTTP {m.group(1)}" if m else type(e).__name__
            errors[key] = errors.get(key, 0) + 1
            log(f"[yahoo] {jan} 失敗: {last_error}")
            if "limit count" in last_error:
                stopped = "Yahoo API の利用制限（429）が待っても解除されないため中断（次回に再開）"
                log(f"[yahoo] {stopped}")
                break
            if key == "HTTP 400":  # その商品だけの問題（JANの形式など）。連続失敗には数えない
                streak -= 1
                first_400 = first_400 or f"{jan}: {last_error}"
                cache[jan] = {"at": now_iso(), "o": [], "r": 9.9}
                continue
            if streak >= 15:
                stopped = "Yahoo APIが連続で失敗したため中断"
                log(f"[yahoo] {stopped}: {last_error}")
                break
            continue
        streak = 0
        offers = drop_excluded(offers)
        if not chk["disabled"]:
            check_variants(page_client, offers, jan, top, jan in watch, chk,
                           list(by_jan.get(jan, {}).get("names", [])))
        kept = trim_offers(offers, top, jan in watch)
        best = min((o["p"] - o.get("pt", 0) for o in offers), default=None)
        cache[jan] = {"at": now_iso(), "o": kept, "r": round(best / top, 3) if best and top else 9.9}
        done += 1
        if done % 500 == 0:
            log(f"[yahoo] {done}/{len(targets)}")
            save(DATA / "yahoo_cache.json", cache, compact=True)
    cache = {k: v for k, v in cache.items() if k in by_jan or k in watch}
    save(DATA / "yahoo_cache.json", cache, compact=True)
    log(f"[yahoo] 更新 {done}件 / 失敗 {fails}件 / 対象 {len(targets)}件 {stopped}")
    RUN_LOG["yahoo"] = {"targets": len(targets), "done": done, "failed": fails,
                        "errors": errors, "last_error": last_error, "first_400": first_400[:300],
                        "stopped": stopped, "skipped_not_due": skipped,
                        "limited_429": hits429, "first_429": first_429}
    RUN_LOG["item_check"] = chk
    log(f"[yahoo] 商品ページ確認 {chk['checked']}件 / 価格補正 {chk['changed']}件 / 失敗 {chk['failed']}件")
    return cache


def load_yahoo_user():
    """Chrome拡張がログイン状態で確認した「あなたの条件での価格・ポイント」。36時間より古いものは使わない。"""
    raw = load(DATA / "yahoo_user.json", {})
    out = {}
    for url, v in (raw.get("offers") or {}).items():
        try:
            age = datetime.now(JST) - datetime.fromisoformat(v["at"])
        except (KeyError, ValueError):
            continue
        if age < timedelta(hours=36):
            out[url.split("?")[0]] = {k: v[k] for k in ("p", "pt", "rate", "capped", "at", "pv", "add", "ng", "sf", "sfc", "pref") if v.get(k) not in (None, [], "")}
    return out, raw.get("updated")


def encrypt_json(obj, password: str) -> dict:
    """ブラウザ（crypt.js）で復号できる形で暗号化する：PBKDF2-SHA256(20万回) → AES-256-GCM。"""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), None)
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256-200000", "alg": "AES-GCM", "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def load_excludes():
    """ツール画面の「この出品を除外」で登録された出品URL。"""
    try:
        d = json.loads((DOCS / "excludes.json").read_text(encoding="utf-8"))
        return {str(x.get("u", "")).split("?")[0] for x in d.get("items", []) if x.get("u")}
    except (OSError, ValueError):
        return set()


def drop_excluded(offers):
    ex = load_excludes()
    return [o for o in offers if (o.get("u") or "").split("?")[0] not in ex] if ex else offers


def build(by_jan, cache, watch):
    yu, yu_updated = load_yahoo_user()
    yahoo_names = {j: [o.get("n", "") for o in (c.get("o") or [])] for j, c in cache.items()}
    RUN_LOG["variants_fixed"] = apply_variants(by_jan, yahoo_names)
    items = []
    for jan in list(by_jan) + [j for j in watch if j not in by_jan]:
        rec = by_jan.get(jan, {"name": "", "buys": {}})
        watched = jan in watch
        y = cache.get(jan) or {}
        offers = trim_offers(drop_excluded(y.get("o", [])), top_buy(rec), watched)
        if not offers and not watched:
            continue
        name = rec["name"] or watch.get(jan, {}).get("memo") or (offers[0]["n"] if offers else "")
        for o in offers:
            u = yu.get((o.get("u") or "").split("?")[0])
            if u:
                o["yu"] = u
        offers = [o for o in offers if not (o.get("yu") or {}).get("ng")]
        if not offers and not watched:
            continue
        item = {"jan": jan, "name": name, "buys": rec["buys"], "offers": offers, "at": y.get("at", "")}
        if watched:
            item["w"] = 1
        items.append(item)
    out = {"updated": now_iso(), "sources": source_status(), "items": items, "yahoo": RUN_LOG.get("yahoo"), "yahoo_user": yu_updated}
    pw = os.environ.get("SITE_PASSWORD", "")
    if pw:
        # サイト全体をパスワードで保護：暗号化した data.enc.json だけを公開し、平文は消す
        save(DOCS / "data.enc.json", encrypt_json(out, pw), compact=True)
        (DOCS / "data.json").unlink(missing_ok=True)
        log(f"[build] {len(items)}件を docs/data.enc.json に暗号化して出力")
    else:
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
    watch = load_watch()
    log(f"ウォッチリスト {len(watch)}件")
    if not args.skip_yahoo:
        appid = os.environ.get("YAHOO_APPID", "").strip()
        if not appid:
            build(by_jan, cache, watch)
            sys.exit("★エラー: YAHOO_APPID が設定されていません。"
                     "Settings → Secrets and variables → Actions に登録してください")
        cache = update_yahoo(
            by_jan, cache, appid,
            int(os.environ.get("MIN_BUY", "3000")),
            int(os.environ.get("YAHOO_BUDGET_MIN", "160")),
            watch,
        )
    build(by_jan, cache, watch)


if __name__ == "__main__":
    main()
