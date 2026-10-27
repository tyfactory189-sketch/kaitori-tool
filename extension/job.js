// 買取差益チェッカー 自動取得：取得ジョブ本体（オフスクリーン文書で動く。DOMParser が使える）
// 1. 買取wiki の全商品（kadenkaitori.tokyo/search/N）
// 2. 買取wiki 専用サイト（iPad・iPhone・PC 等）で「容量・色を選ぶ商品」の仕様ごとの価格
// 3. 森森買取の全商品（ゆっくり取得）
// 4. GitHub に保存し、Yahoo照合（Actions）を起動

const KTS = (() => {
  const parser = new DOMParser();
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const num = s => parseInt(String(s).replace(/[^\d]/g, ''), 10);
  const text = el => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  const jstNow = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16) + '+09:00';

  let progress = () => {};
  const setProgress = fn => { progress = fn; };

  // 制限（403/429）や通信エラーは待って再試行。取れなければ null
  async function getHtml(url, { waits = [5, 30, 60, 120], init } = {}) {
    for (let i = 0; i <= waits.length; i++) {
      try {
        const r = await fetch(url, { credentials: 'include', ...(init || {}) });
        if (r.ok) return await r.text();
        if (r.status === 404) return null;
      } catch (e) { /* 再試行 */ }
      if (i < waits.length) await sleep(waits[i] * 1000);
    }
    return null;
  }
  const getDoc = async (url, opt) => { const h = await getHtml(url, opt); return h ? parser.parseFromString(h, 'text/html') : null; };

  async function pool(urls, conc, gap, fn, onEach, stopWhen) {
    let i = 0, done = 0;
    const worker = async () => {
      while (i < urls.length && !(stopWhen && stopWhen())) {
        const u = urls[i++];
        await fn(u);
        onEach(++done);
        await sleep(gap);
      }
    };
    await Promise.all(Array.from({ length: conc }, worker));
  }

  // ---------- 買取wiki 一覧 ----------
  const WIKI = 'https://kadenkaitori.tokyo';
  function parseWiki(d, items) {
    d.querySelectorAll('.pro_list').forEach(b => {
      const t = text(b);
      const jan = (t.match(/JAN[：:]\s*(\d{8,14})/) || [])[1];
      const price = (t.match(/買取価格[：:]\s*([\d,]+)\s*円/) || [])[1];
      if (!jan || !price) return;
      const name = text(b.querySelector('.sub-pro-name')).replace(/\s*\d{13}\s*$/, '');
      const a = b.querySelector('a[href]');
      const url = a ? new URL(a.getAttribute('href'), WIKI).href : WIKI + '/';
      items.push({ jan, name, price: num(price), url, note: /購入証明/.test(t) ? '購入証明必要' : '' });
    });
  }
  async function grabWiki() {
    const items = [];
    let failed = 0;
    const first = await getDoc(WIKI + '/search/1');
    if (!first) throw new Error('買取wikiの1ページ目を開けませんでした');
    const count = num((text(first.body).match(/([\d,]+)\s*件該当/) || [])[1] || 0);
    const per = first.querySelectorAll('.pro_list').length || 44;
    const pages = Math.ceil(count / per);
    parseWiki(first, items);
    const urls = []; for (let p = 2; p <= pages; p++) urls.push(WIKI + '/search/' + p);
    await pool(urls, 3, 250, async u => { const d = await getDoc(u); d ? parseWiki(d, items) : failed++; },
      n => progress(`買取wiki ${n + 1}/${pages}ページ（${items.length.toLocaleString()}件）`, (n + 1) / pages * 25),
      () => failed > 10);
    if (failed > 10) throw new Error(`買取wikiで取得できないページが続きました（${failed}件）`);
    return dedupe(items);
  }
  function dedupe(items) {
    const m = new Map();
    items.forEach(it => { const c = m.get(it.jan); if (!c || it.price > c.price) m.set(it.jan, it); });
    return [...m.values()];
  }

  // ---------- 買取wiki 専用サイトの容量・色ごとの価格 ----------
  // run.py の is_multi_spec と同じ条件
  const MULTI_SITES = ['iphonekaitori.tokyo', 'ipadkaitori.jp', 'pckaitori.tokyo', 'gamekaitori.jp'];
  const RE_FAMILY = /iPad|iPhone|MacBook|iMac|Mac ?mini|Mac ?Studio|Mac ?Pro|Pixel ?\d|Galaxy ?[ASZ]\d|Surface|Steam ?Deck/;
  const RE_CAP = /\d+\s*(GB|TB|G)\b|\d+G\+\d+G|\d+GB?\/\d+/i;
  const RE_MODEL = /\b[A-Z0-9]{4,6}\d?[A-Z]{0,2}\/A\b/;
  const isCandidate = it => MULTI_SITES.some(d => it.url.includes(d)) && RE_FAMILY.test(it.name) && !RE_CAP.test(it.name) && !RE_MODEL.test(it.name);
  // 選択肢グループ名 → get_prices のパラメータ（item_a 等）
  const GROUP_PARAM = { career: 'a', color: 'c', gb: 'g' };
  const LETTERS = ['a', 'n', 'c', 'g', 'o', 'k'];

  // 商品ページから goods_id と選択肢を読む
  function parseOptions(d) {
    const gid = d.querySelector('#goods_id, input[name=goods_id]');
    const groups = {};
    d.querySelectorAll('input[type=radio]').forEach(r => {
      if (!r.name || r.name === 'rank') return;
      const lab = r.id ? d.querySelector(`label[for="${r.id}"]`) : null;
      (groups[r.name] = groups[r.name] || []).push({ id: r.dataset.value || r.value, label: text(lab) });
    });
    return { goodsId: gid ? gid.value : '', groups };
  }
  function combos(groups) {
    let out = [{}];
    for (const [name, opts] of Object.entries(groups)) {
      const next = [];
      for (const c of out) for (const o of opts) next.push({ ...c, [name]: o });
      out = next;
    }
    return out;
  }
  async function getPrice(origin, goodsId, combo) {
    const params = Object.fromEntries(LETTERS.map(l => ['item_' + l, 'true']));
    for (const [name, o] of Object.entries(combo)) params['item_' + (GROUP_PARAM[name] || name[0])] = o.id;
    params.goods_id = goodsId;
    const h = await getHtml(origin + '/home/tool/get_prices', {
      waits: [5, 30],
      init: { method: 'POST', body: new URLSearchParams(params), headers: { 'X-Requested-With': 'XMLHttpRequest' } },
    });
    if (!h) return null;
    try { return num(JSON.parse(h).data.n.price) || null; } catch (e) { return null; }
  }
  async function grabVariants(wikiItems, prev) {
    const goods = {};
    const now = Date.now();
    const prevGoods = (prev && prev.goods) || {};
    // 前回「選択肢なし」と分かった商品は7日間は調べ直さない
    const targets = wikiItems.filter(it => {
      if (!isCandidate(it) && !(prevGoods[it.jan] && !prevGoods[it.jan].single)) return false;
      const p = prevGoods[it.jan];
      if (p && p.single && now - Date.parse(p.checked) < 7 * 864e5) { goods[it.jan] = p; return false; }
      return true;
    });
    let done = 0, withVariants = 0;
    for (const it of targets) {
      progress(`専用サイトの容量・色ごとの価格 ${++done}/${targets.length}`, 25 + done / Math.max(1, targets.length) * 15);
      const d = await getDoc(it.url, { waits: [5, 30] });
      await sleep(400);
      if (!d) continue;
      const { goodsId, groups } = parseOptions(d);
      const unsupported = Object.keys(groups).filter(n => !GROUP_PARAM[n] && !LETTERS.includes(n[0]));
      if (!goodsId || !Object.keys(groups).length) { goods[it.jan] = { url: it.url, name: it.name, single: true, checked: jstNow() }; continue; }
      if (unsupported.length) { goods[it.jan] = { url: it.url, name: it.name, unsupported, checked: jstNow() }; continue; }
      const origin = new URL(it.url).origin;
      const variants = [];
      for (const c of combos(groups).slice(0, 48)) {
        const p = await getPrice(origin, goodsId, c);
        // 選択肢の名前は run.py で商品名と突き合わせるため color / gb / その他 の順で残す
        const sel = {};
        for (const [name, o] of Object.entries(c)) sel[name] = o.label;
        if (p) variants.push({ sel, p });
        await sleep(400);
      }
      goods[it.jan] = { url: it.url, name: it.name, goodsId, variants, checked: jstNow() };
      if (variants.length) withVariants++;
    }
    return { updated: jstNow(), goods, stats: { checked: targets.length, withVariants } };
  }

  // ---------- 森森買取 ----------
  const MORI = 'https://www.morimori-kaitori.jp';
  function parseMori(d, items) {
    d.querySelectorAll('.mm1551-prow').forEach(r => {
      const meta = text(r.querySelector('.mm1551-prow__meta'));
      const jan = (meta.match(/JAN[：:]\s*(\d{8,14})/) || [])[1];
      if (!jan || /中古/.test(meta)) return;
      const price = (text(r.querySelector('.mm1551-prow__cur')).match(/([\d,]+)\s*円/) || [])[1];
      if (!price) return;
      const a = r.querySelector('.mm1551-prow__name a[href]') || r.querySelector('a[href*="/product/"]');
      items.push({ jan, name: text(r.querySelector('.mm1551-prow__name')), price: num(price), url: a ? new URL(a.getAttribute('href'), MORI).href : MORI + '/', note: '' });
    });
  }
  async function grabMorimori() {
    const items = [];
    let failed = 0;
    const home = await getDoc(MORI + '/');
    if (!home) throw new Error('森森買取のトップページを開けませんでした');
    const tops = [...new Set([...home.querySelectorAll('a[href]')].map(a => new URL(a.getAttribute('href'), MORI).pathname).filter(p => /^\/category\/\d{2}$/.test(p)))];
    const urls = [];
    for (const t of tops) {
      const d = await getDoc(MORI + t);
      await sleep(1500);
      if (!d) { failed++; continue; }
      parseMori(d, items);
      const count = num((text(d.body).match(/該当\s*([\d,]+)\s*件/) || [])[1] || 0);
      const per = d.querySelectorAll('.mm1551-prow').length || 50;
      for (let p = 2; p <= Math.ceil(count / per); p++) urls.push(MORI + t + '?page=' + p);
    }
    await pool(urls, 1, 1500, async u => { const d = await getDoc(u); d ? parseMori(d, items) : failed++; },
      n => progress(`森森買取 ${n}/${urls.length}ページ（${items.length.toLocaleString()}件）`, 40 + n / Math.max(1, urls.length) * 55),
      () => failed > 10);
    if (failed > 10) throw new Error(`森森買取で取得できないページが続きました（${failed}件）。制限中の可能性があります`);
    return dedupe(items);
  }

  // ---------- Yahoo!ショッピング（ログイン中のあなたの条件でのポイント・価格） ----------
  // 商品ページの埋め込みデータ（__NEXT_DATA__）には、ログイン中の会員（プレミアム・ランク・PayPay条件など）に
  // 合わせた付与ポイントの内訳が入っている。付与上限に達したキャンペーンは実際には付かないので差し引く。
  function parseYahooItem(html, jan, names = []) {
    const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
    if (!m) return null;
    let pp;
    try { pp = JSON.parse(m[1]).props.pageProps; } catch (e) { return null; }
    const item = pp.item || {}, pt = pp.point || {};
    const base = +item.applicablePrice || 0;
    if (!base) return null;
    // 仕様選択（JANに一致する選択肢の価格、無ければ最高値）
    const prices = []; let jp = null;
    const t1 = item.stockTableOneAxis, t2 = item.stockTableTwoAxis;
    const choices = [];
    if (t1) ((t1.firstOption || {}).choiceList || []).forEach(c => choices.push(c));
    if (t2) ((t2.firstOption || {}).choiceList || []).forEach(f => (((f.secondOption || {}).choiceList) || []).forEach(c => choices.push({ ...c, choiceName: (f.choiceName || '') + ' ' + (c.choiceName || '') })));
    choices.forEach(c => { const p = c.price ? +c.price : base; prices.push(p); const sku = String(c.skuId || ''); if (sku && (sku === jan || sku.endsWith(jan))) jp = p; });
    // 管理番号がJANでない場合は、選択肢の名前（ブラック／256GB 等）が商品名に含まれるもので特定
    const nz = x => String(x || '').normalize('NFKC').replace(/\s+/g, '').toLowerCase();
    let byName = null;
    if (jp == null && choices.length && names.length) {
      const txt = nz(names.join(' '));
      const hit = choices.filter(c => String(c.choiceName || '').split(/\s+/).filter(Boolean).every(w => txt.includes(nz(w))));
      if (hit.length === 1) { byName = hit[0]; jp = byName.price ? +byName.price : base; }
    }
    let price = jp != null ? jp : (prices.length ? Math.max(...prices) : base);
    let add = 0, optNg = false;
    // 型番（英字＋数字5文字以上）で「種類を選べる」選択肢からこのJANのものを特定
    const mt = new Set((String(names.join(' ')).normalize('NFKC').match(/[A-Za-z0-9][A-Za-z0-9\-]{3,}/g) || []).map(t => t.replace(/-/g, '').toUpperCase()).filter(n => n.length >= 5 && /[A-Z]/.test(n) && /\d/.test(n) && !/\d(GB|TB|MM|ML|W|V|MAH)$/.test(n)));
    (item.selectOptionList || []).forEach(o => {
      const chs = o.choiceList || [];
      const mine = mt.size ? chs.filter(c => { const cn = String(c.name || '').normalize('NFKC').toUpperCase().replace(/[\s-]/g, ''); return [...mt].some(t => cn.includes(t)); }) : [];
      if (mine.length === 1) { if (mine[0].isSelectable === false) optNg = true; add += +mine[0].charge || 0; return; }
      const ch = chs.filter(c => c.isSelectable !== false).map(c => +c.charge || 0); if (ch.length && Math.min(...ch) > 0) add += Math.min(...ch);
    });
    price += add;
    // ポイント（表示は基本価格に対する値なので、価格が変わったら比例させる）
    const parts = (pt.currentCampaignList || []).flatMap(c => c.partsCampaignList || []);
    const total = +pt.totalPoint || 0;
    // isReachedLimit の項目は、表示ポイント自体がすでに上限まで減らされた値（残り枠ぶん）なのでそのまま合計を使う
    const ratio = base ? price / base : 1;
    // 在庫・販売状態（中古・予約・販売期間外・在庫なしは対象外にする）
    const st = item.stock || {};
    let ng;
    if (item.isUsed) ng = '中古';
    else if (item.isPreOrder || (item.preOrderType && item.preOrderType !== 'None')) ng = '予約商品';
    else if (item.isOnSale === false || item.isBeforeSalePeriod || item.isAfterSalePeriod) ng = '販売期間外';
    else if (st.isAvailable === false) ng = '在庫なし';
    const hit = byName || choices.find(c => { const sku = String(c.skuId || ''); return sku && (sku === jan || sku.endsWith(jan)); });
    if (!ng && hit && hit.stock && hit.stock.isAvailable === false) ng = '在庫なし';
    if (!ng && optNg) ng = '在庫なし';
    // セット品をばらした単品・外箱なし（商品説明で判定）
    if (!ng && /バラ売り|ばら売り|(?<!す)ばらし|バラし|バラシ|分けて(?:単体|単品|販売)|(?:左|右)または(?:右|左)|左右どちらか|片方のみ|外箱(?:は|が)?(?:付属(?:でき|しませ|なし|無し)|なし|無し|ありません)|本体同梱品|同梱品(?:を|の)(?:ばら|バラ|単品)|セット(?:品)?(?:から|を)(?:取り出|ばら|バラ|分解)/.test(String((item.caption || '') + ' ' + (item.information || '')).replace(/<[^>]+>/g, ''))) ng = 'ばら売り';
    // 送料（ログイン中の住所＝お届け先の都道府県あて）と条件付き無料の金額
    const pg = pp.postage || {};
    let sf, sfc, pref;
    if (pg.isPostageFree) sf = 0;
    else if (pg.fee != null) {
      sf = +pg.fee || 0; pref = pg.prefecture || undefined;
      const cm = String(pg.conditionFreeText || '').normalize('NFKC').match(/([\d,]+)\s*円以上/);
      if (cm && sf) sfc = +cm[1].replace(/,/g, '');
    }
    return {
      ng, sf, sfc, pref,
      p: price, base, add: add || undefined,
      pv: jp == null && prices.length && Math.min(...prices) !== Math.max(...prices) ? [Math.min(...prices), Math.max(...prices)] : undefined,
      pt: Math.round(total * ratio),
      rate: +pt.totalPointRatio || 0,
      capped: parts.filter(x => x.isReachedLimit).map(x => x.title.slice(0, 30)),
      at: jstNow(),
    };
  }
  // ログイン状態だけを見る（個人情報は読み取らない・保存しない）
  function loginState(html) {
    const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
    try {
      const u = JSON.parse(m[1]).props.pageProps.user;
      return { login: !!(u && 'isWalletUser' in u), premium: !!(u && u.isPremiumUser) };
    } catch (e) { return { login: false, premium: false }; }
  }

  // 一覧データから「利益が出そうな出品」を選ぶ（還元を多めの12%と見て、損が3,000円以内）
  function pickCandidates(data, watch, limit) {
    const out = [];
    for (const it of data.items || []) {
      const buys = Object.values(it.buys || {}).filter(b => !b.m).map(b => b.p);
      const best = buys.length ? Math.max(...buys) : 0;
      const watched = watch.has(it.jan);
      (it.offers || []).slice(0, 2).forEach((o, i) => {
        if (!/store\.shopping\.yahoo\.co\.jp/.test(o.u || '')) return;
        const eff = o.p - o.p / 1.1 * 0.12 - (o.pt || 0);
        const score = best - eff;
        if (watched || (best && score > -3000)) out.push({ jan: it.jan, name: it.name, url: o.u.split('?')[0], score: watched ? 1e9 - i : score });
      });
    }
    out.sort((a, b) => b.score - a.score);
    const seen = new Set();
    return out.filter(c => !seen.has(c.url) && seen.add(c.url)).slice(0, limit);
  }

  async function grabYahooUser(g, pagesUrl, limit = 400, pass = '') {
    const er = await fetch(pagesUrl + 'data.enc.json', { cache: 'no-store' }).catch(() => null);
    let data;
    if (er && er.ok) {
      if (!pass) throw new Error('サイトが暗号化されていますが、拡張機能にサイトのパスワードが未設定です');
      try { data = await decryptJson(await er.json(), pass); } catch (e) { throw new Error('サイトのパスワードが違います（設定画面で入れ直してください）'); }
    } else data = await fetch(pagesUrl + 'data.json', { cache: 'no-store' }).then(r => r.json());
    const wl = await g.readJson('docs/watchlist.json').catch(() => null);
    const watch = new Set(((wl && wl.items) || []).map(w => String(w.jan)));
    const cands = pickCandidates(data, watch, limit);
    const offers = {};
    let done = 0, ok = 0, loginChecked = false, premiumWarn = false;
    for (const c of cands) {
      progress(`Yahoo（ログイン条件のポイント）${++done}/${cands.length}`, done / cands.length * 100);
      const h = await getHtml(c.url, { waits: [5, 30] });
      await sleep(800);
      if (!h) continue;
      if (!loginChecked) {
        loginChecked = true;
        const st = loginState(h);
        if (!st.login) throw new Error('この Chrome で Yahoo! JAPAN にログインしていないため、会員条件のポイントを取得できません');
        if (!st.premium) premiumWarn = true;
      }
      const r = parseYahooItem(h, c.jan, [c.name]);
      if (r) { offers[c.url] = r; ok++; }
    }
    return { updated: jstNow(), offers, stats: { candidates: cands.length, ok, premium: !premiumWarn } };
  }

  // ---------- GitHub ----------
  function gh(settings) {
    const api = (path, opt = {}) => fetch('https://api.github.com/repos/' + settings.repo + path, {
      ...opt,
      headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + settings.token, 'X-GitHub-Api-Version': '2022-11-28', ...(opt.body ? { 'Content-Type': 'application/json' } : {}) },
    });
    const b64 = s => new Promise(res => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(',')[1]); fr.readAsDataURL(new Blob([s])); });
    return {
      async readJson(path) {
        const r = await api('/contents/' + path + '?ref=main');
        if (!r.ok) return null;
        const j = await r.json();
        if (j.content) return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(j.content.replace(/\n/g, '')), c => c.charCodeAt(0))));
        if (j.download_url) return fetch(j.download_url, { cache: 'no-store' }).then(x => x.json()).catch(() => null); // 1MB超
        return null;
      },
      async write(path, obj, message) {
        const content = await b64(JSON.stringify(obj));
        for (let attempt = 0; attempt < 3; attempt++) {
          const cur = await api('/contents/' + path + '?ref=main');
          if (cur.status === 401) throw new Error('合鍵（トークン）が無効です。設定画面で入れ直してください');
          const sha = cur.ok ? (await cur.json()).sha : undefined;
          const r = await api('/contents/' + path, { method: 'PUT', body: JSON.stringify({ message, content, sha, branch: 'main' }) });
          if (r.ok) return;
          if (r.status === 401 || r.status === 403 || r.status === 404) throw new Error(`保存する権限がありません（HTTP ${r.status}）。合鍵の権限とリポジトリ名を確認してください`);
          await sleep(3000);
        }
        throw new Error(path + ' の保存に失敗しました');
      },
      async startYahoo() {
        const r = await api('/actions/workflows/update.yml/dispatches', { method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { skip_buyback: true } }) });
        return r.status === 204;
      },
    };
  }


  // 残高などの個人データは、パスワードで暗号化してから保存する（公開ページでも中身は読めない）
  const b64e = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
  async function deriveKey(pass, salt) {
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: 200000, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  }
  async function decryptJson(enc, pass) {
    const d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
    const key = await deriveKey(pass, d(enc.salt));
    return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: d(enc.iv) }, key, d(enc.ct))));
  }
  async function encryptJson(obj, pass) {
    const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKey(pass, salt);
    const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(obj)));
    return { v: 1, kdf: 'PBKDF2-SHA256-200000', alg: 'AES-GCM', salt: b64e(salt), iv: b64e(iv), ct: b64e(ct) };
  }

  // ---------- 残高シート（Googleスプレッドシート） ----------
  function parseCsv(text) {
    const rows = []; let row = [], cur = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
      else if (c === '"') q = true;
      else if (c === ',') { row.push(cur); cur = ''; }
      else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
      else if (c !== '\r') cur += c;
    }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    return rows;
  }
  const colNo = c => String(c).toUpperCase().split('').reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
  function parseBudget(csv, sheet) {
    const n = colNo(sheet.nameCol), a = colNo(sheet.amtCol), first = Math.min(n, a);
    const skip = new Set(String(sheet.skip == null ? 'an3,an4,an5,an6' : sheet.skip).split(/[,、\s]+/).map(x => x.trim().toLowerCase()).filter(Boolean));
    const items = [];
    parseCsv(csv).forEach((r, i) => {
      const name = String(r[n - first] || '').trim();
      const raw = String(r[a - first] || '').normalize('NFKC').replace(/[,円¥\s]/g, '');
      if (!name || !/^-?\d+(\.\d+)?$/.test(raw)) return;
      if (skip.has(name.toLowerCase())) return; // 読み込まない名前
      items.push({ name, amt: Math.round(+raw), row: sheet.startRow + i });
    });
    return items;
  }
  async function grabBudget(sheet) {
    const m = String(sheet.url || '').match(/\/spreadsheets\/d\/([\w-]+)/);
    if (!m) throw new Error('残高シートのURLが正しくありません');
    const gid = (String(sheet.url).match(/[#?&]gid=(\d+)/) || [])[1] || '0';
    const c1 = String.fromCharCode(64 + Math.min(colNo(sheet.nameCol), colNo(sheet.amtCol)));
    const c2 = String.fromCharCode(64 + Math.max(colNo(sheet.nameCol), colNo(sheet.amtCol)));
    const url = `https://docs.google.com/spreadsheets/d/${m[1]}/gviz/tq?tqx=out:csv&gid=${gid}&headers=0&range=${c1}${sheet.startRow}:${c2}${sheet.startRow + 300}`;
    const r = await fetch(url, { credentials: 'include', cache: 'no-store' });
    const t = await r.text();
    if (!r.ok || /^\s*<(!doctype|html)/i.test(t)) throw new Error('シートを開けません（このChromeでシートを見られるGoogleアカウントにログインしてください）');
    return parseBudget(t, sheet);
  }

  // ---------- 全体 ----------
  async function run(settings) {
    const g = gh(settings);
    const sites = settings.sites || {};
    const notes = [];
    let saved = 0;
    const MIN_ITEMS = 1000;
    const sitePass = settings.sitePass || (settings.sheet && settings.sheet.pass) || '';

    if (sites.wiki) {
      try {
        progress('買取wiki を取得中…', 1);
        const items = await grabWiki();
        if (items.length < MIN_ITEMS) throw new Error(`買取wikiが ${items.length}件しか取れませんでした（保存せず）`);
        await g.write('data/buyback_wiki.json', { updated: jstNow(), items }, `買取wiki 買取価格を更新（自動取得 ${items.length}件）`);
        notes.push(`買取wiki ${items.length.toLocaleString()}件`); saved++;
        if (sites.variants) {
          const prev = await g.readJson('data/wiki_variants.json').catch(() => null);
          const v = await grabVariants(items, prev);
          await g.write('data/wiki_variants.json', v, `買取wiki 容量・色ごとの価格を更新（${v.stats.withVariants}商品）`);
          notes.push(`仕様別 ${v.stats.withVariants}商品`); saved++;
        }
      } catch (e) { notes.push('買取wiki 失敗：' + e.message); }
    }
    if (sites.morimori) {
      try {
        progress('森森買取 を取得中…', 40);
        const items = await grabMorimori();
        if (items.length < MIN_ITEMS) throw new Error(`森森買取が ${items.length}件しか取れませんでした（保存せず）`);
        await g.write('data/buyback_morimori.json', { updated: jstNow(), items }, `森森買取 買取価格を更新（自動取得 ${items.length}件）`);
        notes.push(`森森買取 ${items.length.toLocaleString()}件`); saved++;
      } catch (e) { notes.push('森森買取 失敗：' + e.message); }
    }
    if (sites.yahooUser) {
      try {
        progress('Yahoo のポイントを確認中…', 0);
        const [u, r] = settings.repo.split('/');
        const y = await grabYahooUser(g, `https://${u}.github.io/${r}/`, 400, sitePass);
        await g.write('data/yahoo_user.json', y, `Yahoo ログイン条件のポイントを更新（${y.stats.ok}件）`);
        notes.push(`Yahooポイント ${y.stats.ok}件` + (y.stats.premium ? '' : '（LYPプレミアム会員としてログインしていません）')); saved++;
      } catch (e) { notes.push('Yahooポイント 失敗：' + e.message); }
    }
    if (sites.budget !== false && settings.sheet && settings.sheet.url) {
      try {
        if (!sitePass) throw new Error('サイトのパスワードが未設定です（設定画面で入力してください）');
        progress('残高シートを読み込み中…', 99);
        const items = await grabBudget(settings.sheet);
        if (!items.length) throw new Error('金額の行が見つかりませんでした');
        await g.write('docs/budgets.enc.json', await encryptJson({ updated: jstNow(), items }, sitePass), `残高シートを更新（暗号化・${items.length}件）`);
        notes.push(`残高 ${items.length}件`);
      } catch (e) { notes.push('残高シート 失敗：' + e.message); }
    }
    if (saved && settings.startYahoo) {
      progress('Yahoo照合を起動中…', 98);
      notes.push((await g.startYahoo().catch(() => false)) ? 'Yahoo照合を開始' : 'Yahoo照合は次の定期実行で');
    }
    return { ok: saved > 0 && !notes.some(n => n.includes('失敗')), summary: notes.join(' ／ ') || '取得対象がありません' };
  }

  return { run, parseCsv, parseBudget, encryptJson, decryptJson, setProgress, parseWiki, parseMori, parseOptions, combos, isCandidate, getPrice, grabVariants, parseYahooItem, pickCandidates, loginState };
})();

// オフスクリーン文書として読み込まれたときだけ、バックグラウンドからの指示を待つ
if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener(msg => {
    if (msg.target !== 'offscreen' || msg.cmd !== 'run') return;
    KTS.setProgress((text, pct) => chrome.runtime.sendMessage({ cmd: 'progress', text, pct }));
    KTS.run(msg.settings)
      .then(r => chrome.runtime.sendMessage({ cmd: 'done', ...r }))
      .catch(e => chrome.runtime.sendMessage({ cmd: 'done', ok: false, summary: 'エラー：' + (e && e.message || e) }));
  });
}
