// 買取差益チェッカー 自動取得：バックグラウンド（予定の管理と、取得ジョブの起動・状態保存）
const DEFAULT_SETTINGS = {
  token: '',
  repo: 'tyfactory189-sketch/kaitori-tool',
  times: ['11:00', '14:00', '20:00'],
  sites: { wiki: true, variants: true, morimori: true, yahooUser: true, budget: true, sedori: true, stores: true, x: true },
  startYahoo: true,
  xAccounts: ['momonnusan', 'MATCHANFIRE'],
  sedori: { url: 'https://docs.google.com/spreadsheets/d/1IPd1p5gbUS98Qt017o2cVC6a-RFAYqDYB_UI8zpCFzU/edit', tab: '商品管理' },
  sheet: { url: 'https://docs.google.com/spreadsheets/d/14RAmHsswRyA3yekaeUlINFWQ7Mt8jR1GPT0jfBn1Mks/edit?gid=0#gid=0', nameCol: 'B', amtCol: 'L', startRow: 4, skip: 'an3,an4,an5,an6' },
};
const STALE_MS = 3 * 60 * 60e3; // 3時間以上「実行中」のままなら止まったとみなす

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}), sites: { ...DEFAULT_SETTINGS.sites, ...((settings || {}).sites || {}) }, sheet: { ...DEFAULT_SETTINGS.sheet, ...((settings || {}).sheet || {}) }, sedori: { ...DEFAULT_SETTINGS.sedori, ...((settings || {}).sedori || {}) } };
}
async function getStatus() {
  const { status } = await chrome.storage.local.get('status');
  return status || { running: false, history: [] };
}
async function setStatus(patch) {
  const s = { ...(await getStatus()), ...patch };
  await chrome.storage.local.set({ status: s });
  return s;
}

// ---------- 予定 ----------
function nextTime(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  const d = new Date();
  d.setHours(h, m || 0, 0, 0);
  if (d.getTime() <= Date.now() + 30e3) d.setDate(d.getDate() + 1);
  return d.getTime();
}
async function schedule() {
  const { times } = await getSettings();
  const all = await chrome.alarms.getAll();
  await Promise.all(all.filter(a => a.name.startsWith('run-')).map(a => chrome.alarms.clear(a.name)));
  for (const t of times) {
    if (!/^\d{1,2}:\d{2}$/.test(t)) continue;
    await chrome.alarms.create('run-' + t, { when: nextTime(t), periodInMinutes: 24 * 60 });
  }
}
chrome.runtime.onInstalled.addListener(async () => { await schedule(); report({ event: 'インストール・更新' }); });
chrome.runtime.onStartup.addListener(async () => {
  await schedule();
  const st = await getStatus();
  if (st.running) await setStatus({ running: false, text: '前回の実行は Chrome の終了で中断されました' });
  await report({ event: 'Chrome起動' });
});
chrome.storage.onChanged.addListener((ch, area) => { if (area === 'local' && ch.settings) schedule(); });
chrome.alarms.onAlarm.addListener(async a => {
  if (!a.name.startsWith('run-')) return;
  const st = await getStatus();
  if (st.running && Date.now() - (st.startedAt || 0) >= STALE_MS) {
    await setStatus({ running: false, text: '前回の実行が途中で止まっていました（' + (st.text || '') + '）' });
    await report({ event: '前回の実行が途中で停止' });
  }
  const r = await startJob('定時（' + a.name.slice(4) + '）');
  if (!r.ok) report({ event: '定時実行できず：' + r.message });
});

// ---------- 状態をGitHubに報告（ツール画面とサポート側から確認できるように） ----------
async function report(extra = {}) {
  try {
    const settings = await getSettings();
    if (!settings.token) return;
    const st = await getStatus();
    const alarms = (await chrome.alarms.getAll()).filter(a => a.name.startsWith('run-'));
    const body = {
      version: chrome.runtime.getManifest().version,
      reportedAt: new Date().toISOString(),
      running: !!st.running, text: st.text || '', trigger: st.trigger || '',
      startedAt: st.startedAt ? new Date(st.startedAt).toISOString() : null,
      last: st.last ? { ...st.last, at: new Date(st.last.at).toISOString() } : null,
      history: (st.history || []).slice(0, 10).map(h => ({ ...h, at: new Date(h.at).toISOString() })),
      times: settings.times, sites: settings.sites,
      next: alarms.length ? new Date(Math.min(...alarms.map(a => a.scheduledTime))).toISOString() : null,
      ...extra,
    };
    const api = (path, opt = {}) => fetch('https://api.github.com/repos/' + settings.repo + path, { cache: 'no-store',
      ...opt, headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + settings.token, 'X-GitHub-Api-Version': '2022-11-28' },
    });
    const path = '/contents/docs/extension_status.json';
    const bytes = new TextEncoder().encode(JSON.stringify(body, null, 1));
    let bin = ''; bytes.forEach(c => { bin += String.fromCharCode(c); });
    for (let i = 0; i < 3; i++) {
      const cur = await api(path + '?ref=main');
      const sha = cur.ok ? (await cur.json()).sha : undefined;
      const r = await api(path, { method: 'PUT', body: JSON.stringify({ message: '自動取得の状態: ' + (extra.event || body.text).slice(0, 60), content: btoa(bin), sha, branch: 'main' }) });
      if (r.ok || r.status === 401 || r.status === 403) return;
      await new Promise(res => setTimeout(res, 3000));
    }
  } catch (e) { /* 報告の失敗は無視（取得そのものには影響させない） */ }
}

// ---------- X（旧Twitter）の参考アカウントの投稿を集める ----------
// 実際のタブでプロフィールを開き、表示された投稿の文章を読む（このPCのChromeでXにログインしておく）
async function ghWrite(path, obj, message) {
  const settings = await getSettings();
  const api = (p, opt = {}) => fetch('https://api.github.com/repos/' + settings.repo + p, { cache: 'no-store', ...opt,
    headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + settings.token, 'X-GitHub-Api-Version': '2022-11-28' } });
  const bytes = new TextEncoder().encode(JSON.stringify(obj, null, 1));
  let bin = ''; bytes.forEach(c => { bin += String.fromCharCode(c); });
  for (let i = 0; i < 4; i++) {
    const cur = await api('/contents/' + path + '?ref=main&t=' + Date.now());
    const sha = cur.ok ? (await cur.json()).sha : undefined;
    const r = await api('/contents/' + path, { method: 'PUT', body: JSON.stringify({ message, content: btoa(bin), sha, branch: 'main' }) });
    if (r.ok) return true;
    await new Promise(res => setTimeout(res, 2000 * (i + 1)));
  }
  return false;
}
async function ghRead(path) {
  const settings = await getSettings();
  const r = await fetch('https://api.github.com/repos/' + settings.repo + '/contents/' + path + '?ref=main&t=' + Date.now(), { cache: 'no-store',
    headers: { Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + settings.token } });
  if (!r.ok) return null;
  const j = await r.json();
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(j.content.replace(/\n/g, '')), c => c.charCodeAt(0))));
}
// 別ウィンドウ（前面に出さない）で開く：裏のタブだとXが続きを読み込まないため
async function openWorkTab(url) {
  try {
    const w = await chrome.windows.create({ url, focused: false, width: 1200, height: 900, type: 'normal' });
    return { id: w.tabs[0].id, windowId: w.id };
  } catch (e) {
    const t = await chrome.tabs.create({ url, active: false });
    return { id: t.id };
  }
}
async function closeWorkTab(t) {
  if (!t) return;
  try { if (t.windowId) await chrome.windows.remove(t.windowId); else await chrome.tabs.remove(t.id); } catch (e) { /* noop */ }
}
function scrapeTimeline(scrolls) { // ページの中で動く（chrome.scripting で注入）
  return (async () => {
    const seen = new Map();
    const grab = () => document.querySelectorAll('article').forEach(a => {
      const link = a.querySelector('a[href*="/status/"] time') ? a.querySelector('a[href*="/status/"] time').closest('a') : null;
      if (!link) return;
      const url = link.href.split('?')[0];
      if (seen.has(url)) return;
      const text = [...a.querySelectorAll('[data-testid="tweetText"]')].map(e => e.innerText).join('\n');
      const cards = [...a.querySelectorAll('[data-testid="card.wrapper"], a[href*="t.co"]')].map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean);
      const alts = [...a.querySelectorAll('img[alt]')].map(i => i.alt).filter(t => t && t.length > 4 && !/^Image$|^画像$/.test(t));
      const au = a.querySelector('[data-testid="User-Name"] a[href^="/"]');
      seen.set(url, { url, author: au ? au.getAttribute('href').replace(/^\//, '').split('/')[0] : '', time: a.querySelector('time').getAttribute('datetime'), text, cards: cards.slice(0, 4), alts: alts.slice(0, 4),
        pinned: /固定|Pinned/.test(a.innerText.slice(0, 40)) });
    });
    let idle = 0;
    for (let i = 0; i < scrolls && idle < 6; i++) {
      const before = seen.size; grab(); window.scrollBy(0, 2500);
      await new Promise(r => setTimeout(r, 1800));
      idle = seen.size === before ? idle + 1 : 0; // 新しい投稿が出なくなったら（いちばん古いところまで来たら）終わり
    }
    grab();
    return { posts: [...seen.values()], login: !document.querySelector('a[href="/login"]') };
  })();
}
async function grabX() {
  const settings = await getSettings();
  // 参考アカウントは「設定画面の欄」と「GitHubの data/x_config.json（ツール画面から追加できる）」を合わせたもの
  const cfg = (await ghRead('data/x_config.json').catch(() => null)) || {};
  // チェッカー画面で管理している一覧（data/x_config.json）があればそれを使う（画面で外したアカウントは読まない）
  const base = Array.isArray(cfg.accounts) && cfg.accounts.length ? cfg.accounts : (settings.xAccounts || []);
  const accts = [...new Set(base.map(a => String(a).replace(/^@/, '').trim()).filter(Boolean))];
  if (!accts.length) return null;
  const prev = (await ghRead('data/x_posts.json').catch(() => null)) || { posts: [] };
  const byUrl = new Map((prev.posts || []).map(p => [p.url, p]));
  const stats = {};
  for (const acct of accts) {
    let tab;
    try {
      tab = await openWorkTab('https://x.com/' + acct);
      await new Promise(r => setTimeout(r, 9000));
      // 初回（まだ投稿をあまり持っていないアカウント）は、過去の投稿までさかのぼって読む
      const have = [...byUrl.values()].filter(p => p.acct === acct).length;
      const deep = have < 100;
      const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: scrapeTimeline, args: [deep ? (settings.xDeepScrolls || 150) : (settings.xScrolls || 8)] });
      const out = (res && res.result) || { posts: [] };
      out.posts.forEach(p => byUrl.set(p.url, { ...p, acct }));
      stats[acct] = out.login ? (deep ? '初回 ' : '') + out.posts.length + '件' : 'ログインが必要';
    } catch (e) { stats[acct] = 'エラー: ' + String(e.message || e).slice(0, 80); }
    finally { await closeWorkTab(tab); }
  }
  // アカウントごとに新しい順2000件まで残す（過去の投稿のリスト用）
  const posts = [];
  for (const acct of new Set([...byUrl.values()].map(p => p.acct))) {
    posts.push(...[...byUrl.values()].filter(p => p.acct === acct).sort((a, b) => String(b.time).localeCompare(String(a.time))).slice(0, 2000));
  }
  await ghWrite('data/x_posts.json', { updated: new Date().toISOString(), stats, posts }, 'Xの参考アカウントの投稿を更新');
  // 新しいアカウント探し：X検索の「最新」を読み、投稿者ごとに集める（1日1回）
  const last = (await chrome.storage.local.get('xSearchAt')).xSearchAt || 0;
  if ((cfg.queries || []).length && Date.now() - last > 20 * 3600e3) {
    const found = [];
    for (const q of cfg.queries.slice(0, 10)) {
      let tab;
      try {
        tab = await openWorkTab('https://x.com/search?f=live&q=' + encodeURIComponent(q));
        await new Promise(r => setTimeout(r, 9000));
        const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: scrapeTimeline, args: [12] });
        ((res && res.result && res.result.posts) || []).forEach(p => found.push({ ...p, q }));
      } catch (e) { /* 次の検索へ */ }
      finally { await closeWorkTab(tab); }
    }
    await ghWrite('data/x_search.json', { updated: new Date().toISOString(), posts: found }, 'Xの検索結果（アカウント探し）を更新');
    await chrome.storage.local.set({ xSearchAt: Date.now() });
    stats._search = found.length;
  }
  return stats;
}

// ---------- 家電量販店：実際のタブを開き、そのページの中で検索する（ボット対策の確認を通ったまま読める） ----------
function storeLookup(st, list, delay) { // ページの中で動く
  return (async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const toNum = t => parseInt(String(t || '').replace(/[^\d]/g, ''), 10) || 0;
    const SOLD = /在庫なし|売り切れ|完売|販売終了|販売を終了|取り扱い終了|入荷待ち/;
    const sj = async u => { const r = await fetch(u, { cache: 'no-store' }); if (r.status === 202 || r.status === 403) throw new Error('blocked ' + r.status); return new TextDecoder('shift_jis').decode(await r.arrayBuffer()); };
    const tx = async u => { const r = await fetch(u, { cache: 'no-store' }); if (r.status === 202 || r.status === 403) throw new Error('blocked ' + r.status); return r.text(); };
    const nz = x => String(x || '').normalize('NFKC').replace(/[\s\-\/]/g, '').toUpperCase();
    const out = {}; let blocked = 0;
    for (const { jan, toks, bicId } of list) {
      try {
        let r = null;
        if (st === 'kojima') {
          const doc = new DOMParser().parseFromString(await tx(`/ec/prod_list.html?keyword=${jan}`), 'text/html');
          const li = [...doc.querySelectorAll('li[mk2pcode]')].find(x => x.getAttribute('mk2pcode') === jan);
          if (li) { const t = li.textContent; const a = li.querySelector('a[href*="prod_detail"]');
            r = { p: toNum(li.getAttribute('mk2price')), pt: toNum((li.querySelector('.point .number') || {}).textContent), ng: SOLD.test(t) ? '在庫なし' : '', n: li.getAttribute('mk2pname') || '', u: location.origin + (a ? a.getAttribute('href') : '') }; }
        } else if (st === 'nojima') {
          const doc = new DOMParser().parseFromString(await tx(`/app/catalog/list/init?searchWord=${jan}`), 'text/html');
          const li = [...doc.querySelectorAll('.commoditylistitem li')].find(x => x.querySelector(`a[href^="/commodity/1/${jan}/"]`));
          if (li) { const t = li.textContent; const pr = li.querySelector('.price');
            r = { p: toNum(pr && pr.firstChild && pr.firstChild.textContent), pt: toNum((li.querySelector('.pointKangen') || {}).textContent), cp: toNum((li.querySelector('.couponlistnebiki') || {}).textContent),
              ng: SOLD.test(t) && !/在庫あり/.test(t) ? '在庫なし' : '', n: (li.querySelector('.textOverflowShohinmei span') || {}).textContent || '', u: `${location.origin}/commodity/1/${jan}/` }; }
        } else if (st === 'bic') {
          let cands = [];
          for (const t of toks) {
            const doc = new DOMParser().parseFromString(await sj(`/bc/category/?q=${encodeURIComponent(t)}`), 'text/html');
            cands = [...doc.querySelectorAll('li.prod_box[data-item-id]')].map(li => ({ id: li.getAttribute('data-item-id'), n: li.getAttribute('data-item-name') || '',
              p: toNum((li.querySelector('.bcs_price .val') || li.querySelector('.bcs_price') || {}).textContent), pt: toNum((li.querySelector('.bcs_point') || {}).textContent),
              ng: SOLD.test((li.querySelector('.bcs_nouki') || li).textContent) ? '在庫なし' : '' }))
              .filter(c => c.p > 0 && !/店舗のみ|海外仕様|ツーリスト|中古/.test(c.n) && nz(c.n).includes(nz(t)));
            await sleep(delay);
            if (cands.length) break;
          }
          if (bicId) cands = cands.filter(c => c.id === bicId);
          for (const c of cands.slice(0, 3)) {
            let cj = c.id === bicId ? jan : '';
            if (!cj) { const ih = await sj(`/bc/item/${c.id}/`); cj = (ih.match(/"goodsStkNo"\s*:\s*"(\d{8,14})"/) || [])[1] || ''; await sleep(delay); }
            if (cj === jan) { r = { p: c.p, pt: c.pt, ng: c.ng, n: c.n, u: `${location.origin}/bc/item/${c.id}/`, id: c.id }; break; }
          }
        }
        out[jan] = r || { none: 1 };
        blocked = 0;
      } catch (e) { out[jan] = { err: String(e.message || e).slice(0, 60) }; if (++blocked >= 4) break; }
      await sleep(delay);
    }
    return out;
  })();
}
async function grabStoresInTabs() {
  const settings = await getSettings();
  const wl = (await ghRead('docs/watchlist.json').catch(() => null)) || { items: [] };
  const prev = (await ghRead('data/stores.json').catch(() => null)) || {};
  const items = { ...(prev.items || {}) }, bicMap = { ...(prev.bicMap || {}) }, stats = {};
  const names = Object.fromEntries((wl.items || []).map(w => [String(w.jan), String(w.memo || '').replace(/\s*\[.*$/, '')]));
  const toks = name => [...new Set((String(name || '').normalize('NFKC').match(/[A-Za-z0-9][A-Za-z0-9\-\/]{3,}/g) || [])
    .filter(t => /[A-Za-z]/.test(t) && /\d/.test(t) && t.replace(/[-\/]/g, '').length >= 5 && !/^\d+(GB|TB|MM|ML|W|V|MAH)$/i.test(t)))].slice(0, 2);
  const jans = Object.keys(names).filter(j => /^\d{8,14}$/.test(j));
  const at = (j, st) => Date.parse(((items[j] || {})[st] || {}).at || 0) || 0;
  const conf = { kojima: ['https://www.kojima.net/ec/index.html', 3000], nojima: ['https://online.nojima.co.jp/', 1800], bic: ['https://www.biccamera.com/', 2000] };
  const per = settings.storesPer || 120;
  await Promise.all(Object.entries(conf).map(async ([st, [url, delay]]) => {
    let tab;
    try {
      const order = jans.filter(j => st !== 'bic' || toks(names[j]).length).sort((a, b) => at(a, st) - at(b, st)).slice(0, per);
      tab = await openWorkTab(url);
      await new Promise(r => setTimeout(r, 12000)); // 確認画面（ボット対策）が終わるのを待つ
      const list = order.map(j => ({ jan: j, toks: toks(names[j]), bicId: Object.keys(bicMap).find(k => bicMap[k] === j) || '' }));
      const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: storeLookup, args: [st, list, delay] });
      const got = (res && res.result) || {};
      let found = 0, err = 0;
      for (const [j, r] of Object.entries(got)) {
        if (r.err) { err++; continue; }
        if (r.id) { bicMap[r.id] = j; delete r.id; }
        if (!r.none) found++;
        items[j] = { ...(items[j] || {}), [st]: { ...r, at: new Date().toISOString() } };
      }
      stats[st] = { checked: Object.keys(got).length - err, found, failed: err };
    } catch (e) { stats[st] = { error: String(e.message || e).slice(0, 80) }; }
    finally { await closeWorkTab(tab); }
  }));
  await ghWrite('data/stores.json', { updated: new Date().toISOString(), items, bicMap, stats }, '家電量販店の価格を更新');
  return stats;
}

// ---------- ジョブ ----------
async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: 'offscreen.html',
    reasons: ['DOM_PARSER'],
    justification: '買取サイトのページを解析して買取価格を取り出すため',
  });
}

async function startJob(trigger) {
  const st = await getStatus();
  if (st.running && Date.now() - (st.startedAt || 0) < STALE_MS) return { ok: false, message: 'すでに実行中です' };
  const settings = await getSettings();
  if (!settings.token) {
    await setStatus({ running: false, text: '合鍵（トークン）が未設定のため実行できません。設定画面で入力してください。' });
    return { ok: false, message: '合鍵が未設定です' };
  }
  await setStatus({ running: true, startedAt: Date.now(), trigger, text: '開始しました', pct: 0 });
  report({ event: '開始（' + trigger + '）' });
  if (settings.sites.x !== false && (settings.xAccounts || []).length) {
    try {
      await setStatus({ running: true, startedAt: Date.now(), trigger, text: 'Xの投稿を読み込み中…', pct: 1 });
      const xs = await grabX();
      if (xs) await chrome.storage.local.set({ xStats: xs });
    } catch (e) { /* Xが読めなくても本体は続ける */ }
  }
  if (settings.sites.stores !== false) {
    try {
      await setStatus({ running: true, startedAt: Date.now(), trigger, text: '家電量販店の価格を確認中…', pct: 2 });
      const ss = await grabStoresInTabs();
      await chrome.storage.local.set({ storeStats: ss });
    } catch (e) { /* 量販店が読めなくても本体は続ける */ }
  }
  await ensureOffscreen();
  chrome.runtime.sendMessage({ target: 'offscreen', cmd: 'run', settings: { ...settings, storesInTab: true } });
  return { ok: true };
}

async function finishJob(result) {
  const st = await getStatus();
  const entry = { at: Date.now(), trigger: st.trigger, ok: result.ok, summary: result.summary, secs: Math.round((Date.now() - (st.startedAt || Date.now())) / 1000) };
  await setStatus({ running: false, text: result.summary, pct: 100, last: entry, history: [entry, ...(st.history || [])].slice(0, 20) });
  try { await chrome.offscreen.closeDocument(); } catch (e) { /* noop */ }
  await report({ event: (result.ok ? '完了' : 'エラーあり') + '（' + (st.trigger || '') + '）' });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.target === 'offscreen') return false;
  (async () => {
    if (msg.cmd === 'runNow') return startJob('手動');
    if (msg.cmd === 'progress') { await setStatus({ text: msg.text, pct: msg.pct }); return {}; }
    if (msg.cmd === 'done') { await finishJob(msg); return {}; }
    if (msg.cmd === 'getState') {
      const alarms = (await chrome.alarms.getAll()).filter(a => a.name.startsWith('run-'));
      return { status: await getStatus(), next: alarms.length ? Math.min(...alarms.map(a => a.scheduledTime)) : null };
    }
    return {};
  })().then(reply);
  return true;
});
