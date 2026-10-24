/* 買取差益チェッカー：買取価格取得ブックマーク
 * 買取wiki（kadenkaitori.tokyo）または森森買取（morimori-kaitori.jp）のページで実行すると、
 * 全商品の新品買取価格を集めて GitHub リポジトリの data/buyback_<site>.json に保存し、
 * Yahoo照合（Actions の「価格データ更新」）を起動する。
 * __REPO__ は bookmarklet.html が「ユーザー名/リポジトリ名」に置き換える。
 */
(async () => {
  const REPO = '__REPO__';
  const DRY = window.__KTS_DRY_RUN === true; // テスト用：保存せず結果だけ返す
  if (window.__ktsRunning) { alert('取得中です。終わるまでお待ちください。'); return; }

  const host = location.hostname;
  const SITE = /kadenkaitori\.tokyo$/.test(host) ? 'wiki' : /morimori-kaitori\.jp$/.test(host) ? 'morimori' : null;
  const LABEL = { wiki: '買取wiki', morimori: '森森買取' }[SITE];
  if (!SITE) { alert('買取wiki（kadenkaitori.tokyo）か森森買取（morimori-kaitori.jp）のページを開いてから押してください。'); return; }
  const MIN_ITEMS = 1000; // これより少なければサイト構造が変わったとみなして保存しない
  window.__ktsRunning = true;

  // ---------- 進捗表示 ----------
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;width:340px;max-width:calc(100vw - 24px);background:#1d1d1b;color:#fff;font:13px/1.5 sans-serif;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.35);padding:14px 16px';
  box.innerHTML = '<div style="font-weight:700;margin-bottom:6px">買取差益チェッカー：' + LABEL + 'を取得中</div>' +
    '<div style="background:#444;border-radius:4px;height:8px;overflow:hidden"><div id="kts-bar" style="background:#ff5a4e;height:100%;width:0%"></div></div>' +
    '<div id="kts-msg" style="margin-top:8px;white-space:pre-wrap">準備中…</div>' +
    '<button id="kts-close" style="display:none;margin-top:10px;background:#fff;color:#1d1d1b;border:0;border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer">閉じる</button>';
  document.body.appendChild(box);
  let lastMsg = '';
  const bar = box.querySelector('#kts-bar'), msg = box.querySelector('#kts-msg'), closeBtn = box.querySelector('#kts-close');
  const show = (t, pct) => { lastMsg = t; msg.textContent = t; if (pct != null) bar.style.width = Math.min(100, pct).toFixed(1) + '%'; };
  const finish = (t, ok) => {
    show(t, ok ? 100 : null);
    bar.style.background = ok ? '#4cd38a' : '#ff5a4e';
    closeBtn.style.display = 'inline-block';
    closeBtn.onclick = () => box.remove();
    window.__ktsRunning = false;
  };

  // ---------- 共通 ----------
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const parser = new DOMParser();
  // サイトごとのアクセス速度。森森買取は速く取ると一時的にブロックされるので1件ずつゆっくり。
  const PACE = { wiki: { conc: 3, gap: 250 }, morimori: { conc: 1, gap: 1500 } }[SITE];
  let failed = 0;
  // 制限（403/429）や通信エラーのときは待ってから再試行。最後まで取れなければ null を返す
  const getDoc = async url => {
    const waits = [5, 30, 60, 120, 180];
    for (let i = 0; i <= waits.length; i++) {
      try {
        const r = await fetch(url, { credentials: 'same-origin' });
        if (r.ok) return parser.parseFromString(await r.text(), 'text/html');
        if (r.status === 404) return null;
      } catch (e) { /* 再試行 */ }
      if (i === waits.length) break;
      for (let s = waits[i]; s > 0; s--) {
        msg.textContent = lastMsg + `\nサイトから一時的に制限されました。${s}秒待って再開します…`;
        await sleep(1000);
      }
    }
    failed++;
    return null;
  };
  // 同時 conc 件まで並行して取得
  const pool = async (urls, conc, fn, onEach) => {
    let i = 0, done = 0;
    const worker = async () => {
      while (i < urls.length && failed <= 10) { // 制限が続くときは打ち切る
        const u = urls[i++];
        const d = await getDoc(u);
        if (d) fn(d);
        onEach(++done);
        await sleep(PACE.gap);
      }
    };
    await Promise.all(Array.from({ length: conc }, worker));
  };
  const num = s => parseInt(String(s).replace(/[^\d]/g, ''), 10);
  const abs = h => h ? new URL(h, location.origin).href : location.origin + '/';
  const text = el => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();

  // ---------- 買取wiki ----------
  async function grabWiki() {
    const items = [];
    const parse = d => {
      d.querySelectorAll('.pro_list').forEach(b => {
        const t = text(b);
        const jan = (t.match(/JAN[：:]\s*(\d{8,14})/) || [])[1];
        const price = (t.match(/買取価格[：:]\s*([\d,]+)\s*円/) || [])[1];
        if (!jan || !price) return;
        const name = text(b.querySelector('.sub-pro-name')).replace(/\s*\d{13}\s*$/, '');
        const a = b.querySelector('a[href]');
        items.push({ jan, name, price: num(price), url: abs(a && a.getAttribute('href')), note: /購入証明/.test(t) ? '購入証明必要' : '' });
      });
    };
    show('1ページ目を確認中…', 0);
    const first = await getDoc('/search/1');
    if (!first) throw new Error('買取wikiの1ページ目を開けませんでした。少し時間をおいてもう一度押してください。');
    const count = num((text(first.body).match(/([\d,]+)\s*件該当/) || [])[1] || 0);
    const per = first.querySelectorAll('.pro_list').length || 44;
    const pages = Math.ceil(count / per);
    parse(first);
    const urls = []; for (let p = 2; p <= pages; p++) urls.push('/search/' + p);
    await pool(urls, PACE.conc, parse, n => show(`${n + 1} / ${pages} ページ（${items.length.toLocaleString()}件）`, (n + 1) / pages * 90));
    return items;
  }

  // ---------- 森森買取 ----------
  async function grabMorimori() {
    const items = [];
    const parse = d => {
      d.querySelectorAll('.mm1551-prow').forEach(r => {
        const meta = text(r.querySelector('.mm1551-prow__meta'));
        const jan = (meta.match(/JAN[：:]\s*(\d{8,14})/) || [])[1];
        if (!jan || /中古/.test(meta)) return;
        const price = (text(r.querySelector('.mm1551-prow__cur')).match(/([\d,]+)\s*円/) || [])[1]; // 「ASK」は飛ばす
        if (!price) return;
        const a = r.querySelector('.mm1551-prow__name a[href]') || r.querySelector('a[href*="/product/"]');
        items.push({ jan, name: text(r.querySelector('.mm1551-prow__name')), price: num(price), url: abs(a && a.getAttribute('href')), note: '' });
      });
    };
    show('カテゴリを確認中…', 0);
    const home = await getDoc('/');
    if (!home) throw new Error('森森買取のトップページを開けませんでした。少し時間をおいてもう一度押してください。');
    const tops = [...new Set([...home.querySelectorAll('a[href]')].map(a => new URL(a.getAttribute('href'), location.origin).pathname).filter(p => /^\/category\/\d{2}$/.test(p)))];
    const urls = [];
    let ci = 0;
    for (const t of tops) {
      show(`カテゴリを確認中… ${++ci}/${tops.length}`, ci / tops.length * 5);
      const d = await getDoc(t);
      if (!d) continue;
      parse(d);
      const count = num((text(d.body).match(/該当\s*([\d,]+)\s*件/) || [])[1] || 0);
      const per = d.querySelectorAll('.mm1551-prow').length || 50;
      for (let p = 2; p <= Math.ceil(count / per); p++) urls.push(t + '?page=' + p);
      await sleep(PACE.gap);
    }
    await pool(urls, PACE.conc, parse, n => show(`${n} / ${urls.length} ページ（${items.length.toLocaleString()}件）\n残り約${Math.ceil((urls.length - n) * (PACE.gap + 700) / 60000)}分`, 5 + n / urls.length * 85));
    return items;
  }

  // ---------- GitHub へ保存 ----------
  const TOKEN_KEY = 'kts_github_token';
  const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
  const setToken = t => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) { /* noop */ } };
  const gh = (path, opt = {}) => fetch('https://api.github.com/repos/' + REPO + path, {
    ...opt,
    headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + opt.token, 'X-GitHub-Api-Version': '2022-11-28', ...(opt.body ? { 'Content-Type': 'application/json' } : {}) },
  });
  const toBase64 = s => new Promise(res => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(',')[1]);
    fr.readAsDataURL(new Blob([s], { type: 'application/json' }));
  });

  async function upload(json, token) {
    const path = 'data/buyback_' + SITE + '.json';
    const content = await toBase64(json);
    for (let attempt = 0; attempt < 2; attempt++) {
      const cur = await gh('/contents/' + path + '?ref=main', { token });
      if (cur.status === 401) throw Object.assign(new Error('合鍵（トークン）が無効です。'), { auth: true });
      const sha = cur.ok ? (await cur.json()).sha : undefined;
      const r = await gh('/contents/' + path, {
        method: 'PUT', token,
        body: JSON.stringify({ message: LABEL + ' 買取価格を更新（ブラウザ取得）', content, sha, branch: 'main' }),
      });
      if (r.ok) return;
      if (r.status === 401 || r.status === 403 || r.status === 404) {
        throw Object.assign(new Error('保存する権限がありません（HTTP ' + r.status + '）。合鍵の権限「Contents: Read and write」とリポジトリ名を確認してください。'), { auth: true });
      }
      if (r.status !== 409 && r.status !== 422) throw new Error('保存に失敗しました（HTTP ' + r.status + '）');
      await sleep(3000); // 同時に更新された場合はやり直す
    }
    throw new Error('保存に失敗しました（他の更新と重なりました）。もう一度押してください。');
  }

  async function startYahoo(token) {
    const r = await gh('/actions/workflows/update.yml/dispatches', {
      method: 'POST', token, body: JSON.stringify({ ref: 'main', inputs: { skip_buyback: true } }),
    });
    return r.status === 204;
  }

  // ---------- 実行 ----------
  try {
    let token = '';
    if (!DRY) {
      token = getToken();
      if (!token) {
        token = (prompt('GitHubの合鍵（トークン）を貼り付けてください。\n（このサイトで初回だけ。ブラウザ内に保存されます）') || '').trim();
        if (!token) { finish('合鍵が入力されなかったので中止しました。', false); return; }
      }
    }
    const t0 = Date.now();
    const raw = SITE === 'wiki' ? await grabWiki() : await grabMorimori();
    // JANごとに高い方を残す
    const map = new Map();
    raw.forEach(it => { const c = map.get(it.jan); if (!c || it.price > c.price) map.set(it.jan, it); });
    const items = [...map.values()];
    const secs = Math.round((Date.now() - t0) / 1000);
    if (failed > 10) {
      finish(`取得できなかったページが ${failed} 件ありました。サイトの制限が続いているため保存していません。30分ほどおいてもう一度押してください。`, false);
      return;
    }
    if (items.length < MIN_ITEMS) {
      finish(`取得できたのが ${items.length}件だけでした。サイトの作りが変わった可能性があるため保存していません。`, false);
      return;
    }
    const jst = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16) + '+09:00';
    const json = JSON.stringify({ updated: jst, items });
    if (DRY) {
      window.__ktsResult = { count: items.length, secs, bytes: json.length, sample: items.slice(0, 3) };
      finish(`テスト完了：${items.length.toLocaleString()}件（${secs}秒）。保存はしていません。`, true);
      return;
    }
    show(`${items.length.toLocaleString()}件を取得しました。GitHubに保存中…`, 92);
    try {
      await upload(json, token);
    } catch (e) {
      if (e.auth) setToken('');
      throw e;
    }
    setToken(token);
    show('保存しました。Yahoo照合を起動中…', 97);
    const started = await startYahoo(token);
    finish(`完了：${LABEL} ${items.length.toLocaleString()}件を保存しました（${Math.ceil(secs / 60)}分）。\n` +
      (started ? 'Yahoo照合を開始しました。30〜60分ほどで一覧に反映されます。'
        : 'Yahoo照合の自動起動はできませんでした（合鍵に Actions 権限がありません）。次の定期更新で反映されます。'), true);
  } catch (e) {
    finish('エラー：' + (e && e.message || e), false);
  }
})();
