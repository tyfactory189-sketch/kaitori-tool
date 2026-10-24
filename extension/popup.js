const $ = id => document.getElementById(id);
const fmt = t => { const d = new Date(t); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function refresh() {
  const { status: st, next } = await chrome.runtime.sendMessage({ cmd: 'getState' });
  const { settings } = await chrome.storage.local.get('settings');
  if (settings && settings.repo) {
    const [u, r] = settings.repo.split('/');
    $('list').href = `https://${u}.github.io/${r}/`;
  }
  if (st.running) {
    $('now').innerHTML = `<b>取得中…</b>（${esc(st.trigger || '')}）<div>${esc(st.text || '')}</div><div class="bar"><div style="width:${Math.min(100, st.pct || 0)}%"></div></div><div class="sub">${fmt(st.startedAt)} 開始。Chrome を閉じずにお待ちください（閉じても次回やり直します）</div>`;
  } else if (!settings || !settings.token) {
    $('now').innerHTML = '<span class="ng">合鍵（トークン）が未設定です。</span><br><a href="options.html" target="_blank">設定画面</a>で入力してください。';
  } else {
    $('now').innerHTML = st.last ? `<span class="${st.last.ok ? 'ok' : 'ng'}">${st.last.ok ? '前回は成功' : '前回は一部失敗'}</span>（${fmt(st.last.at)}）<div class="sub">${esc(st.last.summary)}</div>` : '待機中';
  }
  $('run').disabled = !!st.running || !(settings && settings.token);
  $('next').textContent = next ? fmt(next) : '未設定';
  const h = st.history || [];
  if (h.length) $('hist').innerHTML = h.slice(0, 6).map(e => `<li><span class="${e.ok ? 'ok' : 'ng'}">${e.ok ? '✓' : '✕'}</span> ${fmt(e.at)} ${esc(e.trigger || '')}（${Math.round((e.secs || 0) / 60)}分）<div class="sub">${esc(e.summary)}</div></li>`).join('');
}
$('run').onclick = async () => {
  $('run').disabled = true;
  const r = await chrome.runtime.sendMessage({ cmd: 'runNow' });
  if (r && !r.ok) alert(r.message);
  refresh();
};
refresh();
setInterval(refresh, 2000);
