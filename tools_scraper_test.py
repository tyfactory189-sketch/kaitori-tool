"""買取サイトの取得テスト（件数と先頭数件を data/scraper_test.json に書く）。"""
import json, sys, time
from pathlib import Path
from scrapers import SCRAPERS

key = sys.argv[1]
logs = []
t = time.time()
try:
    items = SCRAPERS[key].scrape(log=lambda m: logs.append(str(m)))
    out = {"source": key, "count": len(items), "sample": items[:8], "items": items if len(items) < 30000 else [], "secs": int(time.time() - t), "log": logs}
except Exception as e:  # noqa: BLE001
    out = {"source": key, "error": str(e)[:500], "log": logs}
Path("data/scraper_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
