const $ = id => document.getElementById(id);
const DEF = { token: '', repo: 'tyfactory189-sketch/kaitori-tool', times: ['11:00', '14:00', '20:00'], sites: { wiki: true, variants: true, morimori: true, yahooUser: true, budget: true }, startYahoo: true, sheet: { url: 'https://docs.google.com/spreadsheets/d/14RAmHsswRyA3yekaeUlINFWQ7Mt8jR1GPT0jfBn1Mks/edit?gid=0#gid=0', nameCol: 'B', amtCol: 'L', startRow: 4 } };

(async () => {
  const { settings } = await chrome.storage.local.get('settings');
  const s = { ...DEF, ...(settings || {}), sites: { ...DEF.sites, ...((settings || {}).sites || {}) } };
  $('token').value = s.token; $('repo').value = s.repo; $('times').value = s.times.join(', ');
  $('s_wiki').checked = s.sites.wiki; $('s_variants').checked = s.sites.variants; $('s_morimori').checked = s.sites.morimori; $('s_yahoo').checked = s.sites.yahooUser;
  $('startYahoo').checked = s.startYahoo;
  const sh = { ...DEF.sheet, ...(s.sheet || {}) };
  $('s_budget').checked = s.sites.budget !== false; $('sheetUrl').value = sh.url; $('nameCol').value = sh.nameCol; $('amtCol').value = sh.amtCol; $('startRow').value = sh.startRow; $('sheetPass').value = s.sitePass || sh.pass || '';
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
  const settings = { token, repo, times: [...new Set(times)].sort(), sites: { wiki: $('s_wiki').checked, variants: $('s_variants').checked, morimori: $('s_morimori').checked, yahooUser: $('s_yahoo').checked, budget: $('s_budget').checked }, startYahoo: $('startYahoo').checked,
    sheet: { url: $('sheetUrl').value.trim(), nameCol: ($('nameCol').value.trim() || 'B').toUpperCase(), amtCol: ($('amtCol').value.trim() || 'L').toUpperCase(), startRow: Math.max(1, parseInt($('startRow').value, 10) || 4) }, sitePass: $('sheetPass').value };
  if (settings.sitePass && settings.sitePass.length < 8) return msg('サイトのパスワードは8文字以上にしてください', false);
  await chrome.storage.local.set({ settings });
  $('times').value = settings.times.join(', ');
  // サイトのパスワードが GitHub の SITE_PASSWORD と同じか、公開中の暗号化データで確かめる
  if (settings.sitePass) {
    try {
      const [u, r] = repo.split('/');
      const er = await fetch(`https://${u}.github.io/${r}/data.enc.json`, { cache: 'no-store' });
      if (er.ok) {
        const enc = await er.json(), d = x => Uint8Array.from(atob(x), c => c.charCodeAt(0));
        const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(settings.sitePass), 'PBKDF2', false, ['deriveKey']);
        const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt: d(enc.salt), iterations: 200000, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
        try { await crypto.subtle.decrypt({ name: 'AES-GCM', iv: d(enc.iv) }, key, d(enc.ct)); }
        catch (e) { return msg('保存しましたが、サイトのパスワードが GitHub の SITE_PASSWORD と一致しません。同じものを入れてください', false); }
      }
    } catch (e) { /* 確認できないときはそのまま */ }
  }
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
