// 買取差益チェッカー 自動取得：バックグラウンド（予定の管理と、取得ジョブの起動・状態保存）
const DEFAULT_SETTINGS = {
  token: '',
  repo: 'tyfactory189-sketch/kaitori-tool',
  times: ['11:00', '14:00', '20:00'],
  sites: { wiki: true, variants: true, morimori: true, yahooUser: true, budget: true },
  startYahoo: true,
  sheet: { url: 'https://docs.google.com/spreadsheets/d/14RAmHsswRyA3yekaeUlINFWQ7Mt8jR1GPT0jfBn1Mks/edit?gid=0#gid=0', nameCol: 'B', amtCol: 'L', startRow: 4 },
};
const STALE_MS = 3 * 60 * 60e3; // 3時間以上「実行中」のままなら止まったとみなす

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}), sites: { ...DEFAULT_SETTINGS.sites, ...((settings || {}).sites || {}) }, sheet: { ...DEFAULT_SETTINGS.sheet, ...((settings || {}).sheet || {}) } };
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
    const api = (path, opt = {}) => fetch('https://api.github.com/repos/' + settings.repo + path, {
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
  await ensureOffscreen();
  chrome.runtime.sendMessage({ target: 'offscreen', cmd: 'run', settings });
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
