const $ = id => document.getElementById(id);
const DEF = { token: '', repo: 'tyfactory189-sketch/kaitori-tool', times: ['11:00', '14:00', '20:00'], sites: { wiki: true, variants: true, morimori: true }, startYahoo: true };

(async () => {
  const { settings } = await chrome.storage.local.get('settings');
  const s = { ...DEF, ...(settings || {}), sites: { ...DEF.sites, ...((settings || {}).sites || {}) } };
  $('token').value = s.token; $('repo').value = s.repo; $('times').value = s.times.join(', ');
  $('s_wiki').checked = s.sites.wiki; $('s_variants').checked = s.sites.variants; $('s_morimori').checked = s.sites.morimori;
  $('startYahoo').checked = s.startYahoo;
})();

$('save').onclick = async () => {
  const msg = (t, ok) => { $('msg').textContent = t; $('msg').className = ok ? 'ok' : 'ng'; };
  const times = $('times').value.split(/[,、\s]+/).filter(Boolean).map(t => {
    const m = t.replace('：', ':').replace(/時(\d{1,2})分?$/, ':$1').replace(/時$/, '').match(/^(\d{1,2})(?::(\d{1,2}))?$/);
    return m && +m[1] < 24 && +(m[2] || 0) < 60 ? `${m[1].padStart(2, '0')}:${(m[2] || '00').padStart(2, '0')}` : null;
  });
  if (times.includes(null) || !times.length) return msg('時刻は「11:00, 14:00, 20:00」のように入力してください', false);
  const repo = $('repo').value.trim();
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) return msg('リポジトリは「ユーザー名/リポジトリ名」の形で入力してください', false);
  const token = $('token').value.trim();
  const settings = { token, repo, times: [...new Set(times)].sort(), sites: { wiki: $('s_wiki').checked, variants: $('s_variants').checked, morimori: $('s_morimori').checked }, startYahoo: $('startYahoo').checked };
  await chrome.storage.local.set({ settings });
  $('times').value = settings.times.join(', ');
  if (!token) return msg('保存しました（合鍵が空なので自動取得は動きません）', false);
  // 合鍵の確認
  try {
    const r = await fetch('https://api.github.com/repos/' + repo, { headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' } });
    if (r.ok) {
      const j = await r.json();
      msg(j.permissions && j.permissions.push ? '保存しました。合鍵も確認できました ✓' : '保存しましたが、合鍵に書き込み権限がないようです', !!(j.permissions && j.permissions.push));
    } else msg(`保存しましたが、合鍵でリポジトリを開けませんでした（HTTP ${r.status}）`, false);
  } catch (e) { msg('保存しました（合鍵の確認はできませんでした）', true); }
};
