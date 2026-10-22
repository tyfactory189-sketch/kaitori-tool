"""共通HTTPクライアント。

curl_cffi が入っていれば Chrome のTLS指紋を真似て取得する（ボット判定の強いサイト対策）。
入っていなければ requests で取得する。
"""
import time
import random

try:
    from curl_cffi import requests as _req  # type: ignore
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # pragma: no cover
    import requests as _req  # type: ignore
    _IMPERSONATE = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class Client:
    """サイトごとに1つ作る。delay 秒以上の間隔を空けてアクセスする。"""

    def __init__(self, delay: float = 1.0, retries: int = 3):
        self.delay = delay
        self.retries = retries
        self._last = 0.0
        self.session = _req.Session()
        self.session.headers.update(HEADERS)

    def _wait(self):
        gap = self.delay + random.uniform(0, self.delay * 0.3)
        sleep = self._last + gap - time.time()
        if sleep > 0:
            time.sleep(sleep)
        self._last = time.time()

    def get(self, url: str, params=None, as_json: bool = False):
        last_err = None
        for attempt in range(self.retries):
            self._wait()
            try:
                r = self.session.get(url, params=params, timeout=30, **_IMPERSONATE)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(10 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json() if as_json else r.text
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"GET失敗 {url}: {last_err}")
