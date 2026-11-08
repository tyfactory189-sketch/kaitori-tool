"""Amazon Creators API の接続確認（数件検索して data/amazon_test.json に書く）。"""
import json, os, time
from pathlib import Path
import amazon

env = {k: os.environ.get(k, "").strip() for k in ("AMAZON_CREDENTIAL_ID", "AMAZON_CREDENTIAL_SECRET", "AMAZON_CREDENTIAL_VERSION", "AMAZON_PARTNER_TAG")}
# 認証情報の中身は絶対に書き出さない（リポジトリは公開）。形式が正しいかだけ確かめる
ver = env["AMAZON_CREDENTIAL_VERSION"]
out = {"at": time.strftime("%Y-%m-%d %H:%M"), "has": {k: bool(v) for k, v in env.items()},
       "version_ok": bool(__import__("re").search(r"[23]\s*[.．]\s*[123]", ver)), "version_len": len(ver),
       "id_looks_like_secret": env["AMAZON_CREDENTIAL_ID"].startswith("amzn1.oa2-cs"),
       "version_shape": __import__("re").sub(r"[A-Za-z]", "a", __import__("re").sub(r"\d", "9", ver)),
       "tag_shape": __import__("re").sub(r"[A-Za-z]", "a", env["AMAZON_PARTNER_TAG"])[-6:],
       "tag_ok": bool(__import__("re").fullmatch(r"[\w-]+-2[0-9]", env["AMAZON_PARTNER_TAG"])), "results": []}
try:
    api = amazon.Creators(env["AMAZON_CREDENTIAL_ID"], env["AMAZON_CREDENTIAL_SECRET"], env["AMAZON_CREDENTIAL_VERSION"] or "3.3", env["AMAZON_PARTNER_TAG"])
    api.token()
    out["token"] = "ok"
    for jan, buy, names in [("4549995635232", 30000, ["AirPods Pro 3 MFHP4J/A"]), ("4548736132610", 40000, ["SONY WH-1000XM5"]), ("4902370550733", 40000, [])]:
        try:
            raw = api.search(jan)
            rows = amazon.parse(raw)
            out["results"].append({"jan": jan, "raw_keys": list(raw.keys())[:6], "rows": rows[:4],
                                   "offers": amazon.search_jan(api, jan, buy, keep=3, names=names)})
        except Exception as e:  # noqa: BLE001
            out["results"].append({"jan": jan, "error": str(e)[:400]})
except Exception as e:  # noqa: BLE001
    msg = str(e)
    for v in env.values():
        if v:
            msg = msg.replace(v, "***")
    out["error"] = msg[:500]
Path("data/amazon_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
