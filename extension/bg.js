// 買取差益チェッカー 自動取得：バックグラウンド（予定の管理と、取得ジョブの起動・状態保存）
const DEFAULT_SETTINGS = {
  token: '',
  repo: 'tyfactory189-sketch/kaitori-tool',
  times: ['11:00', '14:00', '20:00'],
  sites: { wiki: true, variants: true, morimori: true },
  startYahoo: true,
};
const STALE_MS = 3 * 60 * 60e3; // 3時間以上「実行中」のままなら止まったとみなす

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}), sites: { ...DEFAULT_SETTINGS.sites, ...((settings || {}).sites || {}) } };
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
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(async () => {
  await schedule();
  const st = await getStatus();
  if (st.running) await setStatus({ running: false, text: '前回の実行は Chrome の終了で中断されました' });
});
chrome.storage.onChanged.addListener((ch, area) => { if (area === 'local' && ch.settings) schedule(); });
chrome.alarms.onAlarm.addListener(a => { if (a.name.startsWith('run-')) startJob('定時（' + a.name.slice(4) + '）'); });

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
  await ensureOffscreen();
  chrome.runtime.sendMessage({ target: 'offscreen', cmd: 'run', settings });
  return { ok: true };
}

async function finishJob(result) {
  const st = await getStatus();
  const entry = { at: Date.now(), trigger: st.trigger, ok: result.ok, summary: result.summary, secs: Math.round((Date.now() - (st.startedAt || Date.now())) / 1000) };
  await setStatus({ running: false, text: result.summary, pct: 100, last: entry, history: [entry, ...(st.history || [])].slice(0, 20) });
  try { await chrome.offscreen.closeDocument(); } catch (e) { /* noop */ }
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
