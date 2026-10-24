/* GitHub への保存（ウォッチリスト用）。一覧画面とウォッチリスト画面で共用。
 * 合鍵（トークン）はこのブラウザの localStorage にだけ保存する。
 */
window.KTS_GH = (() => {
  const TOKEN_KEY = 'kts_github_token';
  const WATCH_PATH = 'docs/watchlist.json';
  const LOCAL_WATCH = 'kts_watch_local';

  // https://user.github.io/repo/... → user/repo
  function repo() {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const seg = location.pathname.split('/').filter(Boolean)[0];
    try { const o = localStorage.getItem('kts_repo'); if (o) return o; } catch (e) { /* noop */ }
    return m && seg && !/\.html$/.test(seg) ? m[1] + '/' + seg : '';
  }
  const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
  const setToken = t => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) { /* noop */ } };
  function askToken() {
    let t = getToken();
    if (!t) {
      t = (prompt('保存にはGitHubの合鍵（トークン）が必要です。\n「買取価格を取得」ボタン用に作った github_pat_… をここに貼り付けてください（このブラウザで初回だけ）。') || '').trim();
      if (t) setToken(t);
    }
    return t;
  }
  async function api(path, opt = {}) {
    const r = await fetch('https://api.github.com/repos/' + repo() + path, {
      ...opt,
      headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + opt.token, 'X-GitHub-Api-Version': '2022-11-28', ...(opt.body ? { 'Content-Type': 'application/json' } : {}) },
    });
    if (r.status === 401) { setToken(''); throw new Error('合鍵（トークン）が無効です。もう一度保存すると入力を求められます。'); }
    return r;
  }
  const b64enc = s => new Promise(res => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(',')[1]); fr.readAsDataURL(new Blob([s])); });
  const b64dec = b => new TextDecoder().decode(Uint8Array.from(atob(b.replace(/\n/g, '')), c => c.charCodeAt(0)));

  const normalize = raw => (Array.isArray(raw) ? raw : (raw && raw.items) || []).filter(w => w && /^\d{8,14}$/.test(String(w.jan)));

  // ウォッチリストを読む：合鍵があれば GitHub から最新を、なければ公開ページのファイルを読む
  async function loadWatch() {
    const t = getToken();
    if (t && repo()) {
      try {
        const r = await api('/contents/' + WATCH_PATH + '?ref=main', { token: t });
        if (r.status === 404) return { items: [], sha: undefined };
        if (r.ok) { const j = await r.json(); return { items: normalize(JSON.parse(b64dec(j.content))), sha: j.sha }; }
      } catch (e) { /* 公開ファイルにフォールバック */ }
    }
    try {
      const r = await fetch('watchlist.json', { cache: 'no-store' });
      const items = r.ok ? normalize(await r.json()) : [];
      // 保存直後は公開ページの反映が遅れるので、このブラウザで最後に保存した内容を優先
      const local = JSON.parse(localStorage.getItem(LOCAL_WATCH) || 'null');
      if (local && Date.now() - local.at < 10 * 60e3) return { items: normalize(local.items), sha: undefined };
      return { items, sha: undefined };
    } catch (e) { return { items: [], sha: undefined }; }
  }

  // ウォッチリストを保存。他の画面で更新されていたら最新を読み直して変更を重ねる
  async function saveWatch(items, mutate) {
    const token = askToken();
    if (!token) throw new Error('合鍵が入力されなかったので保存していません。');
    for (let attempt = 0; attempt < 3; attempt++) {
      const cur = await api('/contents/' + WATCH_PATH + '?ref=main', { token });
      let sha, base = items;
      if (cur.ok) {
        const j = await cur.json(); sha = j.sha;
        if (mutate) base = mutate(normalize(JSON.parse(b64dec(j.content))));
      } else if (mutate) base = mutate([]);
      base.sort((a, b) => (b.added || '').localeCompare(a.added || ''));
      const body = JSON.stringify({ updated: new Date().toISOString(), items: base }, null, 1);
      const r = await api('/contents/' + WATCH_PATH, {
        method: 'PUT', token,
        body: JSON.stringify({ message: 'ウォッチリストを更新（' + base.length + '件）', content: await b64enc(body), sha, branch: 'main' }),
      });
      if (r.ok) {
        try { localStorage.setItem(LOCAL_WATCH, JSON.stringify({ at: Date.now(), items: base })); } catch (e) { /* noop */ }
        return base;
      }
      if (r.status === 403 || r.status === 404) throw new Error('保存する権限がありません（HTTP ' + r.status + '）。合鍵の「Contents: Read and write」権限を確認してください。');
      if (r.status !== 409 && r.status !== 422) throw new Error('保存に失敗しました（HTTP ' + r.status + '）');
    }
    throw new Error('保存に失敗しました（同時に更新されました）。もう一度お試しください。');
  }

  // Yahoo照合を今すぐ開始（買取サイトの取得は飛ばす）
  async function startYahoo() {
    const token = getToken();
    if (!token) return false;
    const r = await api('/actions/workflows/update.yml/dispatches', {
      method: 'POST', token, body: JSON.stringify({ ref: 'main', inputs: { skip_buyback: true } }),
    });
    return r.status === 204;
  }

  // 「4549995635232 メモ」の形の行から JAN とメモを取り出す（JANだけの行や、表からの貼り付けにも対応）
  function parseInput(text) {
    const out = [];
    for (const line of String(text).split(/\r?\n/)) {
      const m = line.match(/(?:^|\D)(\d{13}|\d{8})(?!\d)/);
      if (!m) continue;
      const memo = line.replace(m[1], '').replace(/^[\s,\t:：、|]+|[\s,\t|]+$/g, '').slice(0, 80);
      out.push({ jan: m[1], memo });
    }
    return out;
  }

  return { repo, getToken, setToken, loadWatch, saveWatch, startYahoo, parseInput };
})();
